"""
Seed a minimal set of airports, flights, and trains for multi-modal search demo.

Ensures you can try: origin LHR, destination CDG, and get direct, connection,
and train-link (via BRU -> train -> AMS) results.

Run: python manage.py seed_multimodal_demo [--date YYYY-MM-DD]
"""
from datetime import datetime, date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Airport, Flight, GroundTransport


# Demo airports: London, Brussels, Amsterdam, Paris
DEMO_AIRPORTS = [
    {'icao': 'EGLL', 'iata': 'LHR', 'name': 'London Heathrow', 'city': 'London', 'country': 'United Kingdom',
     'lat': '51.4700', 'lon': '-0.4543', 'layover_score': '7.00', 'has_lounge': True, 'city_mins': 45},
    {'icao': 'EBBR', 'iata': 'BRU', 'name': 'Brussels Airport', 'city': 'Brussels', 'country': 'Belgium',
     'lat': '50.9014', 'lon': '4.4844', 'layover_score': '6.50', 'has_lounge': True, 'city_mins': 25},
    {'icao': 'EHAM', 'iata': 'AMS', 'name': 'Amsterdam Schiphol', 'city': 'Amsterdam', 'country': 'Netherlands',
     'lat': '52.3105', 'lon': '4.7683', 'layover_score': '8.00', 'has_lounge': True, 'has_sleeping_pods': True, 'city_mins': 20},
    {'icao': 'LFPG', 'iata': 'CDG', 'name': 'Paris Charles de Gaulle', 'city': 'Paris', 'country': 'France',
     'lat': '49.0097', 'lon': '2.5478', 'layover_score': '6.00', 'has_lounge': True, 'city_mins': 35},
]


def get_or_create_airport(data):
    airport, created = Airport.objects.get_or_create(
        iata_code=data['iata'],
        defaults={
            'icao_code': data['icao'],
            'name': data['name'],
            'city': data['city'],
            'country': data['country'],
            'latitude': Decimal(data['lat']),
            'longitude': Decimal(data['lon']),
            'layover_quality_score': Decimal(data.get('layover_score', '0')),
            'has_lounge': data.get('has_lounge', False),
            'has_sleeping_pods': data.get('has_sleeping_pods', False),
            'city_access_time': data.get('city_mins', 0),
        }
    )
    return airport, created


def ensure_demo_airports(stdout, style):
    airports = {}
    for data in DEMO_AIRPORTS:
        airport, created = get_or_create_airport(data)
        airports[data['iata']] = airport
        if created:
            stdout.write(style.SUCCESS('  Created airport {}'.format(airport.iata_code)))
    return airports


def ensure_demo_flights(airports, flight_date, stdout, style):
    """Create flights so we have direct, connection, and train-link options (LHR -> CDG)."""
    # Use UTC so departure_time__date=date matches regardless of server TZ
    base = datetime.combine(flight_date, time(0, 0), tzinfo=timezone.utc)
    flights_created = 0

    # LHR -> CDG direct
    f = Flight.objects.filter(
        origin_airport=airports['LHR'],
        destination_airport=airports['CDG'],
        departure_time__date=flight_date
    ).first()
    if not f:
        Flight.objects.create(
            flight_number='BA304',
            airline='British Airways',
            origin_airport=airports['LHR'],
            destination_airport=airports['CDG'],
            departure_time=base + timedelta(hours=9, minutes=0),
            arrival_time=base + timedelta(hours=11, minutes=30),
            price_eur=Decimal('120.00'),
            duration_minutes=150,
        )
        flights_created += 1

    # LHR -> BRU (first leg for connection and train-link)
    f = Flight.objects.filter(
        origin_airport=airports['LHR'],
        destination_airport=airports['BRU'],
        departure_time__date=flight_date
    ).first()
    if not f:
        Flight.objects.create(
            flight_number='SN2104',
            airline='Brussels Airlines',
            origin_airport=airports['LHR'],
            destination_airport=airports['BRU'],
            departure_time=base + timedelta(hours=8, minutes=0),
            arrival_time=base + timedelta(hours=10, minutes=30),
            price_eur=Decimal('85.00'),
            duration_minutes=150,
        )
        flights_created += 1

    # BRU -> CDG (second leg for same-airport connection)
    f = Flight.objects.filter(
        origin_airport=airports['BRU'],
        destination_airport=airports['CDG'],
        departure_time__date=flight_date
    ).first()
    if not f:
        Flight.objects.create(
            flight_number='AF1342',
            airline='Air France',
            origin_airport=airports['BRU'],
            destination_airport=airports['CDG'],
            departure_time=base + timedelta(hours=14, minutes=0),
            arrival_time=base + timedelta(hours=15, minutes=0),
            price_eur=Decimal('75.00'),
            duration_minutes=60,
        )
        flights_created += 1

    # AMS -> CDG (second leg for train-link: LHR->BRU, train BRU->AMS, AMS->CDG)
    f = Flight.objects.filter(
        origin_airport=airports['AMS'],
        destination_airport=airports['CDG'],
        departure_time__date=flight_date
    ).first()
    if not f:
        Flight.objects.create(
            flight_number='KL1234',
            airline='KLM',
            origin_airport=airports['AMS'],
            destination_airport=airports['CDG'],
            departure_time=base + timedelta(hours=16, minutes=0),
            arrival_time=base + timedelta(hours=17, minutes=15),
            price_eur=Decimal('90.00'),
            duration_minutes=75,
        )
        flights_created += 1

    if flights_created:
        stdout.write(style.SUCCESS('  Created {} flight(s)'.format(flights_created)))
    return flights_created


def ensure_demo_train(airports, stdout, style):
    """Create train BRU -> AMS so train-link LHR->BRU->(train)->AMS->CDG is possible."""
    train = GroundTransport.objects.filter(
        from_airport=airports['BRU'],
        to_airport=airports['AMS'],
        transport_type='train'
    ).first()
    if not train:
        GroundTransport.objects.create(
            name='Thalys Brussels–Amsterdam',
            transport_type='train',
            from_airport=airports['BRU'],
            to_airport=airports['AMS'],
            duration_minutes=110,
            cost_eur=Decimal('29.00'),
            distance_km=Decimal('209.00'),
        )
        stdout.write(style.SUCCESS('  Created train BRU -> AMS'))
        return 1
    return 0


class Command(BaseCommand):
    help = 'Seed minimal airports, flights, and trains for multi-modal search demo (LHR -> CDG)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Flight date YYYY-MM-DD (default: 7 days from today)',
        )

    def handle(self, *args, **options):
        date_str = options.get('date')
        if date_str:
            try:
                flight_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                self.stderr.write(self.style.ERROR('Invalid --date; use YYYY-MM-DD'))
                return
        else:
            flight_date = date.today() + timedelta(days=7)

        self.stdout.write('Seeding multi-modal demo for date {}'.format(flight_date))

        self.stdout.write('Airports (LHR, BRU, AMS, CDG)...')
        airports = ensure_demo_airports(self.stdout, self.style)

        self.stdout.write('Flights (LHR<->BRU<->AMS<->CDG)...')
        ensure_demo_flights(airports, flight_date, self.stdout, self.style)

        self.stdout.write('Train BRU -> AMS...')
        ensure_demo_train(airports, self.stdout, self.style)

        self.stdout.write(self.style.SUCCESS(
            'Done. Try multi-modal search: origin LHR, destination CDG, date {}.'.format(flight_date)
        ))
