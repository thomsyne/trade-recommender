from urllib.parse import urlsplit

from django.conf import settings


class TrustedPortalNullOriginMiddleware:
    """Normalize an opaque origin only for the exact configured HTTPS portal host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("HTTP_ORIGIN") == "null" and _is_trusted_portal_request(request):
            request.META["HTTP_ORIGIN"] = settings.PUBLIC_URL
        return self.get_response(request)


def _is_trusted_portal_request(request):
    if not settings.PUBLIC_URL:
        return False
    portal = urlsplit(settings.PUBLIC_URL)
    return portal.scheme == "https" and request.get_host() == portal.netloc and request.is_secure()
