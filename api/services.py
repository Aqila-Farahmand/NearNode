"""
Service layer for business logic
"""
from django.db.models import Q, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from core.models import Airport, Flight, FlightConnection, GroundTransport, TripOption, TripSearch, CollaborativeVote, PerfectMatch, DelayPrediction, UserProfile
import openai
from django.conf import settings
import json
from datetime import datetime, timedelta


class NearestAlternateService:
    """Service for finding nearest alternate airports within radius"""

    @staticmethod
    def geocode_address(address):
        """Convert street address to lat/lon"""
        geolocator = Nominatim(user_agent="nearnode")
        try:
            location = geolocator.geocode(address)
            if location:
                return location.latitude, location.longitude
        except Exception as e:
            print(f"Geocoding error: {e}")
        return None, None

    @staticmethod
    def find_airports_in_radius(dest_lat, dest_lon, radius_km=100):
        """Find all airports within radius"""
        airports = Airport.objects.all()
        nearby_airports = []

        for airport in airports:
            distance = geodesic((dest_lat, dest_lon), (float(
                airport.latitude), float(airport.longitude))).kilometers
            if distance <= radius_km:
                nearby_airports.append({
                    'airport': airport,
                    'distance_km': distance
                })

        return sorted(nearby_airports, key=lambda x: x['distance_km'])

    @staticmethod
    def calculate_total_trip_cost(flight, ground_transport=None):
        """Calculate total cost including flight and ground transport"""
        total = flight.price_eur
        if ground_transport:
            total += ground_transport.cost_eur
        return total

    @staticmethod
    def calculate_total_trip_time(flight, ground_transport=None):
        """Calculate total time including flight and ground transport"""
        total = flight.duration_minutes
        if ground_transport:
            total += ground_transport.duration_minutes
        return total

    @staticmethod
    def _resolve_destination_coords(final_destination_address):
        """Resolve destination to (lat, lon). Supports address or 3-letter airport code."""
        addr = (final_destination_address or '').strip()
        # If it looks like an airport code (3 letters), try airport first
        if len(addr) == 3 and addr.isalpha():
            try:
                airport = Airport.objects.get(iata_code=addr.upper())
                return float(airport.latitude), float(airport.longitude)
            except Airport.DoesNotExist:
                pass
        dest_lat, dest_lon = NearestAlternateService.geocode_address(addr)
        return dest_lat, dest_lon

    @staticmethod
    def find_best_alternates(origin_airport_code, final_destination_address, date, radius_km=100):
        """Find best alternate airports with total trip cost and time"""
        origin_code = (origin_airport_code or '').strip().upper()
        dest_lat, dest_lon = NearestAlternateService._resolve_destination_coords(
            final_destination_address
        )
        if not dest_lat or not dest_lon:
            return []

        # Find airports in radius
        nearby_airports = NearestAlternateService.find_airports_in_radius(
            dest_lat, dest_lon, radius_km)

        # Get origin airport
        try:
            origin_airport = Airport.objects.get(iata_code=origin_code)
        except Airport.DoesNotExist:
            return []

        results = []
        for item in nearby_airports:
            airport = item['airport']
            distance = item['distance_km']

            flights = Flight.objects.filter(
                origin_airport=origin_airport,
                destination_airport=airport,
                departure_time__date=date
            )

            # Prefer transport to exact address, then any transport from this airport
            ground_transports = list(
                GroundTransport.objects.filter(
                    from_airport=airport,
                    to_address=final_destination_address.strip()
                )
            )
            if not ground_transports:
                ground_transports = list(
                    GroundTransport.objects.filter(from_airport=airport)[:1]
                )
            transport = ground_transports[0] if ground_transports else None

            for flight in flights:
                total_cost = NearestAlternateService.calculate_total_trip_cost(
                    flight, transport)
                total_time = NearestAlternateService.calculate_total_trip_time(
                    flight, transport)
                results.append({
                    'flight': flight,
                    'ground_transport': transport,
                    'airport': airport,
                    'distance_to_destination_km': distance,
                    'total_cost_eur': total_cost,
                    'total_time_minutes': total_time,
                    'flight_cost': flight.price_eur,
                    'ground_cost': transport.cost_eur if transport else 0,
                })

        results.sort(key=lambda x: (
            x['total_cost_eur'], x['total_time_minutes']))
        return results


def _real_alternates_for_airport(origin_code, origin_airport, airport, distance, date_str,
                                 final_destination_address):
    """Get Amadeus offers for origin->airport and return list of result dicts."""
    from api.amadeus_client import search_flight_offers
    offers = search_flight_offers(origin_code, airport.iata_code, date_str)
    ground_transports = list(
        GroundTransport.objects.filter(
            from_airport=airport,
            to_address=(final_destination_address or '').strip()
        )
    )
    if not ground_transports:
        ground_transports = list(GroundTransport.objects.filter(from_airport=airport)[:1])
    transport = ground_transports[0] if ground_transports else None
    ground_cost = float(transport.cost_eur) if transport else 0
    results = []
    for offer in offers:
        flight_cost = offer.get('price_eur', 0)
        duration = offer.get('duration_minutes', 0)
        total_time = duration + (transport.duration_minutes if transport else 0)
        flight_dict = {
            'id': offer.get('id'),
            'flight_number': offer.get('number', ''),
            'airline': offer.get('airline', ''),
            'price_eur': flight_cost,
            'duration_minutes': duration,
            'origin_airport': {'iata_code': origin_code, 'name': getattr(origin_airport, 'name', origin_code)},
            'destination_airport': {'iata_code': airport.iata_code, 'name': airport.name},
        }
        results.append({
            'flight': flight_dict,
            'flight_id': offer.get('id'),
            'ground_transport': transport,
            'airport': airport,
            'distance_to_destination_km': distance,
            'total_cost_eur': flight_cost + ground_cost,
            'total_time_minutes': total_time,
            'flight_cost': flight_cost,
            'ground_cost': ground_cost,
        })
    return results


def find_best_alternates_real(origin_airport_code, final_destination_address, date, radius_km=100):
    """
    Same as NearestAlternateService.find_best_alternates but uses Amadeus API for live flight offers.
    Returns list of dicts with 'flight' as a serializable dict (not a model), plus airport (model),
    ground_transport (model or None), and cost/time fields.
    """
    origin_code = (origin_airport_code or '').strip().upper()
    dest_lat, dest_lon = NearestAlternateService._resolve_destination_coords(final_destination_address)
    if not dest_lat or not dest_lon:
        return []
    nearby_airports = NearestAlternateService.find_airports_in_radius(dest_lat, dest_lon, radius_km)
    try:
        origin_airport = Airport.objects.get(iata_code=origin_code)
    except Airport.DoesNotExist:
        return []
    date_str = date.strftime('%Y-%m-%d')
    results = []
    for item in nearby_airports:
        results.extend(_real_alternates_for_airport(
            origin_code, origin_airport, item['airport'], item['distance_km'],
            date_str, final_destination_address
        ))
    results.sort(key=lambda x: (x['total_cost_eur'], x['total_time_minutes']))
    return results


class MultiModalConnectionService:
    """Service for multi-modal connections with train links"""

    @staticmethod
    def calculate_layover_quality_score(airport, layover_minutes):
        """Calculate layover quality based on airport amenities and time"""
        score = 0.0

        # Base score from airport
        score += float(airport.layover_quality_score)

        # Time-based adjustments
        if 60 <= layover_minutes <= 180:  # Good layover window
            score += 2.0
        elif layover_minutes < 45:  # Too short
            score -= 3.0
        elif layover_minutes > 360:  # Too long
            score -= 1.0

        # Amenity bonuses
        if airport.has_lounge:
            score += 1.5
        if airport.has_sleeping_pods:
            score += 1.0
        if airport.city_access_time > 0 and layover_minutes > 180:
            score += 1.0  # Can visit city

        return min(10.0, max(0.0, score))

    @staticmethod
    def find_train_connections(flight1, flight2, max_layover_hours=6):
        """Find train connections between two flights if layover is long"""
        if not flight2:
            return None

        # Check if layover is long enough for train
        layover = (flight2.departure_time -
                   flight1.arrival_time).total_seconds() / 60

        if layover < 60 or layover > max_layover_hours * 60:
            return None

        # Find ground transport (train) between airports
        ground_transports = GroundTransport.objects.filter(
            from_airport=flight1.destination_airport,
            to_airport=flight2.origin_airport,
            transport_type='train'
        )

        for transport in ground_transports:
            # Check if train fits in layover window
            if transport.duration_minutes + 60 <= layover:  # 60 min buffer
                return transport

        return None

    @staticmethod
    def create_multi_modal_connection(origin, destination, date):
        """Create connections with train links when beneficial"""
        connections = []

        # Direct flights
        direct_flights = Flight.objects.filter(
            origin_airport=origin,
            destination_airport=destination,
            departure_time__date=date
        )

        for flight in direct_flights:
            connections.append({
                'type': 'direct',
                'flight': flight,
                'total_cost': flight.price_eur,
                'total_time': flight.duration_minutes,
                'connection_quality': 10.0
            })

        # Multi-stop connections with train links
        intermediate_airports = Airport.objects.exclude(
            Q(id=origin.id) | Q(id=destination.id)
        )[:20]  # Limit for performance

        for intermediate in intermediate_airports:
            # Flight to intermediate
            flight1 = Flight.objects.filter(
                origin_airport=origin,
                destination_airport=intermediate,
                departure_time__date=date
            ).first()

            if not flight1:
                continue

            # Flight from intermediate
            flight2 = Flight.objects.filter(
                origin_airport=intermediate,
                destination_airport=destination,
                departure_time__gte=flight1.arrival_time +
                timedelta(minutes=60)
            ).first()

            if not flight2:
                continue

            layover = (flight2.departure_time -
                       flight1.arrival_time).total_seconds() / 60

            # Check for train connection
            train = MultiModalConnectionService.find_train_connections(
                flight1, flight2)

            if train:
                total_cost = flight1.price_eur + flight2.price_eur + train.cost_eur
                total_time = flight1.duration_minutes + \
                    flight2.duration_minutes + train.duration_minutes
                quality = MultiModalConnectionService.calculate_layover_quality_score(
                    intermediate, train.duration_minutes)

                connections.append({
                    'type': 'train_link',
                    'flight1': flight1,
                    'flight2': flight2,
                    'train': train,
                    'intermediate_airport': intermediate,
                    'total_cost': total_cost,
                    'total_time': total_time,
                    'connection_quality': quality,
                    'layover_minutes': layover
                })
            else:
                # Regular connection
                total_cost = flight1.price_eur + flight2.price_eur
                total_time = flight1.duration_minutes + flight2.duration_minutes + layover
                quality = MultiModalConnectionService.calculate_layover_quality_score(
                    intermediate, layover)

                connections.append({
                    'type': 'connection',
                    'flight1': flight1,
                    'flight2': flight2,
                    'intermediate_airport': intermediate,
                    'total_cost': total_cost,
                    'total_time': total_time,
                    'connection_quality': quality,
                    'layover_minutes': layover
                })

        # Sort by total cost, then quality
        connections.sort(key=lambda x: (
            x['total_cost'], -x['connection_quality']))
        return connections


class AIVibeSearchService:
    """Service for AI-driven natural language search"""

    @staticmethod
    def parse_query_with_ai(query_text):
        """Use OpenAI to parse natural language query"""
        if not settings.OPENAI_API_KEY:
            # Fallback to simple parsing
            return AIVibeSearchService._simple_parse(query_text)

        try:
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

            prompt = f"""Parse this travel query and extract structured information:
Query: "{query_text}"

Extract:
- origin_city (if mentioned)
- destination_type (e.g., "warm beach", "mountain", "city", "cultural")
- max_duration_hours (flight duration)
- max_price_eur (budget)
- date_range_start and date_range_end (if mentioned)
- weather_preference (e.g., "warm", "sunny", "snow")

Return JSON only with these fields. Use null for missing values."""

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system",
                        "content": "You are a travel query parser. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            result = json.loads(response.choices[0].message.content)
            return result, 0.9  # High confidence

        except Exception as e:
            print(f"AI parsing error: {e}")
            return AIVibeSearchService._simple_parse(query_text), 0.5

    @staticmethod
    def _simple_parse(query_text):
        """Simple keyword-based parsing fallback"""
        query_lower = query_text.lower()
        result = {
            'origin_city': None,
            'destination_type': None,
            'max_duration_hours': None,
            'max_price_eur': None,
            'date_range_start': None,
            'date_range_end': None,
            'weather_preference': None
        }

        # Extract price
        import re
        price_match = re.search(r'€?(\d+)', query_text)
        if price_match:
            result['max_price_eur'] = float(price_match.group(1))

        # Extract duration
        duration_match = re.search(r'(\d+)\s*hour', query_lower)
        if duration_match:
            result['max_duration_hours'] = int(duration_match.group(1))

        # Extract destination type
        if 'beach' in query_lower:
            result['destination_type'] = 'beach'
            result['weather_preference'] = 'warm'
        elif 'mountain' in query_lower:
            result['destination_type'] = 'mountain'
        elif 'city' in query_lower:
            result['destination_type'] = 'city'

        return result

    @staticmethod
    def search_by_vibe(parsed_query, user):
        """Search flights based on parsed vibe query"""
        # Create search record
        search = TripSearch.objects.create(
            user=user,
            query_text=parsed_query.get('original_query', ''),
            origin_city=parsed_query.get('origin_city'),
            destination_type=parsed_query.get('destination_type'),
            max_duration_hours=parsed_query.get('max_duration_hours'),
            max_price_eur=parsed_query.get('max_price_eur'),
            weather_preference=parsed_query.get('weather_preference'),
            ai_parsed_data=parsed_query
        )

        # Find matching airports based on destination type
        matching_airports = AIVibeSearchService._find_matching_airports(
            parsed_query)

        # Find flights
        origin_airport = None
        if parsed_query.get('origin_city'):
            origin_airport = Airport.objects.filter(
                city__icontains=parsed_query['origin_city']).first()

        if not origin_airport:
            return search, []

        options = []
        for dest_airport in matching_airports[:10]:  # Top 10 matches
            flights = Flight.objects.filter(
                origin_airport=origin_airport,
                destination_airport=dest_airport,
                price_eur__lte=parsed_query.get(
                    'max_price_eur', 99999) or 99999,
                duration_minutes__lte=(parsed_query.get(
                    'max_duration_hours', 24) or 24) * 60
            )[:3]

            for flight in flights:
                # Calculate match score
                match_score = AIVibeSearchService._calculate_match_score(
                    flight, parsed_query)

                option = TripOption.objects.create(
                    search=search,
                    flight=flight,
                    total_trip_cost_eur=flight.price_eur,
                    total_trip_time_minutes=flight.duration_minutes,
                    match_score=match_score
                )
                options.append(option)

        # Rank options
        options.sort(key=lambda x: x.match_score, reverse=True)
        for i, option in enumerate(options[:3], 1):
            option.rank = i
            option.save()

        return search, options[:3]

    @staticmethod
    def _find_matching_airports(parsed_query):
        """Find airports matching destination type"""
        # This would integrate with weather APIs and destination databases
        # For now, return popular destinations
        dest_type = parsed_query.get('destination_type', '').lower()

        if 'beach' in dest_type:
            return Airport.objects.filter(
                Q(city__icontains='Maldives') |
                Q(city__icontains='Bali') |
                Q(city__icontains='Cancun') |
                Q(city__icontains='Phuket')
            )
        elif 'mountain' in dest_type:
            return Airport.objects.filter(
                Q(city__icontains='Zurich') |
                Q(city__icontains='Innsbruck') |
                Q(city__icontains='Geneva')
            )
        else:
            return Airport.objects.all()[:20]

    @staticmethod
    def _calculate_match_score(flight, parsed_query):
        """Calculate how well flight matches query"""
        score = 100.0

        # Price match
        if parsed_query.get('max_price_eur'):
            if flight.price_eur > parsed_query['max_price_eur']:
                score -= 50
            else:
                score += (1 - flight.price_eur /
                          parsed_query['max_price_eur']) * 20

        # Duration match
        if parsed_query.get('max_duration_hours'):
            max_minutes = parsed_query['max_duration_hours'] * 60
            if flight.duration_minutes > max_minutes:
                score -= 30
            else:
                score += (1 - flight.duration_minutes / max_minutes) * 10

        return max(0, min(100, score))


class CollaborativeService:
    """Service for collaborative trip planning"""

    @staticmethod
    def generate_sync_code():
        """Generate unique sync code for partner linking"""
        import random
        import string
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    @staticmethod
    def link_partners(user1, sync_code):
        """Link two users via sync code"""
        try:
            profile2 = UserProfile.objects.get(partner_sync_code=sync_code)
            profile1, _ = UserProfile.objects.get_or_create(user=user1)

            profile1.partner = profile2.user
            profile1.save()

            profile2.partner = user1
            profile2.save()

            return True
        except UserProfile.DoesNotExist:
            return False

    @staticmethod
    def vote_on_option(user, trip_option, vote_type):
        """User votes on a trip option"""
        vote, _ = CollaborativeVote.objects.update_or_create(
            user=user,
            trip_option=trip_option,
            defaults={'vote_type': vote_type}
        )
        return vote

    @staticmethod
    def find_perfect_matches(user1, user2):
        """Find perfect matches where both users liked the same option"""
        user1_votes = CollaborativeVote.objects.filter(
            user=user1,
            vote_type__in=['like', 'super_like']
        ).values_list('trip_option_id', flat=True)

        user2_votes = CollaborativeVote.objects.filter(
            user=user2,
            vote_type__in=['like', 'super_like']
        ).values_list('trip_option_id', flat=True)

        # Find common options
        common_options = set(user1_votes) & set(user2_votes)

        matches = []
        for option_id in common_options:
            option = TripOption.objects.get(id=option_id)
            user1_vote = CollaborativeVote.objects.get(
                user=user1, trip_option=option)
            user2_vote = CollaborativeVote.objects.get(
                user=user2, trip_option=option)

            # Calculate match score
            score = 50.0
            if user1_vote.vote_type == 'super_like':
                score += 25
            if user2_vote.vote_type == 'super_like':
                score += 25

            match, _ = PerfectMatch.objects.update_or_create(
                user1=user1,
                user2=user2,
                trip_option=option,
                defaults={'match_score': score}
            )
            matches.append(match)

        return sorted(matches, key=lambda x: x.match_score, reverse=True)


class DelayPredictionService:
    """Service for delay prediction and self-transfer insurance"""

    @staticmethod
    def predict_delay(flight):
        """Predict delay probability for a flight"""
        route = f"{flight.origin_airport.iata_code}-{flight.destination_airport.iata_code}"
        day_of_week = flight.departure_time.weekday()

        # Try to get historical data
        prediction = DelayPrediction.objects.filter(
            route=route,
            airline=flight.airline,
            day_of_week=day_of_week
        ).first()

        if prediction:
            return {
                'delay_probability': float(prediction.delay_probability),
                'avg_delay_minutes': prediction.avg_delay_minutes,
                'sample_size': prediction.sample_size
            }

        # Default prediction
        return {
            'delay_probability': 15.0,  # 15% default
            'avg_delay_minutes': 30,
            'sample_size': 0
        }

    @staticmethod
    def calculate_self_transfer_risk(connection):
        """Calculate risk for self-transfer connections"""
        if not connection.is_self_transfer:
            return 0.0

        layover_minutes = connection.layover_minutes

        # Get delay predictions
        delay1 = DelayPredictionService.predict_delay(connection.first_flight)
        delay2 = None
        if connection.second_flight:
            delay2 = DelayPredictionService.predict_delay(
                connection.second_flight)

        # Calculate risk
        risk = 0.0

        # Base risk from layover time
        if layover_minutes < 90:
            risk += 40.0
        elif layover_minutes < 120:
            risk += 20.0
        elif layover_minutes < 180:
            risk += 10.0

        # Risk from delay probability
        if delay1:
            risk += delay1['delay_probability'] * 0.5
        if delay2:
            risk += delay2['delay_probability'] * 0.3

        # Risk from average delays
        if delay1 and delay1['avg_delay_minutes'] > layover_minutes * 0.5:
            risk += 20.0

        return min(100.0, risk)

    @staticmethod
    def check_self_transfer_insurance(connection):
        """Check if self-transfer is safe enough"""
        risk = DelayPredictionService.calculate_self_transfer_risk(connection)
        connection.self_transfer_risk = risk
        connection.save()

        if risk < 30:
            recommendation = 'Safe'
        elif risk < 60:
            recommendation = 'Risky'
        else:
            recommendation = 'Very Risky'

        return {
            'is_safe': risk < 30.0,
            'risk_percentage': risk,
            'recommendation': recommendation
        }
