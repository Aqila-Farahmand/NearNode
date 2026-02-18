from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from core.models import UserProfile, Airport, TripOption, Flight, FlightConnection
from core.countries import COUNTRY_CHOICES
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from decimal import Decimal
import json


def _populate_user_profile(user, profile, post_data):
    """Helper function to populate user and profile with additional data"""
    email = post_data.get('email')
    if email:
        user.email = email
        profile.email = email
        user.save()

    if post_data.get('first_name'):
        profile.first_name = post_data.get('first_name')
    if post_data.get('last_name'):
        profile.last_name = post_data.get('last_name')
    if post_data.get('phone_number'):
        profile.phone_number = post_data.get('phone_number')

    profile.save()


def signup_view(request):
    """User registration view"""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            profile = UserProfile.objects.create(user=user)
            _populate_user_profile(user, profile, request.POST)
            login(request, user)
            messages.success(request, 'Account created successfully!')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserCreationForm()

    return render(request, 'core/signup.html', {'form': form})


@require_http_methods(["GET", "POST"])
def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        from django.contrib.auth import authenticate
        username = request.POST.get('username')
        password = request.POST.get('password')

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(
                request, 'Please provide both username and password.')

    return render(request, 'core/login.html')


@login_required
def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('home')


def _initialize_new_profile(profile, user):
    """Helper function to initialize a newly created profile from user data"""
    if user.first_name:
        profile.first_name = user.first_name
    if user.last_name:
        profile.last_name = user.last_name
    if user.email:
        profile.email = user.email
    profile.save()


def _update_profile_from_post(profile, user, post_data, request_obj):
    """Helper function to update profile from POST data"""
    # Update basic profile fields
    profile.first_name = post_data.get('first_name', '')
    profile.last_name = post_data.get('last_name', '')
    profile.email = post_data.get('email', '')
    profile.phone_number = post_data.get('phone_number', '')
    profile.currency = post_data.get('currency', 'EUR')
    raw = (post_data.get('country_code') or '').strip().upper()
    profile.country_code = raw[:2] if len(raw) >= 2 else ''

    # Update user's email if provided
    if profile.email:
        user.email = profile.email
        user.save()

    # Update home airport
    airport_code = post_data.get('home_airport')
    if airport_code:
        try:
            airport = Airport.objects.get(iata_code=airport_code)
            profile.home_airport = airport
        except Airport.DoesNotExist:
            messages.error(request_obj, 'Invalid airport code.')

    # Update location
    lat = post_data.get('latitude')
    lon = post_data.get('longitude')
    if lat and lon:
        try:
            profile.location_latitude = float(lat)
            profile.location_longitude = float(lon)
        except ValueError:
            pass

    profile.save()


@login_required
def profile_view(request):
    """User profile view"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # If profile was just created (e.g., from Google signup), populate from user
    if created:
        _initialize_new_profile(profile, request.user)

    if request.method == 'POST':
        _update_profile_from_post(profile, request.user, request.POST, request)
        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    # Get saved trips
    saved_trips = TripOption.objects.filter(
        saved_by=request.user).order_by('-saved_at', '-created_at')

    # Get all airports for dropdown (world list; order by country, city, name)
    airports = Airport.objects.all().order_by('country', 'city', 'name')

    context = {
        'profile': profile,
        'saved_trips': saved_trips,
        'airports': airports,
        'country_choices': COUNTRY_CHOICES,
    }
    return render(request, 'core/profile.html', context)


def _get_or_create_trip_option(data):
    """Helper function to get or create a trip option from request data.
    Accepts trip_option_id, flight_id, connection_id (DB), or offer (API payload).
    """
    trip_option_id = data.get('trip_option_id')
    flight_id = data.get('flight_id')
    connection_id = data.get('connection_id')
    offer = data.get('offer')

    if trip_option_id:
        return TripOption.objects.get(id=trip_option_id)

    # Save from API (e.g. Amadeus): no DB Flight, store full offer in display_data
    if offer and isinstance(offer, dict):
        cost = offer.get('total_trip_cost_eur')
        minutes = offer.get('total_trip_time_minutes')
        if cost is None:
            cost = Decimal('0')
        if minutes is None:
            minutes = 0
        return TripOption.objects.create(
            flight=None,
            flight_connection=None,
            total_trip_cost_eur=Decimal(str(cost)),
            total_trip_time_minutes=int(minutes),
            display_data=offer,
            match_score=Decimal('100.0'),
            rank=1
        )

    # DB flight (flight_id must be an integer PK)
    if flight_id is not None:
        try:
            fid = int(flight_id)
        except (TypeError, ValueError):
            fid = None
        if fid is not None:
            flight = Flight.objects.get(id=fid)
            return TripOption.objects.create(
                flight=flight,
                total_trip_cost_eur=flight.price_eur,
                total_trip_time_minutes=flight.duration_minutes,
                match_score=Decimal('100.0'),
                rank=1
            )

    if connection_id:
        connection = FlightConnection.objects.get(id=connection_id)
        return TripOption.objects.create(
            flight_connection=connection,
            total_trip_cost_eur=connection.total_cost_eur,
            total_trip_time_minutes=connection.total_duration_minutes,
            match_score=Decimal('100.0'),
            rank=1
        )

    return None


@login_required
@csrf_exempt
def save_trip(request):
    """Save a trip option"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            trip_option = _get_or_create_trip_option(data)

            if not trip_option:
                return JsonResponse({'success': False, 'error': 'No trip identifier provided'}, status=400)

            trip_option.saved_by.add(request.user)
            if not trip_option.saved_at:
                trip_option.saved_at = timezone.now()
                trip_option.save()
            return JsonResponse({'success': True, 'message': 'Trip saved successfully!', 'trip_id': trip_option.id})
        except TripOption.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Trip not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


@login_required
@csrf_exempt
def unsave_trip(request):
    """Remove a saved trip"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            trip_option_id = data.get('trip_option_id')

            if trip_option_id:
                trip_option = TripOption.objects.get(id=trip_option_id)
                trip_option.saved_by.remove(request.user)
                return JsonResponse({'success': True, 'message': 'Trip removed from saved trips'})
        except TripOption.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Trip not found'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    """Delete user account with confirmation"""
    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_text = request.POST.get('confirm_text')

        # Verify password
        if not request.user.check_password(password):
            messages.error(request, 'Incorrect password. Account not deleted.')
            return redirect('profile')

        # Verify confirmation text
        if confirm_text != 'DELETE':
            messages.error(
                request, 'Confirmation text must be "DELETE". Account not deleted.')
            return redirect('profile')

        # Delete user (cascades to profile and related data)
        username = request.user.username
        request.user.delete()

        messages.success(
            request, f'Account "{username}" has been permanently deleted.')
        return redirect('home')

    return render(request, 'core/delete_account.html')
