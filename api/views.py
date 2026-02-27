import logging
import requests
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta

from core.models import (
    Airport, Flight, FlightConnection, GroundTransport,
    UserProfile, TripSearch, TripOption, CollaborativeVote,
    PerfectMatch, DelayPrediction
)
from .serializers import (
    AirportSerializer, FlightSerializer, FlightConnectionSerializer,
    GroundTransportSerializer, UserProfileSerializer, TripSearchSerializer,
    TripOptionSerializer, CollaborativeVoteSerializer, PerfectMatchSerializer,
    DelayPredictionSerializer
)
from .services import (
    NearestAlternateService, MultiModalConnectionService,
    AISearchService, CollaborativeService, DelayPredictionService,
    SmartNearbyAirportService,
)
from . import amadeus_client

logger = logging.getLogger(__name__)


def _attach_destination_weather(top_matches):
    """Attach destination_weather to each match when weather API is configured."""
    if not top_matches:
        return
    for match in top_matches:
        match['destination_weather'] = None
        try:
            flight = match.get('flight') or {}
            dest_airport = flight.get('destination_airport') or {}
            city = dest_airport.get('city') or dest_airport.get('name')
            if city:
                match['destination_weather'] = _fetch_weather_for_city(city)
        except Exception as e:
            logger.debug('Weather for match: %s', e)


def _ai_search_hint(parsed_query, has_matches, weather_configured, use_real_flights=False):
    """Build hint when no matches or weather pref set but API not configured."""
    hint = None
    if not has_matches:
        if not parsed_query.get('origin_city'):
            hint = 'Include an origin city (e.g. "from Milan", "from Paris") to see flight results.'
        else:
            logger.info(
                'AI search: no matches for origin_city=%s (parsed: %s)',
                parsed_query.get('origin_city'),
                parsed_query,
            )
            if use_real_flights:
                hint = (
                    'No flights found for this origin/date. Try another origin city or date. '
                    'Ensure AMADEUS_API_KEY and AMADEUS_API_SECRET are set; run load_world_airports if needed.'
                )
            else:
                hint = (
                    'No flights found for this origin. Add airports and flights to the database, '
                    'or set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env for real flight search. '
                    'Run python manage.py load_world_airports to load airports.'
                )
    if (parsed_query.get('weather_preference') or '').strip() and not weather_configured:
        hint = (hint or '') + ' Set WEATHER_API_KEY in .env for weather-based destination matching.'
    return hint


# OpenWeatherMap current weather (api.openweathermap.org/data/2.5/weather)
def _fetch_weather_for_city(city_name):
    """Fetch current weather for a city. Returns dict with temp_c, description, icon or None on error."""
    if not city_name or not str(city_name).strip():
        return None
    api_key = (getattr(settings, 'WEATHER_API_KEY', None) or '').strip()
    base_url = (getattr(settings, 'OPENWEATHER_BASE_URL', None) or '').strip().rstrip('/')
    if not api_key:
        return None
    if not base_url:
        return None
    try:
        resp = requests.get(
            base_url + '/weather',
            params={'q': str(city_name).strip(),
                    'appid': api_key, 'units': 'metric'},
            timeout=5,
        )
        if resp.status_code != 200:
            logger.debug('Weather API non-200 for %s: %s',
                         city_name, resp.status_code)
            return None
        data = resp.json()
        main = data.get('main') or {}
        weather_list = data.get('weather') or []
        desc = weather_list[0].get('description', '') if weather_list else ''
        icon = weather_list[0].get('icon', '') if weather_list else ''
        temp = main.get('temp')
        return {
            'temp_c': round(float(temp), 1) if temp is not None else None,
            'description': desc,
            'icon': icon,
        }
    except Exception as e:
        logger.debug('Weather API error for %s: %s', city_name, e)
        return None


def _exchange_rates_to_eur():
    # Approximate display rates; replace with live FX in production.
    return {
        'EUR': 1.0,
        'USD': 1.10,
        'GBP': 0.85,
        'JPY': 160.0,
        'CAD': 1.50,
        'AUD': 1.65,
        'CHF': 0.95,
        'CNY': 7.80,
        'INR': 90.0,
        'AED': 4.05,
        'BRL': 6.0,
        'MXN': 20.0,
        'SGD': 1.47,
        'HKD': 8.6,
        'SEK': 11.0,
        'NOK': 11.5,
        'DKK': 7.5,
        'NZD': 1.8,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nearest_airport(request):
    """
    GET ?lat=...&lon=... — returns the airport nearest to the given coordinates.
    Used by profile "Use current location" to set home airport.
    """
    lat = request.query_params.get('lat')
    lon = request.query_params.get('lon')
    if not lat or not lon:
        return Response(
            {'error': 'Query parameters lat and lon are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except ValueError:
        return Response({'error': 'lat and lon must be numbers'}, status=status.HTTP_400_BAD_REQUEST)
    airports = list(Airport.objects.all())
    if not airports:
        return Response({'error': 'No airports in database'}, status=status.HTTP_404_NOT_FOUND)
    nearest = min(airports, key=lambda a: a.distance_to(lat_f, lon_f))
    return Response({
        'airport': AirportSerializer(nearest).data,
        'iata_code': nearest.iata_code,
        'distance_km': round(nearest.distance_to(lat_f, lon_f), 2),
    })


class AirportViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for airports"""
    queryset = Airport.objects.all()
    serializer_class = AirportSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def nearby(self, request):
        """Find airports near a location"""
        lat = request.query_params.get('lat')
        lon = request.query_params.get('lon')
        radius = float(request.query_params.get('radius', 100))

        if not lat or not lon:
            return Response({'error': 'lat and lon required'}, status=status.HTTP_400_BAD_REQUEST)

        airports = NearestAlternateService.find_airports_in_radius(
            float(lat), float(lon), radius)
        results = [{
            'airport': AirportSerializer(item['airport']).data,
            'distance_km': item['distance_km']
        } for item in airports]

        return Response(results)


class FlightViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for flights"""
    queryset = Flight.objects.all()
    serializer_class = FlightSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Flight.objects.all()
        origin = self.request.query_params.get('origin')
        destination = self.request.query_params.get('destination')
        date = self.request.query_params.get('date')
        max_price = self.request.query_params.get('max_price')

        if origin:
            queryset = queryset.filter(origin_airport__iata_code=origin)
        if destination:
            queryset = queryset.filter(
                destination_airport__iata_code=destination)
        if date:
            queryset = queryset.filter(departure_time__date=date)
        if max_price:
            queryset = queryset.filter(price_eur__lte=max_price)

        return queryset


def _nearest_alternate_bad_request(message):
    return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)


def _nearest_alternate_request_params(data):
    origin_airport_code = data.get('origin_airport_code')
    final_destination_address = data.get('final_destination_address')
    radius_km = float(data.get('radius_km', 100))
    return {
        'origin_query': data.get('origin_query') or origin_airport_code,
        'destination_query': data.get('destination_query') or final_destination_address,
        'date_str': data.get('date'),
        'origin_radius_km': float(data.get('origin_radius_km', radius_km)),
        'destination_radius_km': float(data.get('destination_radius_km', radius_km)),
        'sort_by': (data.get('sort_by') or 'cost').strip().lower(),
        'sort_order': (data.get('sort_order') or 'asc').strip().lower(),
        'max_results': int(data.get('max_results', 30)),
        'trip_type': (data.get('trip_type') or 'one_way').strip().lower(),
        'return_date_str': (data.get('return_date') or '').strip(),
    }


def _validate_nearest_alternate_dates(params):
    if not all([params['origin_query'], params['destination_query'], params['date_str']]):
        return None, None, 'origin_query/destination_query/date are required (legacy: origin_airport_code/final_destination_address/date).'
    try:
        departure_date = datetime.strptime(params['date_str'], '%Y-%m-%d').date()
    except ValueError:
        return None, None, 'Invalid date format. Use YYYY-MM-DD'

    trip_type = params['trip_type']
    if trip_type not in ('one_way', 'round_trip'):
        return None, None, 'trip_type must be one_way or round_trip'
    if trip_type != 'round_trip':
        return departure_date, None, None

    return_date_str = params['return_date_str']
    if not return_date_str:
        return None, None, 'return_date is required for round trips'
    try:
        return_date = datetime.strptime(return_date_str, '%Y-%m-%d').date()
    except ValueError:
        return None, None, 'Invalid return_date format. Use YYYY-MM-DD'
    if return_date < departure_date:
        return None, None, 'return_date must be on or after departure date'
    return departure_date, return_date, None


def _nearest_alternate_currency_for_user(user):
    if not user.is_authenticated:
        return 'EUR'
    try:
        return user.profile.currency
    except (UserProfile.DoesNotExist, AttributeError):
        return 'EUR'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def nearest_alternate_search(request):
    """
    Feature 1: Nearest Alternate Optimization
    Search for airports within radius and calculate total trip cost/time
    """
    params = _nearest_alternate_request_params(request.data)
    departure_date, return_date, validation_error = _validate_nearest_alternate_dates(params)
    if validation_error:
        return _nearest_alternate_bad_request(validation_error)
    if not amadeus_client.is_configured():
        return _nearest_alternate_bad_request(
            'Real flight search requires AMADEUS_API_KEY and AMADEUS_API_SECRET.'
        )

    smart_search = SmartNearbyAirportService.search(
        origin_query=params['origin_query'],
        destination_query=params['destination_query'],
        search_date=departure_date,
        origin_radius_km=params['origin_radius_km'],
        destination_radius_km=params['destination_radius_km'],
        sort_by=params['sort_by'],
        sort_order=params['sort_order'],
        max_results=params['max_results'],
        trip_type=params['trip_type'],
        return_date=return_date,
        return_meta=True,
    )
    results = smart_search.get('results', [])
    search_meta = smart_search.get('meta', {})
    currency = _nearest_alternate_currency_for_user(request.user)
    rate = _exchange_rates_to_eur().get(currency, 1.0)
    use_real_api = amadeus_client.is_configured()
    serialized_results = [
        _serialize_one_alternate(result, rate, currency, use_real_api)
        for result in results
    ]

    payload = {
        'results': serialized_results,
        'count': len(serialized_results),
        'currency': currency,
        'sort_by': params['sort_by'],
        'sort_order': params['sort_order'],
        'trip_type': params['trip_type'],
        'return_date': params['return_date_str'] if params['trip_type'] == 'round_trip' else None,
        'search_meta': search_meta,
    }
    if not serialized_results:
        payload['hint'] = _smart_search_empty_hint(
            params['origin_query'],
            params['destination_query'],
            params['origin_radius_km'],
            search_meta,
        )
    return Response(payload)


def _serialize_one_alternate(result, rate, currency, use_real_api):
    """Build one serialized result for nearest-alternate (DB or real API)."""
    flight_data, flight_id = _serialize_alternate_flight(result, use_real_api)
    ground_data = _serialize_alternate_ground(result.get('ground_transport'))
    origin_airport_data = _serialize_origin_airport_data(result, flight_data)
    destination_airport_data = _serialize_destination_airport_data(result, flight_data)
    total_cost = _as_float(result.get('total_cost_eur', 0))
    ground_cost = _as_float(result.get('ground_cost', 0))
    flight_duration = _alternate_duration_minutes(
        result, 'flight_time_minutes', flight_data, 'duration_minutes'
    )
    ground_duration = _alternate_duration_minutes(
        result, 'ground_time_minutes', ground_data, 'duration_minutes'
    )
    outbound_flight_duration = _as_float(
        result.get('outbound_flight_time_minutes'),
        _as_float((flight_data or {}).get('outbound_duration_minutes', 0) if isinstance(flight_data, dict) else 0),
    )
    return_flight_duration = _as_float(
        result.get('return_flight_time_minutes'),
        _as_float((flight_data or {}).get('return_duration_minutes', 0) if isinstance(flight_data, dict) else 0),
    )
    return {
        'flight': flight_data,
        'flight_leg': flight_data,
        'flight_id': flight_id,
        'ground_transport': ground_data,
        'ground_leg': ground_data,
        'airport': AirportSerializer(result['airport']).data,
        'origin_airport': origin_airport_data,
        'destination_airport': destination_airport_data,
        'origin_distance_km': float(result.get('origin_distance_km', 0) or 0),
        'distance_to_destination_km': float(result.get('distance_to_destination_km', 0) or 0),
        'total_trip_cost_eur': total_cost,
        'total_trip_cost_converted': total_cost * rate,
        'currency': currency,
        'trip_type': result.get('trip_type') or (flight_data.get('trip_type') if isinstance(flight_data, dict) else 'one_way') or 'one_way',
        'total_trip_time_minutes': result['total_time_minutes'],
        'flight_cost_eur': float(result['flight_cost']),
        'ground_cost_eur': ground_cost,
        'flight_duration_minutes': flight_duration,
        'outbound_flight_duration_minutes': int(outbound_flight_duration or 0),
        'return_flight_duration_minutes': int(return_flight_duration or 0),
        'ground_duration_minutes': ground_duration,
    }


def _serialize_alternate_flight(result, use_real_api):
    if use_real_api and isinstance(result.get('flight'), dict):
        return result['flight'], result.get('flight_id')
    flight_data = FlightSerializer(result['flight']).data
    return flight_data, flight_data.get('id')


def _serialize_alternate_ground(ground):
    if isinstance(ground, dict):
        return ground
    if ground:
        return GroundTransportSerializer(ground).data
    return None


def _serialize_origin_airport_data(result, flight_data):
    origin_airport_obj = result.get('origin_airport')
    if origin_airport_obj:
        return AirportSerializer(origin_airport_obj).data
    return _flight_field_if_dict(flight_data, 'origin_airport')


def _serialize_destination_airport_data(result, flight_data):
    destination_airport_obj = result.get('destination_airport') or result.get('airport')
    if destination_airport_obj:
        return AirportSerializer(destination_airport_obj).data
    return _flight_field_if_dict(flight_data, 'destination_airport')


def _flight_field_if_dict(flight_data, key):
    if isinstance(flight_data, dict):
        return flight_data.get(key)
    return None


def _as_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _alternate_duration_minutes(result, result_key, leg_data, leg_duration_key):
    if result.get(result_key) is not None:
        return int(result.get(result_key) or 0)
    if isinstance(leg_data, dict):
        return int(leg_data.get(leg_duration_key, 0) or 0)
    return 0


def _nearest_alternate_empty_hint(origin_airport_code, final_destination_address, date):
    """Return a specific hint when nearest-alternate search returns no results."""
    origin_code = (origin_airport_code or '').strip().upper()
    dest_lat, dest_lon = NearestAlternateService._resolve_destination_coords(
        final_destination_address
    )
    is_iata = len(origin_code) == 3 and origin_code.isalpha()
    if is_iata and not Airport.objects.filter(iata_code=origin_code).exists():
        return (
            'Origin airport "{}" not in database. Run: python manage.py load_world_airports.'.format(
                origin_code or ''
            )
        )
    if not dest_lat or not dest_lon:
        return (
            'Could not find destination. Use a city name (e.g. London), '
            'full address, or 3-letter airport code (e.g. LHR).'
        )
    # When Amadeus is configured, no results means API returned nothing for this route/date
    from . import amadeus_client
    if amadeus_client.is_configured():
        return (
            'No flights from {} to airports near your destination on this date. '
            'Try a different date or larger radius.'.format(origin_code)
        )
    return (
        'Set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env for real flight search. '
        'See Documents/REAL_DATA_SETUP.md.'
    )


def _smart_search_empty_hint(origin_query, destination_query, origin_radius_km, search_meta):
    origins = search_meta.get('origin_airports_considered') or []
    destinations = search_meta.get('destination_airports_considered') or []
    no_ground = search_meta.get('origin_airports_without_ground') or []
    origin_preview = ', '.join(origins[:8]) if origins else 'none'
    destination_preview = ', '.join(destinations[:8]) if destinations else 'none'
    hint = (
        'No flights found for destination "{}" from your origin "{}" and nearby airports within {} km. '
        'Checked origin airports: {}. Checked destination airports: {}. '
        'Try a different date, larger radius, or another destination city/airport.'
    ).format(
        destination_query,
        origin_query,
        int(origin_radius_km),
        origin_preview,
        destination_preview,
    )
    if no_ground:
        hint += ' Some nearby origins were skipped due to unavailable ground routes: {}.'.format(
            ', '.join(no_ground[:8])
        )
    return hint


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def multi_modal_search(request):
    """
    Feature 2: Multi-Modal Connection Logic
    Find connections with train links and layover quality scores
    """
    origin_code = request.data.get('origin_airport_code')
    destination_code = request.data.get('destination_airport_code')
    date_str = request.data.get('date')

    if not all([origin_code, destination_code, date_str]):
        return Response(
            {'error': 'origin_airport_code, destination_airport_code, and date required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        origin = Airport.objects.get(iata_code__iexact=origin_code.strip())
        destination = Airport.objects.get(
            iata_code__iexact=destination_code.strip())
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except Airport.DoesNotExist:
        return Response({'error': 'Airport not found'}, status=status.HTTP_404_NOT_FOUND)
    except ValueError:
        return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

    connections = MultiModalConnectionService.create_multi_modal_connection(
        origin, destination, date)

    serialized_connections = []
    for conn in connections:
        serialized = {
            'type': conn['type'],
            'total_cost_eur': float(conn['total_cost']),
            'total_time_minutes': conn['total_time'],
            'connection_quality_score': conn['connection_quality'],
        }

        if conn['type'] == 'direct':
            serialized['flight'] = FlightSerializer(conn['flight']).data
        elif conn['type'] == 'train_link':
            serialized['flight1'] = FlightSerializer(conn['flight1']).data
            serialized['flight2'] = FlightSerializer(conn['flight2']).data
            serialized['train'] = GroundTransportSerializer(conn['train']).data
            serialized['intermediate_airport'] = AirportSerializer(
                conn['intermediate_airport']).data
            serialized['layover_minutes'] = conn['layover_minutes']
            if conn.get('intermediate_airport_b'):
                serialized['intermediate_airport_b'] = AirportSerializer(
                    conn['intermediate_airport_b']).data
        else:
            serialized['flight1'] = FlightSerializer(conn['flight1']).data
            serialized['flight2'] = FlightSerializer(conn['flight2']).data
            serialized['intermediate_airport'] = AirportSerializer(
                conn['intermediate_airport']).data
            serialized['layover_minutes'] = conn['layover_minutes']

        serialized_connections.append(serialized)

    return Response({
        'connections': serialized_connections,
        'count': len(serialized_connections)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ai_search(request):
    """
    Feature 3: AI Search — natural language search for trips.
    User writes free text; AI parses it and returns matching options.
    """
    query_text = request.data.get('query')

    if not query_text:
        return Response({'error': 'query required'}, status=status.HTTP_400_BAD_REQUEST)

    # Use actual DB: pass available origin/destination cities so the model can normalize the query
    available_origins = AISearchService.get_available_origin_cities()
    available_destinations = AISearchService.get_available_destination_cities()
    parsed_query, confidence = AISearchService.parse_query_with_ai(
        query_text,
        available_origin_cities=available_origins,
        available_destination_cities=available_destinations,
    )
    parsed_query['original_query'] = query_text

    # Run AI search (user is authenticated); may return DB options or real-API match dicts
    try:
        search, options = AISearchService.search_by_query(
            parsed_query, request.user)
    except Exception as e:
        logger.exception('AI search failed: %s', e)
        return Response(
            {'error': 'Search failed. Check server logs.', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    search_data = TripSearchSerializer(search).data
    # options are either TripOption instances (DB) or list of match dicts (Amadeus API)
    if options and isinstance(options[0], dict):
        top_matches = options
    else:
        top_matches = [TripOptionSerializer(opt).data for opt in options]
    weather_configured = bool((getattr(settings, 'WEATHER_API_KEY', None) or '').strip())
    if weather_configured:
        _attach_destination_weather(top_matches)
    use_real_flights = bool(options and isinstance(options[0], dict))
    hint = _ai_search_hint(parsed_query, bool(top_matches), weather_configured, use_real_flights)
    llm_backend = (getattr(settings, 'AI_SEARCH_LLM_BACKEND', None) or '').strip().lower() or None
    return Response({
        'search': search_data,
        'parsed_query': parsed_query,
        'ai_confidence': confidence,
        'llm_backend': llm_backend,
        'weather_configured': weather_configured,
        'top_matches': top_matches,
        'hint': hint,
        'use_real_flights': use_real_flights,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_partner_sync_code(request):
    """Generate sync code for partner linking"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if not profile.partner_sync_code:
        profile.partner_sync_code = CollaborativeService.generate_sync_code()
        profile.save()

    return Response({
        'sync_code': profile.partner_sync_code,
        'message': 'Share this code with your partner to link accounts'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def link_partner(request):
    """Link partner account via sync code"""
    sync_code = request.data.get('sync_code')

    if not sync_code:
        return Response({'error': 'sync_code required'}, status=status.HTTP_400_BAD_REQUEST)

    success = CollaborativeService.link_partners(request.user, sync_code)

    if success:
        profile = UserProfile.objects.get(user=request.user)
        return Response({
            'success': True,
            'partner': UserProfileSerializer(profile).data['partner'],
            'message': 'Partner linked successfully'
        })
    else:
        return Response({'error': 'Invalid sync code'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def vote_on_trip(request):
    """
    Feature 4: Collaborative Voting
    User votes on a trip option
    """
    trip_option_id = request.data.get('trip_option_id')
    # 'like', 'dislike', 'super_like'
    vote_type = request.data.get('vote_type')

    if not all([trip_option_id, vote_type]):
        return Response({'error': 'trip_option_id and vote_type required'}, status=status.HTTP_400_BAD_REQUEST)

    if vote_type not in ['like', 'dislike', 'super_like']:
        return Response({'error': 'Invalid vote_type'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        trip_option = TripOption.objects.get(id=trip_option_id)
    except TripOption.DoesNotExist:
        return Response({'error': 'Trip option not found'}, status=status.HTTP_404_NOT_FOUND)

    vote = CollaborativeService.vote_on_option(
        request.user, trip_option, vote_type)

    # Check for perfect matches if user has a partner
    try:
        profile = UserProfile.objects.get(user=request.user)
        if profile.partner:
            matches = CollaborativeService.find_perfect_matches(
                request.user, profile.partner)
            return Response({
                'vote': CollaborativeVoteSerializer(vote).data,
                'perfect_matches': PerfectMatchSerializer(matches[:5], many=True).data
            })
    except UserProfile.DoesNotExist:
        pass

    return Response(CollaborativeVoteSerializer(vote).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_perfect_matches(request):
    """Get perfect matches for user and their partner"""
    try:
        profile = UserProfile.objects.get(user=request.user)
        if not profile.partner:
            return Response({'error': 'No partner linked'}, status=status.HTTP_400_BAD_REQUEST)

        matches = CollaborativeService.find_perfect_matches(
            request.user, profile.partner)
        return Response(PerfectMatchSerializer(matches, many=True).data)
    except UserProfile.DoesNotExist:
        return Response({'error': 'Profile not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def predict_delay(request):
    """
    Feature 5: Delay Prediction
    Predict delay probability for a flight
    """
    flight_id = request.query_params.get('flight_id')

    if not flight_id:
        return Response({'error': 'flight_id required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        flight = Flight.objects.get(id=flight_id)
    except Flight.DoesNotExist:
        return Response({'error': 'Flight not found'}, status=status.HTTP_404_NOT_FOUND)

    prediction = DelayPredictionService.predict_delay(flight)

    return Response({
        'flight': FlightSerializer(flight).data,
        'delay_prediction': prediction
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_self_transfer_insurance(request):
    """
    Feature 5: Self-Transfer Insurance Check
    Check if a self-transfer connection is safe
    """
    connection_id = request.data.get('connection_id')

    if not connection_id:
        return Response({'error': 'connection_id required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        connection = FlightConnection.objects.get(id=connection_id)
    except FlightConnection.DoesNotExist:
        return Response({'error': 'Connection not found'}, status=status.HTTP_404_NOT_FOUND)

    insurance_check = DelayPredictionService.check_self_transfer_insurance(
        connection)

    return Response({
        'connection': FlightConnectionSerializer(connection).data,
        'insurance_check': insurance_check
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_profile(request):
    """Get or create user profile"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return Response(UserProfileSerializer(profile).data)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_user_profile(request):
    """Update user profile"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    budget = request.data.get('budget_preference_eur')
    preferred_airlines = request.data.get('preferred_airlines')
    currency = request.data.get('currency')
    preferred_language = request.data.get('preferred_language')

    if budget is not None:
        profile.budget_preference_eur = budget
    if preferred_airlines is not None:
        profile.preferred_airlines = preferred_airlines
    if currency is not None:
        profile.currency = currency
    if preferred_language is not None:
        profile.preferred_language = preferred_language

    profile.save()

    return Response(UserProfileSerializer(profile).data)
