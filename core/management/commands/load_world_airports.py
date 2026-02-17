"""
Management command to load world airports from OurAirports CSV.
Run: python manage.py load_world_airports
Downloads the CSV once and populates the Airport model for the profile dropdown.
"""
import csv
import io
from decimal import Decimal

import requests
from django.core.management.base import BaseCommand

from core.models import Airport


# OurAirports CSV: https://davidmegginson.github.io/ourairports-data/airports.csv
AIRPORTS_CSV_URL = (
    'https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv'
)
# Only load these types (commercial/significant airports with IATA codes)
TYPES = {'large_airport', 'medium_airport', 'small_airport'}


def _parse_airport_row(row):
    """Parse a CSV row into (icao_code, defaults) or None if skip."""
    if (row.get('type') or '').strip() not in TYPES:
        return None
    ident = (row.get('ident') or '').strip()[:4]
    iata = (row.get('iata_code') or '').strip()[:3]
    if not ident or not iata:
        return None
    try:
        lat = Decimal(row.get('latitude_deg', 0))
        lon = Decimal(row.get('longitude_deg', 0))
    except Exception:
        return None
    return (ident.upper(), {
        'iata_code': iata.upper(),
        'name': (row.get('name') or '')[:200],
        'city': (row.get('municipality') or '')[:100],
        'country': (row.get('iso_country') or '')[:100],
        'latitude': lat,
        'longitude': lon,
        'has_lounge': False,
        'has_sleeping_pods': False,
        'city_access_time': 0,
        'layover_quality_score': Decimal('0'),
    })


def _upsert_airport(icao_code, defaults):
    """Create or update one airport. Returns 'created', 'updated', or 'skipped'."""
    try:
        _, was_created = Airport.objects.update_or_create(
            icao_code=icao_code,
            defaults=defaults,
        )
        return 'created' if was_created else 'updated'
    except Exception:
        try:
            Airport.objects.filter(icao_code=icao_code).update(**defaults)
            return 'updated'
        except Exception:
            return 'skipped'


class Command(BaseCommand):
    help = 'Load world airports from OurAirports CSV for the home airport dropdown'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            default=AIRPORTS_CSV_URL,
            help='URL of airports CSV (default: OurAirports)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max number of airports to load (0 = no limit)',
        )

    def handle(self, *args, **options):
        url = options['url']
        limit = options['limit']
        self.stdout.write('Fetching airports from {} ...'.format(url))
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR('Failed to fetch CSV: {}'.format(e)))
            return
        reader = csv.DictReader(io.StringIO(resp.text))
        counts = {'created': 0, 'updated': 0, 'skipped': 0}
        for row in reader:
            if limit and (counts['created'] + counts['updated']) >= limit:
                break
            parsed = _parse_airport_row(row)
            if not parsed:
                counts['skipped'] += 1
                continue
            icao_code, defaults = parsed
            result = _upsert_airport(icao_code, defaults)
            counts[result] += 1
        self.stdout.write(
            self.style.SUCCESS(
                'Done. Created: {}, Updated: {}, Skipped: {}'.format(
                    counts['created'], counts['updated'], counts['skipped']
                )
            )
        )
