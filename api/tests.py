"""
API tests for NearNode.
Run: python manage.py test api
"""
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta


class NearestAlternateAPITest(TestCase):
    """Test nearest-alternate and nearest-airport endpoints."""

    def setUp(self):
        self.client = Client()
        self.url = '/api/nearest-alternate/'

    def test_nearest_alternate_requires_params(self):
        """Missing params return 400."""
        r = self.client.post(
            self.url,
            {},
            content_type='application/json',
        )
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
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_nearest_alternate_valid_request_returns_200(self):
        """Valid POST returns 200 and results/hint."""
        date = (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        r = self.client.post(
            self.url,
            {
                'origin_airport_code': 'MIL',
                'final_destination_address': 'London',
                'date': date,
                'radius_km': 100,
            },
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('results', data)
        self.assertIn('count', data)
        self.assertIn('currency', data)


class NearestAirportAPITest(TestCase):
    """Test nearest-airport endpoint."""

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
