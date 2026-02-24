"""
Service layer for business logic
"""
import json
from datetime import datetime, timedelta

import httpx
import openai
from django.conf import settings
from django.db.models import Q, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

from core.models import Airport, Flight, FlightConnection, GroundTransport, TripOption, TripSearch, CollaborativeVote, PerfectMatch, DelayPrediction, UserProfile


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
                                 final_destination_address, dest_lat, dest_lon):
    """Get Amadeus offers for origin->airport and return list of result dicts.
    Ground transport: real from Navitia if configured, else from DB.
    """
    from api.amadeus_client import search_flight_offers
    from api import ground_transport_client as gtc
    offers = search_flight_offers(origin_code, airport.iata_code, date_str)
    transport = None
    ground_cost = 0.0
    transport_duration = 0
    if gtc.is_configured() and dest_lat is not None and dest_lon is not None:
        journeys = gtc.get_journeys(
            float(airport.latitude), float(airport.longitude),
            dest_lat, dest_lon,
        )
        if journeys:
            transport = journeys[0]
            ground_cost = float(transport.get('cost_eur', 0))
            transport_duration = int(transport.get('duration_minutes', 0))
    if transport is None:
        ground_transports = list(
            GroundTransport.objects.filter(
                from_airport=airport,
                to_address=(final_destination_address or '').strip()
            )
        )
        if not ground_transports:
            ground_transports = list(
                GroundTransport.objects.filter(from_airport=airport)[:1])
        transport = ground_transports[0] if ground_transports else None
        if transport:
            ground_cost = float(transport.cost_eur)
            transport_duration = transport.duration_minutes
    results = []
    for offer in offers:
        flight_cost = offer.get('price_eur', 0)
        duration = offer.get('duration_minutes', 0)
        total_time = duration + transport_duration
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
    dest_lat, dest_lon = NearestAlternateService._resolve_destination_coords(
        final_destination_address)
    if not dest_lat or not dest_lon:
        return []
    nearby_airports = NearestAlternateService.find_airports_in_radius(
        dest_lat, dest_lon, radius_km)
    try:
        origin_airport = Airport.objects.get(iata_code=origin_code)
    except Airport.DoesNotExist:
        return []
    date_str = date.strftime('%Y-%m-%d')
    results = []
    for item in nearby_airports:
        results.extend(_real_alternates_for_airport(
            origin_code, origin_airport, item['airport'], item['distance_km'],
            date_str, final_destination_address, dest_lat, dest_lon
        ))
    results.sort(key=lambda x: (x['total_cost_eur'], x['total_time_minutes']))
    return results


class MultiModalConnectionService:
    """Service for multi-modal connections with train links"""

    @staticmethod
    def calculate_layover_quality_score(airport, layover_minutes):
        """Calculate layover quality based on airport amenities and time."""
        if airport is None:
            return 0.0
        score = 0.0
        try:
            score += float(airport.layover_quality_score or 0)
        except (TypeError, ValueError):
            pass
        layover_minutes = int(layover_minutes) if layover_minutes is not None else 0
        if 60 <= layover_minutes <= 180:
            score += 2.0
        elif layover_minutes < 45:
            score -= 3.0
        elif layover_minutes > 360:
            score -= 1.0
        if getattr(airport, 'has_lounge', False):
            score += 1.5
        if getattr(airport, 'has_sleeping_pods', False):
            score += 1.0
        city_access = getattr(airport, 'city_access_time', 0) or 0
        if city_access > 0 and layover_minutes > 180:
            score += 1.0
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
    def _add_direct_connections(connections, origin, destination, date):
        """Append direct flights to connections list."""
        for flight in Flight.objects.filter(
            origin_airport=origin,
            destination_airport=destination,
            departure_time__date=date
        ):
            connections.append({
                'type': 'direct',
                'flight': flight,
                'total_cost': flight.price_eur,
                'total_time': flight.duration_minutes,
                'connection_quality': 10.0
            })

    @staticmethod
    def _add_train_link_connection(connections, seen, flight1, train, flight2,
                                    airport_a, airport_b, max_layover_mins):
        """Append one train-link connection if valid and not duplicate."""
        layover = (flight2.departure_time - flight1.arrival_time).total_seconds() / 60
        if layover > max_layover_mins:
            return
        key = (flight1.id, train.id, flight2.id)
        if key in seen:
            return
        seen.add(key)
        quality = MultiModalConnectionService.calculate_layover_quality_score(
            airport_a, int(layover))
        connections.append({
            'type': 'train_link',
            'flight1': flight1,
            'flight2': flight2,
            'train': train,
            'intermediate_airport': airport_a,
            'intermediate_airport_b': airport_b,
            'total_cost': flight1.price_eur + flight2.price_eur + train.cost_eur,
            'total_time': flight1.duration_minutes + flight2.duration_minutes + train.duration_minutes,
            'connection_quality': quality,
            'layover_minutes': int(layover)
        })

    @staticmethod
    def _add_same_airport_connection(connections, seen, flight1, flight2,
                                     intermediate, max_layover_mins):
        """Append one same-airport connection if valid and not duplicate."""
        layover = (flight2.departure_time - flight1.arrival_time).total_seconds() / 60
        if layover > max_layover_mins:
            return
        key = (flight1.id, None, flight2.id)
        if key in seen:
            return
        seen.add(key)
        quality = MultiModalConnectionService.calculate_layover_quality_score(
            intermediate, int(layover))
        connections.append({
            'type': 'connection',
            'flight1': flight1,
            'flight2': flight2,
            'intermediate_airport': intermediate,
            'total_cost': flight1.price_eur + flight2.price_eur,
            'total_time': flight1.duration_minutes + flight2.duration_minutes + int(layover),
            'connection_quality': quality,
            'layover_minutes': int(layover)
        })

    @staticmethod
    def create_multi_modal_connection(origin, destination, date):
        """Create connections with train links when beneficial.

        Train links: fly to airport A, take train to airport B, fly from B.
        Same-airport connections: fly to intermediate, fly from same intermediate.
        """
        connections = []
        seen = set()
        min_connection_mins = 60
        max_layover_mins = 6 * 60

        MultiModalConnectionService._add_direct_connections(
            connections, origin, destination, date)

        first_legs = Flight.objects.filter(
            origin_airport=origin,
            departure_time__date=date
        ).select_related('destination_airport').exclude(
            destination_airport=destination
        )[:50]
        for flight1 in first_legs:
            airport_a = flight1.destination_airport
            for train in GroundTransport.objects.filter(
                    from_airport=airport_a,
                    transport_type='train'
            ).exclude(to_airport__isnull=True).exclude(to_airport=airport_a):
                airport_b = train.to_airport
                if airport_b.id == destination.id:
                    continue
                layover_min = min_connection_mins + train.duration_minutes
                flight2 = Flight.objects.filter(
                    origin_airport=airport_b,
                    destination_airport=destination,
                    departure_time__date=date,
                    departure_time__gte=flight1.arrival_time + timedelta(minutes=layover_min)
                ).first()
                if flight2:
                    MultiModalConnectionService._add_train_link_connection(
                        connections, seen, flight1, train, flight2,
                        airport_a, airport_b, max_layover_mins)

        for intermediate in Airport.objects.exclude(
                Q(id=origin.id) | Q(id=destination.id))[:20]:
            flight1 = Flight.objects.filter(
                origin_airport=origin,
                destination_airport=intermediate,
                departure_time__date=date
            ).first()
            if not flight1:
                continue
            flight2 = Flight.objects.filter(
                origin_airport=intermediate,
                destination_airport=destination,
                departure_time__gte=flight1.arrival_time + timedelta(minutes=min_connection_mins)
            ).first()
            if flight2:
                MultiModalConnectionService._add_same_airport_connection(
                    connections, seen, flight1, flight2, intermediate, max_layover_mins)

        connections.sort(key=lambda x: (x['total_cost'], -x['connection_quality']))
        return connections


class AISearchService:
    """AI Search: natural language search for trips. User writes text; AI parses and finds options. Supports OpenAI, Groq, or Ollama."""

    @staticmethod
    def _strip_markdown_code_block(text):
        """Remove optional ```...``` wrapper from text."""
        if not text.startswith("```"):
            return text
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    @staticmethod
    def _parse_first_json_object(text):
        """Find first {...} with balanced braces and parse as JSON. Returns dict or None."""
        start = text.find('{')
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    @staticmethod
    def _extract_json_from_content(content):
        """Strip markdown code blocks and parse JSON from LLM response. Tolerates extra text (e.g. from TinyLlama)."""
        if not content or not content.strip():
            return None
        text = content.strip()
        text = AISearchService._strip_markdown_code_block(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        return AISearchService._parse_first_json_object(text)

    @staticmethod
    def _get_llm_client_and_model():
        """
        Return (client, model_name) for Ollama only, or (None, None).
        AI Search uses local Ollama only; no OpenAI/Groq. If Ollama is not configured or not running, keyword fallback is used.
        """
        backend = (getattr(settings, 'AI_SEARCH_LLM_BACKEND', None) or '').strip().lower()
        if backend != 'ollama':
            return None, None

        base_url = (getattr(settings, 'OLLAMA_BASE_URL', None) or '').strip().rstrip('/')
        model = (getattr(settings, 'AI_SEARCH_OLLAMA_MODEL', None) or '').strip()
        if not base_url or not model:
            return None, None

        if not base_url.endswith('/v1'):
            base_url = base_url + '/v1'
        base_url = base_url + '/'
        http_client = httpx.Client(timeout=60.0)
        client = openai.OpenAI(api_key='ollama', base_url=base_url, http_client=http_client)
        return client, model

    @staticmethod
    def get_available_origin_cities():
        """Return list of city names that have at least one outgoing flight in the database (for LLM context)."""
        return list(
            Airport.objects.filter(
                id__in=Flight.objects.values_list('origin_airport_id', flat=True).distinct()
            ).values_list('city', flat=True).distinct().order_by('city')
        )

    @staticmethod
    def get_available_destination_cities():
        """Return list of city names that are destinations of at least one flight (for LLM context)."""
        return list(
            Airport.objects.filter(
                id__in=Flight.objects.values_list('destination_airport_id', flat=True).distinct()
            ).values_list('city', flat=True).distinct().order_by('city')
        )

    @staticmethod
    def parse_query_with_ai(query_text, available_origin_cities=None, available_destination_cities=None):
        """Use configured LLM to parse natural language query. Optionally pass DB-derived origin/destination cities so the model can normalize to actual data."""
        client, model = AISearchService._get_llm_client_and_model()
        if client is None:
            return AISearchService._simple_parse(query_text), 0.5

        db_context = ''
        if available_origin_cities:
            db_context += f"\nAvailable origin cities in our flight database (use one of these if the user's origin matches): {', '.join(available_origin_cities)}."
        if available_destination_cities:
            db_context += f"\nAvailable destination cities in our database: {', '.join(available_destination_cities)}."

        prompt = f"""Parse this travel query and extract structured information:
Query: "{query_text}"
{db_context}

Extract:
- origin_city (if mentioned; prefer a city from the available list when it matches the user's intent)
- destination_type (e.g., "warm beach", "mountain", "city", "cultural")
- max_duration_hours (flight duration in hours)
- max_price_eur (budget as number)
- date_range_start and date_range_end (if mentioned)
- weather_preference (e.g., "warm", "sunny", "snow")

Return only a single JSON object with these keys. Use null for missing values. No markdown, no code block."""

        import logging
        logger = logging.getLogger(__name__)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system",
                     "content": "You are a travel query parser. Reply with exactly one JSON object, no other text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                timeout=60.0,
            )
            raw = response.choices[0].message.content if response.choices else None
            if not raw:
                logger.warning("AI search: empty response from LLM")
                return AISearchService._simple_parse(query_text), 0.5
            result = AISearchService._extract_json_from_content(raw)
            if result and isinstance(result, dict):
                return result, 0.9
            logger.debug("AI search: could not parse JSON from LLM response: %s", raw[:200] if raw else "")
            return AISearchService._simple_parse(query_text), 0.5
        except Exception as e:
            err_msg = str(e).lower()
            if 'refused' in err_msg or 'connection' in err_msg:
                model_name = (getattr(settings, 'AI_SEARCH_OLLAMA_MODEL', None) or '').strip() or 'model from .env'
                logger.warning(
                    "Ollama not running. Using keyword fallback. Start Ollama with your AI_SEARCH_OLLAMA_MODEL (%s).",
                    model_name,
                )
            else:
                logger.warning("AI search parse failed: %s", e, exc_info=True)
            return AISearchService._simple_parse(query_text), 0.5

    @staticmethod
    def _parse_origin_keywords(query_text, query_lower):
        """Extract origin_city from 'from X' or first word. Case-insensitive."""
        import re
        from_match = re.search(r'(?:from|flying from)\s+([a-z]+)', query_text, re.IGNORECASE)
        if from_match:
            return from_match.group(1).strip()
        first_word = re.match(r'^\s*([a-z]+)', query_text, re.IGNORECASE)
        if not first_word:
            return None
        w = first_word.group(1).strip()
        stop = ('i', 'a', 'the', 'want', 'need', 'looking', 'for', 'to', 'my', 'me', 'hi', 'hello')
        return w if w.lower() not in stop and len(w) > 1 else None

    @staticmethod
    def _parse_destination_weather_keywords(query_lower):
        """Extract destination_type and weather_preference from keywords. Returns (dest_type, weather)."""
        dest_type, weather = None, None
        if 'beach' in query_lower or 'sea' in query_lower:
            dest_type, weather = 'beach', 'warm'
        elif 'mountain' in query_lower or 'ski' in query_lower:
            dest_type, weather = 'mountain', 'snow'
        elif 'city' in query_lower or 'cities' in query_lower:
            dest_type = 'city'
        if 'warm' in query_lower or 'sun' in query_lower or 'sunny' in query_lower:
            weather = 'warm'
        elif 'snow' in query_lower or 'cold' in query_lower:
            weather = 'snow'
        return dest_type, weather

    @staticmethod
    def _simple_parse(query_text):
        """Keyword-based parsing when Ollama is not used. Extracts origin, destination type, budget, duration, weather."""
        import re
        empty = {
            'origin_city': None, 'destination_type': None, 'max_duration_hours': None,
            'max_price_eur': None, 'date_range_start': None, 'date_range_end': None,
            'weather_preference': None
        }
        if not query_text or not str(query_text).strip():
            return empty
        query_lower = str(query_text).lower().strip()
        result = dict(empty)
        result['origin_city'] = AISearchService._parse_origin_keywords(query_text, query_lower)
        price_match = re.search(r'€?\s*(\d+)\s*(?:eur|euro|€|euros)?', query_lower)
        if price_match:
            try:
                result['max_price_eur'] = float(price_match.group(1))
            except (TypeError, ValueError):
                pass
        duration_match = re.search(r'(\d+)\s*-?\s*h(?:our)?s?', query_lower)
        if duration_match:
            try:
                result['max_duration_hours'] = int(duration_match.group(1))
            except (TypeError, ValueError):
                pass
        dest_type, weather = AISearchService._parse_destination_weather_keywords(query_lower)
        if dest_type:
            result['destination_type'] = dest_type
        if weather:
            result['weather_preference'] = weather
        return result

    @staticmethod
    def _departure_date_from_parsed(parsed_query):
        """Return (date_str, date) for AI search. Uses date_range_start or default 7 days from today."""
        start = parsed_query.get('date_range_start')
        if start:
            if isinstance(start, str):
                try:
                    dt = datetime.strptime(start[:10], '%Y-%m-%d')
                    return start[:10], dt.date()
                except ValueError:
                    pass
            if hasattr(start, 'strftime'):
                return start.strftime('%Y-%m-%d'), start
        default = datetime.now().date() + timedelta(days=7)
        return default.strftime('%Y-%m-%d'), default

    @staticmethod
    def _dest_airports_for_amadeus(parsed_query, origin_airport):
        """Return list of destination airports for Amadeus: from DB (query match or flights from origin), else any airports in DB."""
        matching = AISearchService._find_matching_airports(parsed_query, origin_airport)
        dest = [a for a in matching[:10] if a.id != origin_airport.id]
        if dest:
            return dest
        return list(Airport.objects.exclude(id=origin_airport.id)[:20])

    @staticmethod
    def _search_by_query_amadeus(parsed_query, origin_airport, max_price, max_minutes):
        """Run AI search using Amadeus Flight Offers API. Returns list of match dicts."""
        from api.amadeus_client import search_flight_offers_for_ai_search
        date_str, _ = AISearchService._departure_date_from_parsed(parsed_query)
        dest_airports = AISearchService._dest_airports_for_amadeus(parsed_query, origin_airport)
        origin_dict = {
            'iata_code': origin_airport.iata_code,
            'name': origin_airport.name,
            'city': getattr(origin_airport, 'city', '') or '',
        }
        all_offers = []
        for dest_airport in dest_airports:
            dest_dict = {
                'iata_code': dest_airport.iata_code,
                'name': dest_airport.name,
                'city': getattr(dest_airport, 'city', '') or '',
            }
            offers = search_flight_offers_for_ai_search(
                origin_airport.iata_code,
                dest_airport.iata_code,
                date_str,
                origin_airport_dict=origin_dict,
                destination_airport_dict=dest_dict,
            )
            all_offers.extend(
                AISearchService._amadeus_offers_to_matches(
                    offers, parsed_query, max_price, max_minutes)
            )
        all_offers.sort(key=lambda x: (x['match_score'], -x['total_trip_cost_eur']), reverse=True)
        return all_offers[:3]

    @staticmethod
    def _amadeus_offers_to_matches(offers, parsed_query, max_price, max_minutes):
        """Convert Amadeus offer dicts to match dicts, filtering by price/duration."""
        out = []
        for flight_dict in offers:
            price_eur = float(flight_dict.get('price_eur', 0))
            dur = int(flight_dict.get('duration_minutes', 0))
            if price_eur <= max_price and dur <= max_minutes:
                out.append({
                    'flight': flight_dict,
                    'match_score': AISearchService._calculate_match_score(flight_dict, parsed_query),
                    'total_trip_cost_eur': price_eur,
                    'total_trip_time_minutes': dur,
                })
        return out

    @staticmethod
    def _parse_budget_and_duration(parsed_query):
        """Return (max_price, max_minutes) from parsed query. Coerces LLM strings."""
        try:
            max_price = float(parsed_query.get('max_price_eur') or 99999)
        except (TypeError, ValueError):
            max_price = 99999
        try:
            max_hours = int(parsed_query.get('max_duration_hours') or 24)
        except (TypeError, ValueError):
            max_hours = 24
        return max_price, max_hours * 60

    @staticmethod
    def _search_by_query_db(search, parsed_query, origin_airport, max_price, max_minutes):
        """Run AI search using flights in the database. Returns (search, options list of TripOption)."""
        matching_airports = AISearchService._find_matching_airports(
            parsed_query, origin_airport)
        dest_airports = [a for a in matching_airports[:10] if a.id != origin_airport.id]
        options = []
        for dest_airport in dest_airports:
            flights = Flight.objects.filter(
                origin_airport=origin_airport,
                destination_airport=dest_airport,
                price_eur__lte=max_price,
                duration_minutes__lte=max_minutes
            )[:3]
            for flight in flights:
                match_score = AISearchService._calculate_match_score(flight, parsed_query)
                option = TripOption.objects.create(
                    search=search,
                    flight=flight,
                    total_trip_cost_eur=flight.price_eur,
                    total_trip_time_minutes=flight.duration_minutes,
                    match_score=match_score
                )
                options.append(option)
        options.sort(key=lambda x: x.match_score, reverse=True)
        for i, option in enumerate(options[:3], 1):
            option.rank = i
            option.save()
        return search, options[:3]

    @staticmethod
    def search_by_query(parsed_query, user):
        """Search flights based on parsed natural-language query. Uses Amadeus when configured, else flights in the database."""
        search = TripSearch.objects.create(
            user=user,
            query_text=parsed_query.get('original_query') or '',
            origin_city=parsed_query.get('origin_city') or '',
            destination_type=parsed_query.get('destination_type') or '',
            max_duration_hours=parsed_query.get('max_duration_hours'),
            max_price_eur=parsed_query.get('max_price_eur'),
            weather_preference=parsed_query.get('weather_preference') or '',
            ai_parsed_data=parsed_query
        )
        origin_airport = AISearchService._resolve_origin_airport(
            parsed_query.get('origin_city'))
        if not origin_airport:
            return search, []

        max_price, max_minutes = AISearchService._parse_budget_and_duration(parsed_query)

        try:
            from api.amadeus_client import is_configured as amadeus_configured
        except ImportError:
            amadeus_configured = lambda: False
        if amadeus_configured():
            try:
                top = AISearchService._search_by_query_amadeus(
                    parsed_query, origin_airport, max_price, max_minutes)
                return search, top
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    'AI search Amadeus call failed, falling back to DB', exc_info=True)

        return AISearchService._search_by_query_db(
            search, parsed_query, origin_airport, max_price, max_minutes)

    @staticmethod
    def _origin_airport_candidates(origin):
        """Return list of Airport candidates for origin city name (city, name, or aliases)."""
        candidates = list(Airport.objects.filter(city__icontains=origin))
        if candidates:
            return candidates
        candidates = list(Airport.objects.filter(name__icontains=origin))
        if candidates:
            return candidates
        aliases = {'milan': ['milano'], 'rome': ['roma'], 'munich': ['muenchen', 'münchen']}
        lower = origin.lower()
        for _city, alternates in aliases.items():
            if lower != _city and lower not in alternates:
                continue
            for alt in [origin, _city] + alternates:
                candidates = list(Airport.objects.filter(
                    Q(city__icontains=alt) | Q(name__icontains=alt)
                ))
                if candidates:
                    return candidates
        return []

    @staticmethod
    def _resolve_origin_airport(origin_city):
        """Resolve origin city name to an Airport. Prefers an airport that has outgoing flights in the database."""
        if not origin_city or not str(origin_city).strip():
            return None
        import re
        origin = str(origin_city).strip()
        # Strip "from X" prefix so we match city name
        origin = re.sub(r'^(?:from|flying from)\s+', '', origin, flags=re.IGNORECASE).strip() or origin
        origin = re.sub(r'[.,;!?]+$', '', origin).strip() or origin  # trailing punctuation
        if not origin:
            return None
        candidates = AISearchService._origin_airport_candidates(origin)
        if not candidates:
            return None
        for airport in candidates:
            if Flight.objects.filter(origin_airport=airport).exists():
                return airport
        return candidates[0]

    @staticmethod
    def _destination_type_keywords(dest_type):
        """Return search keywords for destination type; used to query actual Airport table (no hardcoded city list)."""
        if 'beach' in dest_type or 'sea' in dest_type:
            return ['beach', 'maldives', 'bali', 'cancun', 'phuket', 'palma', 'malaga', 'tenerife', 'faro', 'dubrovnik']
        if 'mountain' in dest_type or 'ski' in dest_type:
            return ['zurich', 'innsbruck', 'geneva', 'chamonix', 'alps', 'salzburg', 'grenoble']
        if 'city' in dest_type or 'cultural' in dest_type:
            return ['paris', 'london', 'rome', 'berlin', 'madrid', 'barcelona', 'amsterdam', 'vienna']
        return [dest_type] if dest_type else []

    @staticmethod
    def _find_matching_airports(parsed_query, origin_airport=None):
        """Find airports from the actual database: match destination_type by keyword in Airport city/name, else use destinations that have flights from origin."""
        dest_type = (parsed_query.get('destination_type') or '').lower()
        weather_pref = (parsed_query.get('weather_preference') or '').lower()
        if not dest_type and weather_pref:
            if weather_pref in ('warm', 'sunny', 'sun'):
                dest_type = 'beach'
            elif weather_pref in ('snow', 'cold'):
                dest_type = 'mountain'

        keywords = AISearchService._destination_type_keywords(dest_type)
        if keywords:
            q = Q()
            for k in keywords:
                q |= Q(city__icontains=k) | Q(name__icontains=k)
            qs = Airport.objects.filter(q).distinct()
            if qs.exists():
                return qs
        # Use actual flights database: destinations that have at least one flight from origin
        if origin_airport:
            dest_ids = Flight.objects.filter(origin_airport=origin_airport).values_list(
                'destination_airport_id', flat=True
            ).distinct()
            return Airport.objects.filter(id__in=dest_ids)
        return Airport.objects.all()[:20]

    @staticmethod
    def _calculate_match_score(flight, parsed_query):
        """Calculate how well flight matches query. flight can be a Flight model or a dict with price_eur, duration_minutes."""
        score = 100.0
        try:
            max_price = float(parsed_query.get('max_price_eur') or 0)
        except (TypeError, ValueError):
            max_price = 0
        try:
            max_hours = int(parsed_query.get('max_duration_hours') or 0)
        except (TypeError, ValueError):
            max_hours = 0

        price_eur = float(flight.get('price_eur', 0) if isinstance(flight, dict) else getattr(flight, 'price_eur', 0))
        duration_minutes = int(flight.get('duration_minutes', 0) if isinstance(flight, dict) else getattr(flight, 'duration_minutes', 0))

        if max_price > 0:
            if price_eur > max_price:
                score -= 50
            else:
                score += (1 - price_eur / max_price) * 20
        if max_hours > 0:
            max_minutes = max_hours * 60
            if duration_minutes > max_minutes:
                score -= 30
            else:
                score += (1 - duration_minutes / max_minutes) * 10
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
