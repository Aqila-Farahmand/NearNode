from django.conf import settings
from django.utils import translation


class UserProfileLocaleMiddleware:
    """
    Use authenticated user's preferred language for request processing.
    Runs after AuthenticationMiddleware to access request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed = {code for code, _name in getattr(settings, 'LANGUAGES', [])}

    def __call__(self, request):
        if getattr(request, 'user', None) and request.user.is_authenticated:
            lang = None
            try:
                lang = getattr(request.user.profile, 'preferred_language', None)
            except Exception:
                lang = None
            if lang in self.allowed:
                translation.activate(lang)
                request.LANGUAGE_CODE = lang
        return self.get_response(request)
