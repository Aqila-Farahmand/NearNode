from django.urls import path
from django.views.generic import TemplateView
from . import views

urlpatterns = [
    path('', TemplateView.as_view(template_name='core/index.html'), name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/delete/', views.delete_account, name='delete_account'),
    path('api/save-trip/', views.save_trip, name='save_trip'),
    path('api/unsave-trip/', views.unsave_trip, name='unsave_trip'),
]
