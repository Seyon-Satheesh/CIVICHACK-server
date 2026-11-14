import logging
import traceback

logger = logging.getLogger("civicspeak.errors")


class ProcessExceptionMiddleware:
    """Logs any unhandled exception with its full traceback so it shows up in Coolify's logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        logger.error("Unhandled error on %s %s\n%s", request.method, request.path, traceback.format_exc())
        return None  # let Django build the normal error response
