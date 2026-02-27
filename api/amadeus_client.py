"""
Amadeus API client for real flight search.
Uses Flight Offers Search when AMADEUS_API_KEY and AMADEUS_API_SECRET are set.
"""
import time
import requests
from django.conf import settings

# Token cache (in production use Redis or similar)
_token_cache = {'token': None, 'expires': 0}


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


def _normalize_base_url(url):
    return (url or '').strip().rstrip('/')


def _normalize_path(path):
    value = (path or '').strip()
    if not value:
        return ''
    return value if value.startswith('/') else '/' + value


def _token_url():
    base = _normalize_base_url(getattr(settings, 'AMADEUS_BASE_URL', ''))
    path = _normalize_path(getattr(settings, 'AMADEUS_TOKEN_PATH', ''))
    return base + path


def _flight_offers_url():
    base = _normalize_base_url(getattr(settings, 'AMADEUS_BASE_URL', ''))
    path = _normalize_path(getattr(settings, 'AMADEUS_FLIGHT_OFFERS_PATH', ''))
    return base + path


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
        _token_url(),
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


def _fetch_flight_offers_raw(origin_iata, destination_iata, departure_date, return_date=None, adults=1):
    """Call Amadeus Flight Offers Search. Returns raw list of offer dicts from API."""
    token = get_token()
    if not token:
        return []
    params = {
        'originLocationCode': origin_iata[:3],
        'destinationLocationCode': destination_iata[:3],
        'departureDate': departure_date,
        'adults': adults,
    }
    if return_date:
        params['returnDate'] = return_date
    resp = requests.get(
        _flight_offers_url(),
        params=params,
        headers={'Authorization': 'Bearer ' + token},
        timeout=15,
    )
    if not resp.ok:
        return []
    data = resp.json()
    return data.get('data') or []


def search_flight_offers(origin_iata, destination_iata, departure_date, return_date=None, adults=1):
    """
    Call Amadeus Flight Offers Search. Returns list of offer dicts with
    id, price_eur, duration_minutes, airline (first carrier), segments.
    """
    offers = _fetch_flight_offers_raw(
        origin_iata,
        destination_iata,
        departure_date,
        return_date=return_date,
        adults=adults,
    )
    return [_map_one_offer(offer) for offer in offers]


def search_flight_offers_for_ai_search(origin_iata, destination_iata, departure_date, origin_airport_dict=None, destination_airport_dict=None, adults=1):
    """
    Same as search_flight_offers but returns flight dicts with origin_airport, destination_airport,
    departure_time, arrival_time for AI search / frontend display.
    """
    offers = _fetch_flight_offers_raw(
        origin_iata,
        destination_iata,
        departure_date,
        adults=adults,
    )
    origin = origin_airport_dict or {'iata_code': origin_iata[:3], 'name': origin_iata, 'city': ''}
    dest = destination_airport_dict or {'iata_code': destination_iata[:3], 'name': destination_iata, 'city': ''}
    return [_map_one_offer_rich(offer, origin, dest) for offer in offers]


def _map_one_offer_rich(offer, origin_airport_dict, destination_airport_dict):
    """Map one Amadeus offer to a flight dict with airport and times for AI search display."""
    base = _map_one_offer(offer)
    itineraries = offer.get('itineraries') or []
    segments = (itineraries[0].get('segments') or []) if itineraries else []
    seg0 = segments[0] if segments else {}
    dep = (seg0.get('departure') or {}).get('at') or ''
    arr = (seg0.get('arrival') or {}).get('at') or ''
    base['origin_airport'] = origin_airport_dict
    base['destination_airport'] = destination_airport_dict
    base['departure_time'] = dep
    base['arrival_time'] = arr
    base['flight_number'] = base.get('number', '') or ''
    return base


def _price_total_eur(offer):
    price = offer.get('price', {}) or {}
    try:
        return float(price.get('total', '0'))
    except (TypeError, ValueError):
        return 0.0


def _itinerary_at(itineraries, idx):
    return itineraries[idx] if len(itineraries) > idx else {}


def _segments_for_itinerary(itinerary):
    return (itinerary.get('segments') or []) if itinerary else []


def _segment_time(segment, side):
    return (segment.get(side) or {}).get('at', '') if segment else ''


def _airline_from_segment(segment):
    operating = segment.get('operating') or {}
    operating_code = operating.get('carrierCode') if isinstance(operating, dict) else None
    return operating_code or segment.get('carrierCode', '') or 'Airline'


def _map_one_offer(offer):
    """Map one Amadeus flight offer to our minimal flight dict."""
    price_eur = _price_total_eur(offer)
    itineraries = offer.get('itineraries') or []
    outbound = _itinerary_at(itineraries, 0)
    inbound = _itinerary_at(itineraries, 1)
    outbound_duration_minutes = _parse_iso_duration(outbound.get('duration') or 'PT0M')
    return_duration_minutes = _parse_iso_duration(inbound.get('duration') or 'PT0M')
    duration_minutes = outbound_duration_minutes + return_duration_minutes
    segments = _segments_for_itinerary(outbound)
    seg0 = segments[0] if segments else {}
    airline = _airline_from_segment(seg0)
    first_outbound = segments[0] if segments else {}
    last_outbound = segments[-1] if segments else {}
    inbound_segments = _segments_for_itinerary(inbound)
    first_inbound = inbound_segments[0] if inbound_segments else {}
    last_inbound = inbound_segments[-1] if inbound_segments else {}
    offer_id = offer.get('id', '') or ''
    return {
        'id': offer.get('id'),
        'price_eur': price_eur,
        'duration_minutes': duration_minutes,
        'outbound_duration_minutes': outbound_duration_minutes,
        'return_duration_minutes': return_duration_minutes,
        'trip_type': 'round_trip' if inbound else 'one_way',
        'airline': airline,
        'number': seg0.get('number', '') or offer_id[:6],
        'departure_time': _segment_time(first_outbound, 'departure'),
        'arrival_time': _segment_time(last_outbound, 'arrival'),
        'return_departure_time': _segment_time(first_inbound, 'departure'),
        'return_arrival_time': _segment_time(last_inbound, 'arrival'),
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
