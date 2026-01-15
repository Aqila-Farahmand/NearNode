"""
Management command to load sample data for testing
"""
from django.core.management.base import BaseCommand
from core.models import Airport, Flight, GroundTransport, DelayPrediction
from datetime import datetime, timedelta
from decimal import Decimal


class Command(BaseCommand):
    help = 'Load sample airports, flights, and ground transport data'

    # Sample destination address for ground transport
    SAMPLE_DESTINATION_ADDRESS = '123 Main St, London'

    # Airline names
    BRITISH_AIRWAYS = 'British Airways'

    def handle(self, *args, **options):
        self.stdout.write('Loading sample data...')
        airports = self._create_airports()
        self._create_ground_transport(airports)
        base_date = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        self._create_flights(airports, base_date)
        self._create_delay_predictions(base_date)
        self.stdout.write(self.style.SUCCESS(
            'Sample data loaded successfully!'))

    def _create_airports(self):
        """Create sample airports and return a dictionary mapping IATA codes to airports."""
        airports_data = [
            {'iata': 'LHR', 'icao': 'EGLL', 'name': 'London Heathrow', 'city': 'London', 'country': 'UK',
             'lat': 51.4700, 'lon': -0.4543, 'lounge': True, 'pods': True, 'score': 8.5},
            {'iata': 'STN', 'icao': 'EGSS', 'name': 'London Stansted', 'city': 'London', 'country': 'UK',
             'lat': 51.8860, 'lon': 0.2389, 'lounge': False, 'pods': False, 'score': 6.0},
            {'iata': 'SOU', 'icao': 'EGHI', 'name': 'Southampton', 'city': 'Southampton', 'country': 'UK',
             'lat': 50.9503, 'lon': -1.3568, 'lounge': False, 'pods': False, 'score': 5.5},
            {'iata': 'MIL', 'icao': 'LIMC', 'name': 'Milan Malpensa', 'city': 'Milan', 'country': 'Italy',
             'lat': 45.6306, 'lon': 8.7281, 'lounge': True, 'pods': True, 'score': 7.5},
            {'iata': 'BRU', 'icao': 'EBBR', 'name': 'Brussels Airport', 'city': 'Brussels', 'country': 'Belgium',
             'lat': 50.9014, 'lon': 4.4844, 'lounge': True, 'pods': False, 'score': 7.0},
            {'iata': 'AMS', 'icao': 'EHAM', 'name': 'Amsterdam Schiphol', 'city': 'Amsterdam', 'country': 'Netherlands',
             'lat': 52.3105, 'lon': 4.7683, 'lounge': True, 'pods': True, 'score': 9.0},
            {'iata': 'JFK', 'icao': 'KJFK', 'name': 'John F. Kennedy International', 'city': 'New York', 'country': 'USA',
             'lat': 40.6413, 'lon': -73.7781, 'lounge': True, 'pods': True, 'score': 8.0},
            {'iata': 'CDG', 'icao': 'LFPG', 'name': 'Charles de Gaulle', 'city': 'Paris', 'country': 'France',
             'lat': 49.0097, 'lon': 2.5479, 'lounge': True, 'pods': True, 'score': 8.5},
        ]

        airports = {}
        for data in airports_data:
            airport, created = Airport.objects.get_or_create(
                iata_code=data['iata'],
                defaults={
                    'icao_code': data['icao'],
                    'name': data['name'],
                    'city': data['city'],
                    'country': data['country'],
                    'latitude': data['lat'],
                    'longitude': data['lon'],
                    'has_lounge': data['lounge'],
                    'has_sleeping_pods': data['pods'],
                    'layover_quality_score': data['score'],
                    'city_access_time': 30 if data['city'] != 'London' else 45,
                }
            )
            airports[data['iata']] = airport
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Created airport: {airport.name}'))
        return airports

    def _create_ground_transport(self, airports):
        """Create sample ground transport options."""
        transport_data = [
            {'name': 'Stansted Express', 'type': 'train', 'from': 'STN', 'to': None,
             'address': self.SAMPLE_DESTINATION_ADDRESS, 'duration': 45, 'cost': 25.00, 'distance': 50},
            {'name': 'Southampton Airport Parkway', 'type': 'train', 'from': 'SOU', 'to': None,
             'address': self.SAMPLE_DESTINATION_ADDRESS, 'duration': 90, 'cost': 35.00, 'distance': 120},
            {'name': 'Heathrow Express', 'type': 'train', 'from': 'LHR', 'to': None,
             'address': self.SAMPLE_DESTINATION_ADDRESS, 'duration': 15, 'cost': 25.00, 'distance': 25},
            {'name': 'Thalys High Speed', 'type': 'train', 'from': 'BRU', 'to': 'AMS',
             'address': None, 'duration': 60, 'cost': 45.00, 'distance': 200},
            {'name': 'Uber', 'type': 'uber', 'from': 'STN', 'to': None,
             'address': self.SAMPLE_DESTINATION_ADDRESS, 'duration': 60, 'cost': 80.00, 'distance': 50},
        ]

        for data in transport_data:
            from_airport = airports[data['from']]
            to_airport = airports.get(data['to']) if data['to'] else None

            transport, created = GroundTransport.objects.get_or_create(
                name=data['name'],
                from_airport=from_airport,
                defaults={
                    'transport_type': data['type'],
                    'to_airport': to_airport,
                    # Convert None to empty string
                    'to_address': data['address'] or '',
                    'duration_minutes': data['duration'],
                    'cost_eur': Decimal(str(data['cost'])),
                    'distance_km': Decimal(str(data['distance'])) if data.get('distance') else None,
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Created transport: {transport.name}'))

    def _create_flights(self, airports, base_date):
        """Create sample flights."""
        flights_data = [
            {'number': 'BA456', 'airline': self.BRITISH_AIRWAYS, 'origin': 'MIL', 'dest': 'LHR',
             'departure': base_date + timedelta(days=7), 'duration': 120, 'price': 350.00, 'delay_prob': 20},
            {'number': 'FR123', 'airline': 'Ryanair', 'origin': 'MIL', 'dest': 'STN',
             'departure': base_date + timedelta(days=7, hours=2), 'duration': 135, 'price': 120.00, 'delay_prob': 25},
            {'number': 'BA789', 'airline': self.BRITISH_AIRWAYS, 'origin': 'MIL', 'dest': 'SOU',
             'departure': base_date + timedelta(days=7, hours=4), 'duration': 150, 'price': 180.00, 'delay_prob': 15},
            {'number': 'SN456', 'airline': 'Brussels Airlines', 'origin': 'MIL', 'dest': 'BRU',
             'departure': base_date + timedelta(days=7), 'duration': 90, 'price': 150.00, 'delay_prob': 18},
            {'number': 'KL789', 'airline': 'KLM', 'origin': 'BRU', 'dest': 'AMS',
             'departure': base_date + timedelta(days=7, hours=3), 'duration': 60, 'price': 80.00, 'delay_prob': 12},
            {'number': 'AF234', 'airline': 'Air France', 'origin': 'MIL', 'dest': 'CDG',
             'departure': base_date + timedelta(days=7, hours=1), 'duration': 100, 'price': 200.00, 'delay_prob': 22},
        ]

        for data in flights_data:
            origin = airports[data['origin']]
            dest = airports[data['dest']]
            departure = data['departure']
            arrival = departure + timedelta(minutes=data['duration'])

            flight, created = Flight.objects.get_or_create(
                flight_number=data['number'],
                origin_airport=origin,
                destination_airport=dest,
                departure_time=departure,
                defaults={
                    'airline': data['airline'],
                    'arrival_time': arrival,
                    'price_eur': Decimal(str(data['price'])),
                    'duration_minutes': data['duration'],
                    'available_seats': 50,
                    'historical_delay_probability': Decimal(str(data['delay_prob'])),
                    'avg_delay_minutes': int(data['delay_prob'] * 1.5),
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Created flight: {flight.flight_number}'))

    def _create_delay_predictions(self, base_date):
        """Create sample delay predictions."""
        delay_data = [
            {'route': 'MIL-LHR', 'airline': self.BRITISH_AIRWAYS,
                'day': 0, 'delay_prob': 20, 'avg_delay': 30},
            {'route': 'MIL-STN', 'airline': 'Ryanair',
                'day': 0, 'delay_prob': 25, 'avg_delay': 35},
            {'route': 'BRU-AMS', 'airline': 'KLM', 'day': 0,
                'delay_prob': 12, 'avg_delay': 20},
        ]

        for data in delay_data:
            pred, created = DelayPrediction.objects.get_or_create(
                route=data['route'],
                airline=data['airline'],
                day_of_week=data['day'],
                time_of_day=base_date.time(),
                defaults={
                    'delay_probability': Decimal(str(data['delay_prob'])),
                    'avg_delay_minutes': data['avg_delay'],
                    'sample_size': 100,
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Created delay prediction: {pred.route}'))
