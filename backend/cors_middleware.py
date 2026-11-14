"""Minimal CORS for /api/ so the Flutter web build (or a browser) can call the API.
Mobile apps don't need CORS. Allowed origins come from CORS_ALLOWED_ORIGINS (comma separated, or *)."""
from django.conf import settings
from django.http import HttpResponse


class ApiCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        origin = request.headers.get("Origin")
        allowed = getattr(settings, "CORS_ALLOWED_ORIGINS", [])
        if origin and ("*" in allowed or origin in allowed):
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            response["Access-Control-Max-Age"] = "86400"
        return response
