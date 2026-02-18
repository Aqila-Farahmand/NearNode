"""
Ground transport (train/public transport) API client using Navitia.
When NAVITIA_TOKEN is set, journey planning from airport coords to destination coords is used.
"""
import requests

try:
    from decouple import config
except Exception:
    config = None

BASE_URL = 'https://api.navitia.io/v1'


def _get_token():
    if config:
        return (config('NAVITIA_TOKEN', default='') or '').strip()
    return ''


def _get_region():
    if config:
        return (config('NAVITIA_REGION', default='fr-idf') or 'fr-idf').strip()
    return 'fr-idf'


def is_configured():
    return bool(_get_token())


def get_journeys(from_lat, from_lon, to_lat, to_lon):
    """
    Get public transport (train/bus/etc.) options from (from_lat, from_lon) to (to_lat, to_lon).
    Returns list of dicts: {duration_minutes, cost_eur, name, transport_type}.
    Navitia format for coords is longitude;latitude.
    """
    token = _get_token()
    if not token:
        return []
    region = _get_region()
    # Navitia: from=lon;lat&to=lon;lat
    from_param = '{};{}'.format(from_lon, from_lat)
    to_param = '{};{}'.format(to_lon, to_lat)
    url = '{}/coverage/{}/journeys'.format(BASE_URL, region)
    params = {'from': from_param, 'to': to_param}
    # Basic auth: username=token, password=empty
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
    for j in journeys[:5]:
        duration_seconds = _journey_duration_seconds(j)
        if duration_seconds is None:
            continue
        duration_minutes = max(0, int(round(duration_seconds / 60.0)))
        fare = _journey_fare(j)
        name = _journey_summary(j)
        result.append({
            'duration_minutes': duration_minutes,
            'cost_eur': fare,
            'name': name,
            'transport_type': 'train',
        })
    return result


def _journey_duration_seconds(journey):
    """Extract total duration in seconds from a journey object."""
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
    """Extract fare in EUR if available; otherwise return 0."""
    fare = journey.get('fare') or {}
    if isinstance(fare, dict):
        total = fare.get('total', {}).get('value') if isinstance(fare.get('total'), dict) else None
        if total is not None:
            try:
                return float(total) / 100.0
            except (TypeError, ValueError):
                pass
    return 0.0


def _journey_summary(journey):
    """Build a short label for the journey (e.g. 'Train + walk')."""
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
