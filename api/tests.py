"""
API tests for NearNode.
Run: python manage.py test api
"""
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from core.models import Airport, Flight
from api import amadeus_client

User = get_user_model()

# Test-only credential; not used in production.
TEST_AUTH_SECRET = 'testpass123'


class NearestAlternateAPITest(TestCase):
    """Test nearest-alternate and nearest-airport endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', email='test@example.com', password=TEST_AUTH_SECRET
        )
        self.client.force_authenticate(user=self.user)
        self.url = '/api/nearest-alternate/'

    def test_nearest_alternate_requires_params(self):
        """Missing params return 400."""
        r = self.client.post(self.url, {}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_nearest_alternate_invalid_date(self):
        """Invalid date format returns 400."""
        r = self.client.post(
            self.url,
            {
                'origin_airport_code': 'MIL',
                'final_destination_address': 'London',
                'date': 'not-a-date',
                'radius_km': 100,
            },
            format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_nearest_alternate_valid_request_returns_200(self):
        """Valid POST returns 200 when real API config exists, else 400."""
        date = (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        r = self.client.post(
            self.url,
            {
                'origin_airport_code': 'MIL',
                'final_destination_address': 'London',
                'date': date,
                'radius_km': 100,
            },
            format='json',
        )
        data = r.json()
        if amadeus_client.is_configured():
            self.assertEqual(r.status_code, 200)
            self.assertIn('results', data)
            self.assertIn('count', data)
            self.assertIn('currency', data)
        else:
            self.assertEqual(r.status_code, 400)
            self.assertIn('error', data)
            self.assertIn('AMADEUS', data.get('error', '').upper())


class NearestAirportAPITest(TestCase):
    """Test nearest-airport endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser2', email='test2@example.com', password=TEST_AUTH_SECRET
        )
        self.client.force_authenticate(user=self.user)

    def test_nearest_airport_requires_lat_lon(self):
        """Missing lat/lon returns 400."""
        r = self.client.get('/api/nearest-airport/')
        self.assertEqual(r.status_code, 400)

    def test_nearest_airport_with_coords_returns_200_or_404(self):
        """With lat/lon returns 200 (if airports exist) or 404 (empty DB)."""
        r = self.client.get('/api/nearest-airport/?lat=51.47&lon=-0.45')
        self.assertIn(r.status_code, (200, 404))
        if r.status_code == 200:
            data = r.json()
            self.assertIn('airport', data)
            self.assertIn('iata_code', data)


class SmartNearestAlternateSearchTest(TestCase):
    """Covers nearby-origin expansion and deterministic sorting."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='smartuser', email='smart@example.com', password=TEST_AUTH_SECRET
        )
        self.client.force_authenticate(user=self.user)
        self.url = '/api/nearest-alternate/'
        self.search_date = (timezone.now() + timedelta(days=7)).date()

        self.airports = {
            'LUX': self._airport('ELLX', 'LUX', 'Luxembourg Findel', 'Luxembourg', 'Luxembourg', '49.6233', '6.2044'),
            'FRA': self._airport('EDDF', 'FRA', 'Frankfurt Airport', 'Frankfurt', 'Germany', '50.0379', '8.5622'),
            'BVA': self._airport('LFOB', 'BVA', 'Beauvais', 'Paris', 'France', '49.4544', '2.1128'),
            'ZAG': self._airport('LDZA', 'ZAG', 'Zagreb Airport', 'Zagreb', 'Croatia', '45.7429', '16.0688'),
        }

        # Origin alternatives within radius (Luxembourg + Germany/France) to Croatia.
        self._flight('LG100', 'Luxair', 'LUX', 'ZAG', 150, 150.00, 8)
        self._flight('LH200', 'Lufthansa', 'FRA', 'ZAG', 100, 90.00, 10)
        self._flight('FR300', 'Ryanair', 'BVA', 'ZAG', 120, 60.00, 12)

        self.amadeus_config_patch = patch('api.views.amadeus_client.is_configured', return_value=True)
        self.amadeus_search_patch = patch(
            'api.amadeus_client.search_flight_offers',
            side_effect=self._mock_search_flight_offers
        )
        self.ground_patch = patch(
            'api.ground_transport_client.get_ground_options',
            side_effect=self._mock_ground_options
        )
        self.amadeus_config_patch.start()
        self.amadeus_search_patch.start()
        self.ground_patch.start()
        self.addCleanup(self.amadeus_config_patch.stop)
        self.addCleanup(self.amadeus_search_patch.stop)
        self.addCleanup(self.ground_patch.stop)

    def _airport(self, icao, iata, name, city, country, lat, lon):
        return Airport.objects.create(
            icao_code=icao,
            iata_code=iata,
            name=name,
            city=city,
            country=country,
            latitude=Decimal(lat),
            longitude=Decimal(lon),
        )

    def _flight(self, number, airline, origin_iata, dest_iata, duration_min, price_eur, dep_hour):
        departure = timezone.make_aware(
            timezone.datetime.combine(self.search_date, timezone.datetime.min.time())
        ) + timedelta(hours=dep_hour)
        arrival = departure + timedelta(minutes=duration_min)
        return Flight.objects.create(
            flight_number=number,
            airline=airline,
            origin_airport=self.airports[origin_iata],
            destination_airport=self.airports[dest_iata],
            departure_time=departure,
            arrival_time=arrival,
            price_eur=Decimal(str(price_eur)),
            duration_minutes=duration_min,
            available_seats=20,
        )

    def _search(self, **overrides):
        payload = {
            'origin_query': 'Luxembourg',
            'destination_query': 'Croatia',
            'date': self.search_date.strftime('%Y-%m-%d'),
            'origin_radius_km': 320,
            'sort_by': 'cost',
            'sort_order': 'asc',
            'max_results': 10,
        }
        payload.update(overrides)
        return self.client.post(self.url, payload, format='json')

    def _mock_search_flight_offers(self, origin_iata, destination_iata, departure_date, return_date=None, adults=1):
        if destination_iata != 'ZAG':
            return []
        offers = {
            'LUX': {'price_eur': 150.0, 'duration_minutes': 150, 'airline': 'Luxair', 'number': 'LG100'},
            'FRA': {'price_eur': 90.0, 'duration_minutes': 100, 'airline': 'Lufthansa', 'number': 'LH200'},
            'BVA': {'price_eur': 60.0, 'duration_minutes': 120, 'airline': 'Ryanair', 'number': 'FR300'},
        }
        one = offers.get(origin_iata)
        if not one:
            return []
        total_minutes = one['duration_minutes'] * 2 if return_date else one['duration_minutes']
        return [{
            'id': '{}-{}-offer'.format(origin_iata, destination_iata),
            'price_eur': one['price_eur'],
            'duration_minutes': total_minutes,
            'trip_type': 'round_trip' if return_date else 'one_way',
            'airline': one['airline'],
            'number': one['number'],
        }]

    def _mock_ground_options(self, from_lat, from_lon, to_lat, to_lon):
        return [{
            'duration_minutes': 30,
            'cost_eur': 12.0,
            'estimated_cost_eur': 12.0,
            'distance_km': 25.0,
            'mode': 'transit',
            'name': 'Mock train',
            'transport_type': 'train',
            'provider': 'google_routes',
        }]

    def test_cross_border_origin_expansion_returns_multiple_origins(self):
        r = self._search()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data.get('count', 0), 2)
        origins = {item.get('origin_airport', {}).get('iata_code') for item in data.get('results', [])}
        self.assertIn('LUX', origins)
        self.assertIn('FRA', origins)

    def test_sort_by_duration(self):
        r = self._search(sort_by='duration')
        self.assertEqual(r.status_code, 200)
        results = r.json().get('results', [])
        self.assertGreaterEqual(len(results), 2)
        durations = [row['total_trip_time_minutes'] for row in results]
        self.assertEqual(durations, sorted(durations))

    def test_sort_by_origin_distance(self):
        r = self._search(sort_by='origin_distance_km')
        self.assertEqual(r.status_code, 200)
        results = r.json().get('results', [])
        self.assertGreaterEqual(len(results), 2)
        distances = [row['origin_distance_km'] for row in results]
        self.assertEqual(distances, sorted(distances))

    def test_response_includes_ground_and_flight_breakdown(self):
        r = self._search()
        self.assertEqual(r.status_code, 200)
        results = r.json().get('results', [])
        first = results[0]
        self.assertIn('ground_leg', first)
        self.assertIn('flight_leg', first)
        self.assertIn('flight_cost_eur', first)
        self.assertIn('ground_cost_eur', first)
        self.assertIn('origin_distance_km', first)
        self.assertIn('booking_options', first)
        self.assertIn('best_booking_option', first)
        self.assertGreaterEqual(len(first.get('booking_options', [])), 1)
        first_option = first['booking_options'][0]
        self.assertIn('booking_score', first_option)
        self.assertIn('provider_name', first_option)
        self.assertIn('booking_url', first_option)
        self.assertIn('provider_logo_url', first_option)
        self.assertTrue(first_option.get('booking_url', '').startswith('http'))
        self.assertIn('utm_source=nearnode', first_option.get('booking_url', ''))
        self.assertIn('nn_origin=', first_option.get('booking_url', ''))
        self.assertIn('nn_destination=', first_option.get('booking_url', ''))

        all_provider_names = {
            opt.get('provider_name')
            for item in results
            for opt in item.get('booking_options', [])
        }
        self.assertIn('Skyscanner', all_provider_names)
        self.assertTrue(
            any(name in all_provider_names for name in ('Luxair', 'Lufthansa'))
        )

    @override_settings(
        BOOKING_GLOBAL_SITES=[
            {
                'name': 'Custom OTA',
                'domain': 'example.com',
                'base_url': 'https://example.com/book/{origin}/{destination}/{date}',
                'price_multiplier': 1.01,
                'base_fee_eur': 1.0,
                'trust_score': 0.84,
                'refundability': 'partial',
                'included_baggage_kg': 15,
                'hidden_fee_risk': 0.11,
            }
        ],
        BOOKING_PROVIDER_TRACKING_PARAMS={
            'custom_ota': {'aff_id': 'partner42'}
        },
        BOOKING_LOCAL_AIRPORT_DIRECT_SITES={
            'ZAG': {'name': 'Croatia Airlines', 'domain': 'croatiaairlines.com', 'base_url': 'https://www.croatiaairlines.com'}
        },
    )
    def test_booking_sources_and_tracking_are_configurable_from_settings(self):
        r = self._search()
        self.assertEqual(r.status_code, 200)
        results = r.json().get('results', [])
        all_options = [opt for item in results for opt in item.get('booking_options', [])]
        provider_names = {opt.get('provider_name') for opt in all_options}
        self.assertIn('Custom OTA', provider_names)
        self.assertIn('Croatia Airlines', provider_names)
        self.assertNotIn('Skyscanner', provider_names)
        custom = next((opt for opt in all_options if opt.get('provider_name') == 'Custom OTA'), None)
        self.assertIsNotNone(custom)
        self.assertIn('aff_id=partner42', custom.get('booking_url', ''))

    @override_settings(BOOKING_URL_HEALTHCHECK_ENABLED=True)
    @patch('api.services.BookingComparisonService._check_provider_url_health')
    def test_healthcheck_filters_unhealthy_providers(self, mock_health):
        mock_health.side_effect = lambda url: 'skyscanner.net' not in url
        r = self._search()
        self.assertEqual(r.status_code, 200)
        results = r.json().get('results', [])
        all_provider_names = {
            opt.get('provider_name')
            for item in results
            for opt in item.get('booking_options', [])
        }
        self.assertNotIn('Skyscanner', all_provider_names)
        self.assertIn('Kayak', all_provider_names)

    def test_round_trip_requires_return_date(self):
        r = self._search(trip_type='round_trip')
        self.assertEqual(r.status_code, 400)
        self.assertIn('return_date', r.json().get('error', ''))

    def test_round_trip_uses_return_date(self):
        return_date = (self.search_date + timedelta(days=5)).strftime('%Y-%m-%d')
        r = self._search(trip_type='round_trip', return_date=return_date)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data.get('trip_type'), 'round_trip')
        first = data.get('results', [])[0]
        self.assertEqual(first.get('flight', {}).get('trip_type'), 'round_trip')


class BookingProviderHealthAPITest(TestCase):
    """Provider health monitoring endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='healthuser', email='health@example.com', password=TEST_AUTH_SECRET
        )
        self.client.force_authenticate(user=self.user)

    @override_settings(BOOKING_URL_HEALTHCHECK_ENABLED=True)
    @patch('api.services.BookingComparisonService._check_provider_url_health')
    def test_health_endpoint_returns_provider_status(self, mock_health):
        mock_health.side_effect = lambda url: 'kayak.com' not in url
        r = self.client.get('/api/booking-providers/health/?refresh=1&limit=8')
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload.get('healthcheck_enabled'))
        self.assertIn('providers', payload)
        self.assertLessEqual(len(payload.get('providers', [])), 8)
        by_name = {row.get('name'): row for row in payload.get('providers', [])}
        if 'Kayak' in by_name:
            self.assertFalse(by_name['Kayak'].get('is_healthy'))
