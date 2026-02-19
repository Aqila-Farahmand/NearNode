"""
Debug multi-modal search: show why no connections are found.

Run: python manage.py debug_multimodal [--origin LHR] [--destination CDG] [--date YYYY-MM-DD]
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from core.models import Airport, Flight, GroundTransport
from api.services import MultiModalConnectionService


class Command(BaseCommand):
    help = 'Debug multi-modal search: list flights/trains and run search for given origin, dest, date'

    def add_arguments(self, parser):
        parser.add_argument('--origin', default='LHR', help='Origin IATA (default: LHR)')
        parser.add_argument('--destination', default='CDG', help='Destination IATA (default: CDG)')
        parser.add_argument('--date', type=str, default=None, help='Date YYYY-MM-DD (default: 7 days from today)')

    def handle(self, *args, **options):
        origin_code = options['origin'].strip().upper()
        dest_code = options['destination'].strip().upper()
        date_str = options.get('date')
        if date_str:
            try:
                search_date = date.fromisoformat(date_str)
            except ValueError:
                self.stderr.write(self.style.ERROR('Invalid --date; use YYYY-MM-DD'))
                return
        else:
            search_date = date.today() + timedelta(days=7)

        self.stdout.write('Multi-modal debug: {} -> {} on {}'.format(origin_code, dest_code, search_date))
        self.stdout.write('')

        # Resolve airports
        try:
            origin = Airport.objects.get(iata_code__iexact=origin_code)
            destination = Airport.objects.get(iata_code__iexact=dest_code)
        except Airport.DoesNotExist as e:
            self.stderr.write(self.style.ERROR('Airport not found: {}'.format(e)))
            self.stdout.write('Available LHR/BRU/AMS/CDG: run python manage.py seed_multimodal_demo --date {}'.format(search_date))
            return

        self.stdout.write('Airports: {} (id={}), {} (id={})'.format(
            origin.iata_code, origin.id, destination.iata_code, destination.id))

        # Flights on this date
        all_on_date = Flight.objects.filter(departure_time__date=search_date)
        count_on_date = all_on_date.count()
        self.stdout.write('Flights on {}: total {}'.format(search_date, count_on_date))

        if count_on_date == 0:
            self.stdout.write(self.style.WARNING(
                'No flights on this date. Seed data with: python manage.py seed_multimodal_demo --date {}'.format(search_date)
            ))
        else:
            for f in all_on_date.select_related('origin_airport', 'destination_airport')[:30]:
                self.stdout.write('  {} {} -> {}  dep={}'.format(
                    f.flight_number,
                    f.origin_airport.iata_code,
                    f.destination_airport.iata_code,
                    f.departure_time,
                ))

        direct = Flight.objects.filter(
            origin_airport=origin,
            destination_airport=destination,
            departure_time__date=search_date,
        )
        self.stdout.write('Direct {} -> {} on date: {}'.format(origin_code, dest_code, direct.count()))

        first_legs = Flight.objects.filter(
            origin_airport=origin,
            departure_time__date=search_date,
        ).exclude(destination_airport=destination)
        self.stdout.write('First legs {} -> (not {}) on date: {}'.format(origin_code, dest_code, first_legs.count()))

        trains = GroundTransport.objects.filter(transport_type='train').exclude(to_airport__isnull=True)
        self.stdout.write('Trains (any): {}'.format(trains.count()))
        for t in trains.select_related('from_airport', 'to_airport')[:10]:
            self.stdout.write('  {} -> {}  {} min'.format(
                t.from_airport.iata_code, t.to_airport.iata_code, t.duration_minutes))

        # Run the actual service
        self.stdout.write('')
        connections = MultiModalConnectionService.create_multi_modal_connection(origin, destination, search_date)
        by_type = {}
        for c in connections:
            t = c['type']
            by_type[t] = by_type.get(t, 0) + 1

        self.stdout.write('Connections returned: {}'.format(len(connections)))
        for t, n in sorted(by_type.items()):
            self.stdout.write('  {}: {}'.format(t, n))

        if len(connections) == 0 and count_on_date > 0:
            self.stdout.write(self.style.WARNING(
                'Flights exist for date but no connections. Check that routes match (e.g. LHR->BRU, BRU->CDG, AMS->CDG, train BRU->AMS).'
            ))
