import logging
import re
import time
import uuid

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


REQUEST_COUNT = Counter(
    "bintu_http_requests_total",
    "HTTP requests served by Bintu API.",
    ("method", "route", "status_code"),
)
REQUEST_ERRORS = Counter(
    "bintu_http_errors_total",
    "HTTP error responses served by Bintu API.",
    ("route", "status_code"),
)
REQUEST_DURATION = Histogram(
    "bintu_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
CACHE_HITS = Counter(
    "bintu_cache_hits_total",
    "Cache hits for scraped content.",
)
CACHE_MISSES = Counter(
    "bintu_cache_misses_total",
    "Cache misses for scraped content.",
)
logger = logging.getLogger("bintu_api.request")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if _REQUEST_ID_PATTERN.fullmatch(supplied_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        start_time = time.perf_counter()
        status_code = 500
        response: Response | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as error:
            logger.error(
                "request_failed request_id=%s error_type=%s",
                request_id,
                type(error).__name__,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "internal_error",
                        "message": "An internal error occurred while handling the request.",
                    }
                },
            )
        finally:
            elapsed = time.perf_counter() - start_time
            route = getattr(request.scope.get("route"), "path", "unmatched")
            REQUEST_COUNT.labels(request.method, route, str(status_code)).inc()
            REQUEST_DURATION.labels(request.method, route).observe(elapsed)
            if status_code >= 400:
                REQUEST_ERRORS.labels(route, str(status_code)).inc()
            logger.info(
                "request_completed request_id=%s method=%s route=%s status_code=%d duration_ms=%.2f",
                request_id,
                request.method,
                route,
                status_code,
                elapsed * 1000,
            )

        response.headers["X-Request-ID"] = request_id
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
