import hashlib
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
    ("layer",),
)
CACHE_MISSES = Counter(
    "bintu_cache_misses_total",
    "Cache misses for scraped content.",
)
EXTRACTIONS = Counter(
    "bintu_extractions_total",
    "Completed text extractions.",
    ("mode", "cache_layer", "outcome"),
)
EXTRACTED_TOKENS = Counter(
    "bintu_extracted_approx_tokens_total",
    "Approximate tokens delivered by completed extractions.",
    ("mode", "cache_layer"),
)
TOKENS_SAVED = Counter(
    "bintu_tokens_saved_estimate_total",
    "Estimated tokens saved relative to the fetched HTML baseline.",
    ("mode", "cache_layer"),
)
UPSTREAM_ERRORS = Counter(
    "bintu_upstream_errors_total",
    "Upstream fetch or extraction failures.",
    ("error_type",),
)
TOKEN_METERING_FAILURES = Counter(
    "bintu_token_metering_failures_total",
    "Failures while recording token usage.",
)


logger = logging.getLogger("bintu_api.request")
EXTRACTION_LOGGER = logging.getLogger("bintu_api.extraction")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")




def url_hash(url: str) -> str:
    """Return a stable, privacy-safe hash for a target URL.

    Raw URLs are never logged: they may contain sensitive paths, query
    parameters, or identifiers. A truncated SHA-256 hash is enough to
    correlate repeated extraction attempts without exposing the target.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]




def log_extraction_completed(
    *,
    request_id: str | None,
    url: str,
    mode: str,
    cache_hit: bool,
    cache_layer: str,
    approx_tokens: int,
    html_tokens: int,
    tokens_saved_estimate: int,
    truncated: bool,
    limiting_factor: str,
) -> None:
    """Emit a structured, privacy-safe extraction-completion event."""
    layer = cache_layer if cache_hit else "none"
    outcome = "truncated" if truncated else "complete"

    EXTRACTIONS.labels(mode, layer, outcome).inc()
    EXTRACTED_TOKENS.labels(mode, layer).inc(max(0, approx_tokens))
    TOKENS_SAVED.labels(mode, layer).inc(max(0, tokens_saved_estimate))

    EXTRACTION_LOGGER.info(
        "extraction_completed request_id=%s url_hash=%s mode=%s "
        "cache_hit=%s cache_layer=%s approx_tokens=%d html_tokens=%d "
        "tokens_saved_estimate=%d truncated=%s limiting_factor=%s",
        request_id or "unknown",
        url_hash(url),
        mode,
        cache_hit,
        layer,
        max(0, approx_tokens),
        max(0, html_tokens),
        max(0, tokens_saved_estimate),
        truncated,
        limiting_factor,
    )




def log_cache_event(
    *,
    event: str,
    url: str,
    request_id: str | None = None,
    layer: str = "none",
) -> None:
    """Emit a privacy-safe cache lifecycle event.

    Valid events: cache_hit, cache_miss, persistent_cache_write.
    """
    if event == "cache_hit":
        CACHE_HITS.labels(layer).inc()
    elif event == "cache_miss":
        CACHE_MISSES.inc()

    EXTRACTION_LOGGER.info(
        "%s request_id=%s url_hash=%s cache_layer=%s",
        event,
        request_id or "unknown",
        url_hash(url),
        layer,
    )




def log_upstream_error(
    *,
    error_type: str,
    url: str,
    request_id: str | None = None,
    status_code: int | None = None,
) -> None:
    """Emit a privacy-safe upstream failure event."""
    UPSTREAM_ERRORS.labels(error_type).inc()

    EXTRACTION_LOGGER.warning(
        "upstream_error request_id=%s url_hash=%s error_type=%s status_code=%s",
        request_id or "unknown",
        url_hash(url),
        error_type,
        status_code if status_code is not None else "none",
    )




def log_token_metering_failure(error: Exception) -> None:
    """Emit a privacy-safe token-metering failure event."""
    TOKEN_METERING_FAILURES.inc()
    EXTRACTION_LOGGER.warning(
        "token_metering_failed error_type=%s",
        type(error).__name__,
    )




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
            logger.exception(
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