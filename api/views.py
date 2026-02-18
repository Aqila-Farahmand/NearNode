from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
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
    AIVibeSearchService, CollaborativeService, DelayPredictionService,
    find_best_alternates_real,
)
from . import amadeus_client


@api_view(['GET'])
@permission_classes([AllowAny])
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
    permission_classes = [AllowAny]

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
    permission_classes = [AllowAny]

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


@api_view(['POST'])
@permission_classes([AllowAny])
def nearest_alternate_search(request):
    """
    Feature 1: Nearest Alternate Optimization
    Search for airports within radius and calculate total trip cost/time
    """
    origin_airport_code = request.data.get('origin_airport_code')
    final_destination_address = request.data.get('final_destination_address')
    date_str = request.data.get('date')
    radius_km = float(request.data.get('radius_km', 100))

    if not all([origin_airport_code, final_destination_address, date_str]):
        return Response(
            {'error': 'origin_airport_code, final_destination_address, and date required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)

    if amadeus_client.is_configured():
        results = find_best_alternates_real(
            origin_airport_code,
            final_destination_address,
            date,
            radius_km,
        )
    else:
        results = NearestAlternateService.find_best_alternates(
            origin_airport_code,
            final_destination_address,
            date,
            radius_km,
        )

    # Get user's currency preference if authenticated
    currency = 'EUR'
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            currency = profile.currency
        except (UserProfile.DoesNotExist, AttributeError):
            pass

    # Convert prices to user's currency (simplified - in production, use real exchange rates)
    exchange_rates = {
        'USD': 1.10, 'EUR': 1.0, 'GBP': 0.85, 'JPY': 160.0,
        'CAD': 1.50, 'AUD': 1.65, 'CHF': 0.95, 'CNY': 7.80
    }
    rate = exchange_rates.get(currency, 1.0)

    use_real_api = amadeus_client.is_configured()
    serialized_results = [
        _serialize_one_alternate(result, rate, currency, use_real_api)
        for result in results
    ]

    payload = {
        'results': serialized_results,
        'count': len(serialized_results),
        'currency': currency
    }
    if len(serialized_results) == 0:
        payload['hint'] = _nearest_alternate_empty_hint(
            origin_airport_code, final_destination_address, date
        )
    return Response(payload)


def _serialize_one_alternate(result, rate, currency, use_real_api):
    """Build one serialized result for nearest-alternate (DB or real API)."""
    if use_real_api and isinstance(result.get('flight'), dict):
        flight_data = result['flight']
        flight_id = result.get('flight_id')
        ground = result.get('ground_transport')
    else:
        flight_data = FlightSerializer(result['flight']).data
        flight_id = flight_data.get('id')
        ground = result.get('ground_transport')
    if isinstance(ground, dict):
        ground_data = ground
    elif ground:
        ground_data = GroundTransportSerializer(ground).data
    else:
        ground_data = None
    return {
        'flight': flight_data,
        'flight_id': flight_id,
        'ground_transport': ground_data,
        'airport': AirportSerializer(result['airport']).data,
        'distance_to_destination_km': result['distance_to_destination_km'],
        'total_trip_cost_eur': float(result['total_cost_eur']),
        'total_trip_cost_converted': float(result['total_cost_eur']) * rate,
        'currency': currency,
        'total_trip_time_minutes': result['total_time_minutes'],
        'flight_cost_eur': float(result['flight_cost']),
        'ground_cost_eur': float(result.get('ground_cost', 0)),
    }


def _nearest_alternate_empty_hint(origin_airport_code, final_destination_address, date):
    """Return a specific hint when nearest-alternate search returns no results."""
    origin_code = (origin_airport_code or '').strip().upper()
    dest_lat, dest_lon = NearestAlternateService._resolve_destination_coords(
        final_destination_address
    )
    if not Airport.objects.filter(iata_code=origin_code).exists():
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


@api_view(['POST'])
@permission_classes([AllowAny])
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
        origin = Airport.objects.get(iata_code=origin_code)
        destination = Airport.objects.get(iata_code=destination_code)
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


def _search_vibe_for_anonymous(parsed_query):
    """Helper function to search vibe for anonymous users"""
    matching_airports = AIVibeSearchService._find_matching_airports(
        parsed_query)
    options = []

    # Find origin airport if specified
    origin_airport = None
    if parsed_query.get('origin_city'):
        origin_airport = Airport.objects.filter(
            city__icontains=parsed_query['origin_city']).first()

    if not origin_airport:
        return options

    # Search flights for matching destinations
    max_price = parsed_query.get('max_price_eur', 99999) or 99999
    max_duration = (parsed_query.get('max_duration_hours', 24) or 24) * 60

    for dest_airport in matching_airports[:10]:
        flights = Flight.objects.filter(
            origin_airport=origin_airport,
            destination_airport=dest_airport,
            price_eur__lte=max_price,
            duration_minutes__lte=max_duration
        )[:3]

        for flight in flights:
            match_score = AIVibeSearchService._calculate_match_score(
                flight, parsed_query)
            options.append({
                'flight': FlightSerializer(flight).data,
                'total_trip_cost_eur': float(flight.price_eur),
                'total_trip_time_minutes': flight.duration_minutes,
                'match_score': match_score
            })

    # Sort by match score and return top 3
    options.sort(key=lambda x: x['match_score'], reverse=True)
    return options[:3]


@api_view(['POST'])
@permission_classes([AllowAny])
def vibe_search(request):
    """
    Feature 3: AI-Driven "Vibe" Search
    Natural language search for destinations
    """
    query_text = request.data.get('query')

    if not query_text:
        return Response({'error': 'query required'}, status=status.HTTP_400_BAD_REQUEST)

    # Parse query with AI
    parsed_query, confidence = AIVibeSearchService.parse_query_with_ai(
        query_text)
    parsed_query['original_query'] = query_text

    # Search by vibe - handle anonymous users
    if request.user.is_authenticated:
        search, options = AIVibeSearchService.search_by_vibe(
            parsed_query, request.user)
        search_data = TripSearchSerializer(search).data
        top_matches = [
            TripOptionSerializer(opt).data for opt in options
        ]
    else:
        options = _search_vibe_for_anonymous(parsed_query)
        search_data = None
        top_matches = options

    return Response({
        'search': search_data,
        'parsed_query': parsed_query,
        'ai_confidence': confidence,
        'top_matches': top_matches
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
@permission_classes([AllowAny])
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
@permission_classes([AllowAny])
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

    if budget is not None:
        profile.budget_preference_eur = budget
    if preferred_airlines is not None:
        profile.preferred_airlines = preferred_airlines

    profile.save()

    return Response(UserProfileSerializer(profile).data)
