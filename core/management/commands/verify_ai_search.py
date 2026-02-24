"""
Verify AI Search has data and can resolve an origin city to flights.

Run (with venv active): python manage.py verify_ai_search

Requires airports and flights in the database (e.g. load_world_airports + your own flight data or Amadeus).
"""
from django.core.management.base import BaseCommand
from core.models import Airport, Flight
from api.services import AISearchService


class Command(BaseCommand):
    help = 'Verify AI Search: airport count, flight count, and origin resolution from database'

    def handle(self, *args, **options):
        airport_count = Airport.objects.count()
        flight_count = Flight.objects.count()
        self.stdout.write('Airports: {}'.format(airport_count))
        self.stdout.write('Flights: {}'.format(flight_count))

        if airport_count == 0 or flight_count == 0:
            self.stdout.write(self.style.WARNING(
                'No data. Add airports (e.g. load_world_airports) and flight data to the database.'
            ))
            return

        available = AISearchService.get_available_origin_cities()
        if not available:
            self.stdout.write(self.style.WARNING(
                'No origin cities with flights. Add flight data to the database.'
            ))
            return

        sample_origin = available[0]
        origin = AISearchService._resolve_origin_airport(sample_origin)
        if not origin:
            self.stdout.write(self.style.WARNING(
                '"{}" did not resolve to an airport.'.format(sample_origin)
            ))
            return
        self.stdout.write(
            '"From {}" -> {} ({})'.format(sample_origin, origin.name, origin.iata_code))
        from_count = Flight.objects.filter(origin_airport=origin).count()
        self.stdout.write('Flights from {}: {}'.format(
            origin.iata_code, from_count))
        if from_count == 0:
            self.stdout.write(self.style.WARNING(
                'No flights from {}. Add flight data for this origin.'.format(
                    origin.iata_code)
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'AI Search can return results for "From {}". Try it in the app.'.format(sample_origin)
            ))
