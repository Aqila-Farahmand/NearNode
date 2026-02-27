"""
Ground transport client with provider support.

Providers:
- google_routes (preferred)
- navitia (legacy fallback)
"""
import requests
from django.conf import settings

try:
    from decouple import config
except Exception:
    config = None


def _get_setting(name, default=''):
    env_value = ''
    if config:
        try:
            env_value = config(name, default='') or ''
        except Exception:
            env_value = ''
    if str(env_value).strip():
        return str(env_value).strip()
    return str(getattr(settings, name, default) or default).strip()


def get_provider():
    """Return configured ground provider name."""
    provider = _get_setting('GROUND_PROVIDER', 'navitia').lower()
    return provider or 'navitia'


def _get_navitia_token():
    return _get_setting('NAVITIA_TOKEN', '')


def _get_navitia_region():
    return _get_setting('NAVITIA_REGION', 'fr-idf') or 'fr-idf'


def _get_google_maps_api_key():
    return _get_setting('GOOGLE_MAPS_API_KEY', '')


def _get_navitia_base_url():
    return _get_setting('NAVITIA_BASE_URL', '')


def _get_google_routes_url():
    return _get_setting('GOOGLE_ROUTES_URL', '')


def is_google_configured():
    return bool(_get_google_maps_api_key())


def is_navitia_configured():
    return bool(_get_navitia_token())


def is_configured():
    provider = get_provider()
    if provider == 'google_routes':
        return is_google_configured()
    if provider == 'navitia':
        return is_navitia_configured()
    return is_google_configured() or is_navitia_configured()


def get_ground_options(from_lat, from_lon, to_lat, to_lon):
    """Return normalized ground options from active provider."""
    provider = get_provider()
    options = []
    if provider == 'google_routes':
        options = _get_google_routes(from_lat, from_lon, to_lat, to_lon)
        if options:
            return options
        return _get_navitia_journeys(from_lat, from_lon, to_lat, to_lon)
    if provider == 'navitia':
        options = _get_navitia_journeys(from_lat, from_lon, to_lat, to_lon)
        if options:
            return options
        return _get_google_routes(from_lat, from_lon, to_lat, to_lon)
    options = _get_google_routes(from_lat, from_lon, to_lat, to_lon)
    if options:
        return options
    return _get_navitia_journeys(from_lat, from_lon, to_lat, to_lon)


def get_journeys(from_lat, from_lon, to_lat, to_lon):
    """
    Backward-compatible alias used by existing service code.
    """
    return get_ground_options(from_lat, from_lon, to_lat, to_lon)


def _parse_google_duration_minutes(duration_str):
    # Google returns durations like "5432s".
    if not duration_str:
        return None
    s = str(duration_str).strip().lower()
    if not s.endswith('s'):
        return None
    try:
        seconds = int(float(s[:-1]))
    except (TypeError, ValueError):
        return None
    return max(0, int(round(seconds / 60.0)))


def _extract_google_fare_eur(route):
    # API response shape can vary; try common locations.
    candidates = [
        route.get('travelAdvisory', {}).get('transitFare', {}),
        route.get('fare', {}),
    ]
    for fare in candidates:
        value = _fare_candidate_to_eur(fare)
        if value is not None:
            return value
    return None


def _fare_candidate_to_eur(fare):
    if not isinstance(fare, dict):
        return None
    currency = _fare_currency_code(fare)
    if not _is_eur_or_unspecified(currency):
        return None
    amount_value = _fare_amount_value(fare)
    if amount_value is not None:
        return amount_value
    return _fare_units_nanos_value(fare)


def _fare_currency_code(fare):
    return (fare.get('currencyCode') or fare.get('currency') or '').upper()


def _is_eur_or_unspecified(currency):
    return currency in ('', 'EUR')


def _fare_amount_value(fare):
    amount = fare.get('amount')
    if amount is None:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


def _fare_units_nanos_value(fare):
    units = fare.get('units')
    if units is None:
        return None
    nanos = fare.get('nanos', 0)
    try:
        return float(units) + (float(nanos) / 1_000_000_000.0)
    except (TypeError, ValueError):
        return None


def _estimate_ground_cost_eur(distance_km, mode):
    # Conservative heuristic when provider does not return fares.
    if distance_km is None:
        return None
    if mode == 'TRANSIT':
        return round(max(2.5, distance_km * 0.11), 2)
    return round(max(4.0, distance_km * 0.20), 2)


def _route_summary(route):
    legs = route.get('legs') or []
    if not legs:
        return 'Ground transport'
    leg0 = legs[0] or {}
    return leg0.get('summary') or route.get('description') or 'Ground transport'


def _google_routes_headers(api_key):
    return {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': (
            'routes.duration,'
            'routes.distanceMeters,'
            'routes.legs.summary,'
            'routes.travelAdvisory.transitFare,'
            'routes.fare'
        ),
    }


def _google_base_payload(from_lat, from_lon, to_lat, to_lon):
    return {
        'origin': {'location': {'latLng': {'latitude': float(from_lat), 'longitude': float(from_lon)}}},
        'destination': {'location': {'latLng': {'latitude': float(to_lat), 'longitude': float(to_lon)}}},
        'languageCode': 'en',
        'units': 'METRIC',
    }


def _google_request_payloads(base_payload):
    return [
        dict(base_payload, travelMode='TRANSIT'),
        dict(base_payload, travelMode='DRIVE'),
    ]


def _fetch_google_routes_for_payload(headers, payload):
    url = _get_google_routes_url()
    if not url:
        return []
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException:
        return []
    if not resp.ok:
        return []
    data = resp.json() if resp.content else {}
    return data.get('routes') or []


def _google_distance_km(route):
    distance_m = route.get('distanceMeters')
    if distance_m is None:
        return None
    try:
        return round(float(distance_m) / 1000.0, 2)
    except (TypeError, ValueError):
        return None


def _google_option_from_route(route, mode):
    duration_minutes = _parse_google_duration_minutes(route.get('duration'))
    if duration_minutes is None:
        return None
    distance_km = _google_distance_km(route)
    fare_eur = _extract_google_fare_eur(route)
    estimate = _estimate_ground_cost_eur(distance_km, mode)
    return {
        'duration_minutes': duration_minutes,
        'cost_eur': fare_eur,
        'estimated_cost_eur': estimate,
        'distance_km': distance_km,
        'mode': mode.lower(),
        'name': _route_summary(route),
        'transport_type': 'train' if mode == 'TRANSIT' else 'car_rental',
        'provider': 'google_routes',
    }


def _google_options_for_mode(headers, payload):
    mode = payload.get('travelMode', 'TRANSIT')
    options = []
    for route in _fetch_google_routes_for_payload(headers, payload)[:3]:
        option = _google_option_from_route(route, mode)
        if option is not None:
            options.append(option)
    return options


def _get_google_routes(from_lat, from_lon, to_lat, to_lon):
    api_key = _get_google_maps_api_key()
    if not api_key:
        return []
    headers = _google_routes_headers(api_key)
    base_payload = _google_base_payload(from_lat, from_lon, to_lat, to_lon)
    options = []
    for payload in _google_request_payloads(base_payload):
        options.extend(_google_options_for_mode(headers, payload))
    return sorted(options, key=lambda x: (x.get('duration_minutes', 10**9), x.get('distance_km') or 10**9))


def _get_navitia_journeys(from_lat, from_lon, to_lat, to_lon):
    token = _get_navitia_token()
    if not token:
        return []
    base_url = _get_navitia_base_url()
    if not base_url:
        return []
    region = _get_navitia_region()
    from_param = '{};{}'.format(from_lon, from_lat)
    to_param = '{};{}'.format(to_lon, to_lat)
    url = '{}/coverage/{}/journeys'.format(base_url.rstrip('/'), region)
    params = {'from': from_param, 'to': to_param}
    auth = (token, '')
    try:
        resp = requests.get(url, params=params, auth=auth, timeout=15)
    except requests.RequestException:
        return []
    if not resp.ok:
        return []
    data = resp.json()
    journeys = data.get('journeys') or []
    result = []
    for journey in journeys[:5]:
        duration_seconds = _journey_duration_seconds(journey)
        if duration_seconds is None:
            continue
        duration_minutes = max(0, int(round(duration_seconds / 60.0)))
        fare = _journey_fare(journey)
        result.append({
            'duration_minutes': duration_minutes,
            'cost_eur': fare,
            'estimated_cost_eur': None,
            'distance_km': None,
            'mode': 'transit',
            'name': _journey_summary(journey),
            'transport_type': 'train',
            'provider': 'navitia',
        })
    return result


def _journey_duration_seconds(journey):
    if journey.get('durations'):
        total = journey.get('durations', {}).get('total')
        if total is not None:
            return int(total)
    sections = journey.get('sections') or []
    if not sections:
        return None
    total = 0
    for sec in sections:
        duration = sec.get('duration')
        if duration is not None:
            total += int(duration)
    return total if total > 0 else None


def _journey_fare(journey):
    fare = journey.get('fare') or {}
    if isinstance(fare, dict):
        total = fare.get('total', {}).get('value') if isinstance(fare.get('total'), dict) else None
        if total is not None:
            try:
                return float(total) / 100.0
            except (TypeError, ValueError):
                pass
    return None


def _journey_summary(journey):
    sections = journey.get('sections') or []
    modes = []
    for sec in sections:
        mode = (sec.get('type') or '').lower()
        if mode == 'public_transport':
            pt = sec.get('mode') or sec.get('pt_display_information') or {}
            name = pt.get('name') if isinstance(pt, dict) else None
            modes.append(name or 'Train')
        elif mode == 'street_network' and sec.get('mode') == 'walking':
            modes.append('Walk')
    return ' + '.join(modes) if modes else 'Public transport'
