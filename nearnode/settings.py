"""
Django settings for nearnode project.
"""

from pathlib import Path
from decouple import config
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config(
    'SECRET_KEY', default='django-insecure-dev-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1',
                       cast=lambda v: [s.strip() for s in v.split(',')])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'rest_framework',
    'corsheaders',
    'django_extensions',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'core',
    'api',
]

SITE_ID = 1

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.UserProfileLocaleMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ROOT_URLCONF = 'nearnode.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'nearnode.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', 'English'),
    ('fr', 'French'),
    ('de', 'German'),
    ('lb', 'Luxembourgish'),
    ('fa', 'Farsi'),
    ('es', 'Spanish'),
    ('it', 'Italian'),
    ('pt', 'Portuguese'),
    ('nl', 'Dutch'),
    ('ar', 'Arabic'),
    ('zh-hans', 'Chinese (Simplified)'),
    ('ja', 'Japanese'),
    ('ko', 'Korean'),
    ('hi', 'Hindi'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# CORS settings
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

CORS_ALLOW_CREDENTIALS = True

# Celery Configuration (for async tasks)
CELERY_BROKER_URL = config(
    'CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config(
    'CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')

# API Keys (set these in .env file)
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
# You'll need to integrate with a flight API
FLIGHT_API_KEY = config('FLIGHT_API_KEY', default='')
WEATHER_API_KEY = config('WEATHER_API_KEY', default='')  # For weather data
GROUND_PROVIDER = config('GROUND_PROVIDER', default='navitia')
GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')
NAVITIA_TOKEN = config('NAVITIA_TOKEN', default='')
NAVITIA_REGION = config('NAVITIA_REGION', default='fr-idf')
NAVITIA_BASE_URL = config('NAVITIA_BASE_URL', default='https://api.navitia.io/v1')
GOOGLE_ROUTES_URL = config(
    'GOOGLE_ROUTES_URL',
    default='https://routes.googleapis.com/directions/v2:computeRoutes'
)
AMADEUS_BASE_URL = config('AMADEUS_BASE_URL', default='https://test.api.amadeus.com')
AMADEUS_TOKEN_PATH = config('AMADEUS_TOKEN_PATH', default='/v1/security/oauth2/token')
AMADEUS_FLIGHT_OFFERS_PATH = config('AMADEUS_FLIGHT_OFFERS_PATH', default='/v2/shopping/flight-offers')
OPENWEATHER_BASE_URL = config('OPENWEATHER_BASE_URL', default='https://api.openweathermap.org/data/2.5')

# AI Search LLM. Set in .env: AI_SEARCH_LLM_BACKEND=ollama, OLLAMA_BASE_URL, AI_SEARCH_OLLAMA_MODEL.
AI_SEARCH_LLM_BACKEND = config('AI_SEARCH_LLM_BACKEND', default='').strip().lower() or None
GROQ_API_KEY = config('GROQ_API_KEY', default='')
OLLAMA_BASE_URL = config('OLLAMA_BASE_URL', default='')
AI_SEARCH_OPENAI_MODEL = config('AI_SEARCH_OPENAI_MODEL', default='')
AI_SEARCH_GROQ_MODEL = config('AI_SEARCH_GROQ_MODEL', default='')
AI_SEARCH_OLLAMA_MODEL = config('AI_SEARCH_OLLAMA_MODEL', default='')

# Authentication settings
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Django Allauth settings
# New settings (replacing deprecated ones)
ACCOUNT_LOGIN_METHODS = {'username'}  # Replaces ACCOUNT_AUTHENTICATION_METHOD
# Replaces ACCOUNT_EMAIL_REQUIRED and ACCOUNT_USERNAME_REQUIRED
ACCOUNT_SIGNUP_FIELDS = ['username*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = False

# Google OAuth Configuration
# Note: Credentials should be configured in Django Admin at /admin/socialaccount/socialapp/
# The .env file values are optional and can be used as reference
GOOGLE_OAUTH2_CLIENT_ID = config('GOOGLE_OAUTH2_CLIENT_ID', default='')
GOOGLE_OAUTH2_CLIENT_SECRET = config('GOOGLE_OAUTH2_CLIENT_SECRET', default='')

# Configure Google provider settings (credentials come from Django Admin)
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
        # Do NOT set 'APP' here - credentials must be configured in Django Admin
        # Go to /admin/socialaccount/socialapp/ and add a Social Application
    }
}
