from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AirportViewSet, FlightViewSet,
    nearest_alternate_search, multi_modal_search, vibe_search,
    generate_partner_sync_code, link_partner, vote_on_trip,
    get_perfect_matches, predict_delay, check_self_transfer_insurance,
    get_user_profile, update_user_profile,
    nearest_airport,
)

router = DefaultRouter()
router.register(r'airports', AirportViewSet, basename='airport')
router.register(r'flights', FlightViewSet, basename='flight')

urlpatterns = [
    path('', include(router.urls)),

    # Feature 1: Nearest Alternate Optimization
    path('nearest-alternate/', nearest_alternate_search, name='nearest-alternate'),

    # Feature 2: Multi-Modal Connections
    path('multi-modal/', multi_modal_search, name='multi-modal'),

    # Feature 3: AI Vibe Search
    path('vibe-search/', vibe_search, name='vibe-search'),

    # Feature 4: Collaborative Mode
    path('collaborative/generate-code/',
         generate_partner_sync_code, name='generate-sync-code'),
    path('collaborative/link-partner/', link_partner, name='link-partner'),
    path('collaborative/vote/', vote_on_trip, name='vote-trip'),
    path('collaborative/matches/', get_perfect_matches, name='perfect-matches'),

    # Feature 5: Delay Prediction & Self-Transfer
    path('delay-prediction/', predict_delay, name='predict-delay'),
    path('self-transfer-check/', check_self_transfer_insurance,
         name='self-transfer-check'),

    # User Profile
    path('profile/', get_user_profile, name='user-profile'),
    path('profile/update/', update_user_profile, name='update-profile'),
    path('nearest-airport/', nearest_airport, name='nearest-airport'),
]
