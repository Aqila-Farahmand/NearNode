"""
Amadeus API client for real flight search.
Uses Flight Offers Search when AMADEUS_API_KEY and AMADEUS_API_SECRET are set.
"""
import time
import requests
from django.conf import settings

# Token cache (in production use Redis or similar)
_token_cache = {'token': None, 'expires': 0}
BASE_URL = 'https://test.api.amadeus.com'
TOKEN_URL = BASE_URL + '/v1/security/oauth2/token'
FLIGHT_OFFERS_URL = BASE_URL + '/v2/shopping/flight-offers'


def _get_api_key():
    try:
        from decouple import config
        return config('AMADEUS_API_KEY', default='').strip()
    except Exception:
        return getattr(settings, 'AMADEUS_API_KEY', '') or ''


def _get_api_secret():
    try:
        from decouple import config
        return config('AMADEUS_API_SECRET', default='').strip()
    except Exception:
        return getattr(settings, 'AMADEUS_API_SECRET', '') or ''


def is_configured():
    """Return True if Amadeus credentials are set."""
    return bool(_get_api_key() and _get_api_secret())


def get_token():
    """Get OAuth token; use cache until near expiry."""
    now = time.time()
    if _token_cache['token'] and _token_cache['expires'] > now + 60:
        return _token_cache['token']
    key = _get_api_key()
    secret = _get_api_secret()
    if not key or not secret:
        return None
    resp = requests.post(
        TOKEN_URL,
        data={
            'grant_type': 'client_credentials',
            'client_id': key,
            'client_secret': secret,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=10,
    )
    if not resp.ok:
        return None
    data = resp.json()
    _token_cache['token'] = data.get('access_token')
    _token_cache['expires'] = now + (data.get('expires_in', 1799) - 60)
    return _token_cache['token']


def search_flight_offers(origin_iata, destination_iata, departure_date, adults=1):
    """
    Call Amadeus Flight Offers Search. Returns list of offer dicts with
    id, price_eur, duration_minutes, airline (first carrier), segments.
    """
    token = get_token()
    if not token:
        return []
    params = {
        'originLocationCode': origin_iata[:3],
        'destinationLocationCode': destination_iata[:3],
        'departureDate': departure_date,
        'adults': adults,
    }
    resp = requests.get(
        FLIGHT_OFFERS_URL,
        params=params,
        headers={'Authorization': 'Bearer ' + token},
        timeout=15,
    )
    if not resp.ok:
        return []
    data = resp.json()
    offers = data.get('data') or []
    return [_map_one_offer(offer) for offer in offers]


def _map_one_offer(offer):
    """Map one Amadeus flight offer to our minimal flight dict."""
    price = offer.get('price', {}) or {}
    try:
        price_eur = float(price.get('total', '0'))
    except (TypeError, ValueError):
        price_eur = 0.0
    itineraries = offer.get('itineraries') or []
    duration_str = (itineraries[0].get('duration') or 'PT0M')[2:] if itineraries else 'PT0M'
    duration_minutes = _parse_iso_duration(duration_str)
    segments = (itineraries[0].get('segments') or []) if itineraries else []
    seg0 = segments[0] if segments else {}
    operating = seg0.get('operating') or {}
    airline = (operating.get('carrierCode') if isinstance(operating, dict) else None) or seg0.get('carrierCode', '') or 'Airline'
    return {
        'id': offer.get('id'),
        'price_eur': price_eur,
        'duration_minutes': duration_minutes,
        'airline': airline,
        'number': seg0.get('number', '') or (offer.get('id', '')[:6]),
    }


def _parse_iso_duration(s):
    """Parse ISO 8601 duration (e.g. PT2H10M) to minutes."""
    s = (s or 'PT0M').upper().replace('PT', '')
    minutes = 0
    acc = ''
    for c in s:
        if c == 'H':
            minutes += 60 * int(acc or 0)
            acc = ''
        elif c == 'M':
            minutes += int(acc or 0)
            acc = ''
        elif c.isdigit():
            acc += c
        else:
            acc = ''
    return minutes
