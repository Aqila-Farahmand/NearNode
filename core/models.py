from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import json


class Airport(models.Model):
    """Airport model with location data"""
    icao_code = models.CharField(max_length=4, unique=True)
    iata_code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    # Layover quality metrics
    has_lounge = models.BooleanField(default=False)
    has_sleeping_pods = models.BooleanField(default=False)
    city_access_time = models.IntegerField(
        default=0, help_text="Minutes to city center")
    layover_quality_score = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(10.0)]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['city', 'country']),
        ]

    def __str__(self):
        return f"{self.name} ({self.iata_code})"

    def distance_to(self, lat, lon):
        """Calculate distance in km to a point"""
        return geodesic((self.latitude, self.longitude), (lat, lon)).kilometers


class GroundTransport(models.Model):
    """Ground transport options (train, bus, Uber, etc.)"""
    TRANSPORT_TYPES = [
        ('train', 'Train'),
        ('bus', 'Bus'),
        ('uber', 'Uber/Taxi'),
        ('car_rental', 'Car Rental'),
        ('shuttle', 'Airport Shuttle'),
    ]

    name = models.CharField(max_length=100)
    transport_type = models.CharField(max_length=20, choices=TRANSPORT_TYPES)
    from_airport = models.ForeignKey(
        Airport, on_delete=models.CASCADE, related_name='departure_transports')
    to_airport = models.ForeignKey(
        Airport, on_delete=models.CASCADE, related_name='arrival_transports', null=True, blank=True)
    to_address = models.CharField(
        max_length=500, blank=True, help_text="Street address if not to airport")
    duration_minutes = models.IntegerField(validators=[MinValueValidator(0)])
    cost_eur = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    distance_km = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} from {self.from_airport.iata_code}"


class Flight(models.Model):
    """Flight information"""
    flight_number = models.CharField(max_length=20)
    airline = models.CharField(max_length=100)
    origin_airport = models.ForeignKey(
        Airport, on_delete=models.CASCADE, related_name='departure_flights')
    destination_airport = models.ForeignKey(
        Airport, on_delete=models.CASCADE, related_name='arrival_flights')
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    price_eur = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    duration_minutes = models.IntegerField(validators=[MinValueValidator(0)])
    available_seats = models.IntegerField(default=0)

    # Delay prediction data
    historical_delay_probability = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0,
        help_text="Probability of delay (0-100)"
    )
    avg_delay_minutes = models.IntegerField(default=0)

    # Mistake fare detection
    is_mistake_fare = models.BooleanField(default=False)
    normal_price_eur = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['departure_time']
        indexes = [
            models.Index(fields=['origin_airport',
                         'destination_airport', 'departure_time']),
            models.Index(fields=['price_eur']),
        ]

    def __str__(self):
        return f"{self.flight_number}: {self.origin_airport.iata_code} -> {self.destination_airport.iata_code}"


class FlightConnection(models.Model):
    """Multi-modal flight connections"""
    first_flight = models.ForeignKey(
        Flight, on_delete=models.CASCADE, related_name='first_connections')
    second_flight = models.ForeignKey(
        Flight, on_delete=models.CASCADE, related_name='second_connections', null=True, blank=True)
    ground_transport = models.ForeignKey(
        GroundTransport, on_delete=models.CASCADE, null=True, blank=True)

    layover_minutes = models.IntegerField(validators=[MinValueValidator(0)])
    total_duration_minutes = models.IntegerField(
        validators=[MinValueValidator(0)])
    total_cost_eur = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    # Connection quality
    connection_quality_score = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(10.0)]
    )
    is_self_transfer = models.BooleanField(default=False)
    self_transfer_risk = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.0,
        help_text="Risk percentage for self-transfer (0-100)"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['total_cost_eur', 'total_duration_minutes']

    def __str__(self):
        if self.second_flight:
            return f"{self.first_flight.origin_airport.iata_code} -> {self.first_flight.destination_airport.iata_code} -> {self.second_flight.destination_airport.iata_code}"
        return f"{self.first_flight.origin_airport.iata_code} -> {self.first_flight.destination_airport.iata_code} (via {self.ground_transport})"


class UserProfile(models.Model):
    """Extended user profile"""
    CURRENCY_CHOICES = [
        ('USD', 'US Dollar ($)'),
        ('EUR', 'Euro (€)'),
        ('GBP', 'British Pound (£)'),
        ('JPY', 'Japanese Yen (¥)'),
        ('CAD', 'Canadian Dollar (C$)'),
        ('AUD', 'Australian Dollar (A$)'),
        ('CHF', 'Swiss Franc (CHF)'),
        ('CNY', 'Chinese Yuan (¥)'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile')

    # Personal Information
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    country_code = models.CharField(
        max_length=2,
        blank=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g. US, GB)"
    )

    # Location & Preferences
    home_airport = models.ForeignKey(
        Airport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='home_users',
        help_text="User's home airport"
    )
    currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='EUR',
        help_text="Preferred currency for price display"
    )
    location_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True)
    location_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True)

    # Collaborative Features
    partner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='partner_profile',
        help_text="Linked partner for collaborative mode"
    )
    partner_sync_code = models.CharField(
        max_length=20, unique=True, null=True, blank=True)
    budget_preference_eur = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    preferred_airlines = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def get_full_name(self):
        """Get user's full name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.user.username


class TripSearch(models.Model):
    """User trip search with vibe/NLP query"""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='trip_searches')
    query_text = models.TextField(help_text="Natural language search query")

    # Parsed parameters
    origin_city = models.CharField(max_length=100, blank=True)
    destination_type = models.CharField(
        max_length=100, blank=True, help_text="e.g., 'warm beach', 'mountain', 'city'")
    max_duration_hours = models.IntegerField(null=True, blank=True)
    max_price_eur = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True)
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    weather_preference = models.CharField(max_length=50, blank=True)

    # AI processing
    ai_confidence_score = models.DecimalField(
        max_digits=3, decimal_places=2, default=0.0)
    ai_parsed_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Search by {self.user.username}: {self.query_text[:50]}..."


class TripOption(models.Model):
    """Individual trip option result from a search"""
    search = models.ForeignKey(
        TripSearch, on_delete=models.CASCADE, related_name='options', null=True, blank=True)
    flight_connection = models.ForeignKey(
        FlightConnection, on_delete=models.CASCADE, null=True, blank=True)
    flight = models.ForeignKey(
        Flight, on_delete=models.CASCADE, null=True, blank=True)

    # For nearest alternate optimization
    final_destination_address = models.CharField(
        max_length=500, blank=True)
    ground_transport_to_destination = models.ForeignKey(
        GroundTransport, on_delete=models.SET_NULL, null=True, blank=True)
    total_trip_cost_eur = models.DecimalField(max_digits=10, decimal_places=2)
    total_trip_time_minutes = models.IntegerField()

    # Ranking
    match_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.0)
    rank = models.IntegerField(default=0)

    # Saved trips
    saved_by = models.ManyToManyField(
        User,
        related_name='saved_trips',
        blank=True,
        help_text="Users who saved this trip"
    )
    saved_at = models.DateTimeField(null=True, blank=True)

    # When saved from real API (e.g. Amadeus), store offer payload; flight is null
    display_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Flight/offer details when saved from API (no DB flight)"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['rank', 'total_trip_cost_eur']

    def get_origin_display(self):
        """Origin code for display (from flight or display_data)."""
        if self.flight:
            return self.flight.origin_airport.iata_code
        data = self.display_data or {}
        o = (data.get('flight') or {}).get('origin_airport') or {}
        return o.get('iata_code', '') if isinstance(o, dict) else str(o)

    def get_destination_display(self):
        """Destination code for display."""
        if self.flight:
            return self.flight.destination_airport.iata_code
        data = self.display_data or {}
        d = (data.get('flight') or {}).get('destination_airport') or {}
        return d.get('iata_code', '') if isinstance(d, dict) else str(d)

    def __str__(self):
        return f"Option {self.rank} for search {self.search.id if self.search else 'unsaved'}"


class CollaborativeVote(models.Model):
    """Votes for collaborative trip planning"""
    VOTE_TYPES = [
        ('like', 'Like'),
        ('dislike', 'Dislike'),
        ('super_like', 'Super Like'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='votes')
    trip_option = models.ForeignKey(
        TripOption, on_delete=models.CASCADE, related_name='votes')
    vote_type = models.CharField(max_length=20, choices=VOTE_TYPES)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'trip_option']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} {self.vote_type} option {self.trip_option.id}"


class PerfectMatch(models.Model):
    """Perfect matches from collaborative voting"""
    user1 = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='matches_as_user1')
    user2 = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='matches_as_user2')
    trip_option = models.ForeignKey(
        TripOption, on_delete=models.CASCADE, related_name='perfect_matches')
    match_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-match_score', '-created_at']

    def __str__(self):
        return f"Match: {self.user1.username} & {self.user2.username} - Option {self.trip_option.id}"


class DelayPrediction(models.Model):
    """Historical delay prediction data"""
    route = models.CharField(max_length=50, help_text="e.g., 'LHR-JFK'")
    airline = models.CharField(max_length=100)
    day_of_week = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)])
    time_of_day = models.TimeField()

    delay_probability = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.0)
    avg_delay_minutes = models.IntegerField(default=0)
    sample_size = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['route', 'airline', 'day_of_week', 'time_of_day']
        indexes = [
            models.Index(fields=['route', 'airline']),
        ]

    def __str__(self):
        return f"{self.route} - {self.airline}: {self.delay_probability}% delay risk"
