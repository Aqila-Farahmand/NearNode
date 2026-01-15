from rest_framework import serializers
from django.contrib.auth.models import User
from core.models import (
    Airport, Flight, FlightConnection, GroundTransport,
    UserProfile, TripSearch, TripOption, CollaborativeVote,
    PerfectMatch, DelayPrediction
)


class AirportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Airport
        fields = '__all__'


class GroundTransportSerializer(serializers.ModelSerializer):
    from_airport = AirportSerializer(read_only=True)
    to_airport = AirportSerializer(read_only=True)

    class Meta:
        model = GroundTransport
        fields = '__all__'


class FlightSerializer(serializers.ModelSerializer):
    origin_airport = AirportSerializer(read_only=True)
    destination_airport = AirportSerializer(read_only=True)

    class Meta:
        model = Flight
        fields = '__all__'


class FlightConnectionSerializer(serializers.ModelSerializer):
    first_flight = FlightSerializer(read_only=True)
    second_flight = FlightSerializer(read_only=True)
    ground_transport = GroundTransportSerializer(read_only=True)

    class Meta:
        model = FlightConnection
        fields = '__all__'


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    partner = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = '__all__'


class TripSearchSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = TripSearch
        fields = '__all__'


class TripOptionSerializer(serializers.ModelSerializer):
    search = TripSearchSerializer(read_only=True)
    flight_connection = FlightConnectionSerializer(read_only=True)
    flight = FlightSerializer(read_only=True)
    ground_transport_to_destination = GroundTransportSerializer(read_only=True)

    class Meta:
        model = TripOption
        fields = '__all__'


class CollaborativeVoteSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    trip_option = TripOptionSerializer(read_only=True)

    class Meta:
        model = CollaborativeVote
        fields = '__all__'


class PerfectMatchSerializer(serializers.ModelSerializer):
    user1 = UserSerializer(read_only=True)
    user2 = UserSerializer(read_only=True)
    trip_option = TripOptionSerializer(read_only=True)

    class Meta:
        model = PerfectMatch
        fields = '__all__'


class DelayPredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DelayPrediction
        fields = '__all__'
