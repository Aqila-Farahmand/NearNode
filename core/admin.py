from django.contrib import admin
from .models import (
    Airport, Flight, FlightConnection, GroundTransport,
    UserProfile, TripSearch, TripOption, CollaborativeVote,
    PerfectMatch, DelayPrediction
)


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ['name', 'iata_code', 'city',
                    'country', 'layover_quality_score']
    list_filter = ['country', 'has_lounge', 'has_sleeping_pods']
    search_fields = ['name', 'iata_code', 'icao_code', 'city']


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ['flight_number', 'airline', 'origin_airport',
                    'destination_airport', 'departure_time', 'price_eur', 'is_mistake_fare']
    list_filter = ['airline', 'is_mistake_fare', 'departure_time']
    search_fields = ['flight_number', 'airline']
    date_hierarchy = 'departure_time'


@admin.register(FlightConnection)
class FlightConnectionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'total_cost_eur', 'total_duration_minutes',
                    'connection_quality_score', 'is_self_transfer']
    list_filter = ['is_self_transfer']


@admin.register(GroundTransport)
class GroundTransportAdmin(admin.ModelAdmin):
    list_display = ['name', 'transport_type',
                    'from_airport', 'duration_minutes', 'cost_eur']
    list_filter = ['transport_type']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'partner', 'budget_preference_eur']
    search_fields = ['user__username', 'partner_sync_code']


@admin.register(TripSearch)
class TripSearchAdmin(admin.ModelAdmin):
    list_display = ['user', 'query_text', 'origin_city',
                    'max_price_eur', 'ai_confidence_score', 'created_at']
    list_filter = ['created_at']
    search_fields = ['query_text', 'user__username']


@admin.register(TripOption)
class TripOptionAdmin(admin.ModelAdmin):
    list_display = ['search', 'rank', 'total_trip_cost_eur',
                    'total_trip_time_minutes', 'match_score']
    list_filter = ['rank']


@admin.register(CollaborativeVote)
class CollaborativeVoteAdmin(admin.ModelAdmin):
    list_display = ['user', 'trip_option', 'vote_type', 'created_at']
    list_filter = ['vote_type', 'created_at']


@admin.register(PerfectMatch)
class PerfectMatchAdmin(admin.ModelAdmin):
    list_display = ['user1', 'user2',
                    'trip_option', 'match_score', 'created_at']
    list_filter = ['created_at']


@admin.register(DelayPrediction)
class DelayPredictionAdmin(admin.ModelAdmin):
    list_display = ['route', 'airline', 'delay_probability',
                    'avg_delay_minutes', 'sample_size']
    list_filter = ['airline', 'day_of_week']
