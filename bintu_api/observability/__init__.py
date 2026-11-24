"""Observability and telemetry for Bintu.

This module records extraction, cache, and request events without owning business logic or external API behavior.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

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
CACHE_LOOKUPS = Counter(
    "bintu_cache_lookups_total",
    "Cache lookup outcomes for scraped content.",
    ("layer", "outcome"),
)
CACHE_LOOKUP_AGE = Histogram(
    "bintu_cache_lookup_age_seconds",
    "Age of persistent cache hits in seconds.",
    ("layer",),
    buckets=(1, 5, 15, 30, 60, 300, 900, 3600, 21600, 86400),
)
CACHE_TOKENS_SAVED = Counter(
    "bintu_cache_tokens_saved_total",
    "Estimated tokens saved by extraction and caching.",
    ("mode", "cache_layer"),
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
EXTRACTION_FAILURES = Counter(
    "bintu_extraction_failures_total",
    "Failed text extractions.",
    ("mode", "failure_code", "error_type"),
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


def log_extraction_failed(
    *,
    request_id: str | None,
    url: str,
    mode: str,
    failure_code: str,
    error_type: str,
    duration_ms: float | None = None,
    status_code: int | None = None,
) -> None:
    """Emit a structured, privacy-safe extraction-failure event.



    Raw URLs and extracted content are never logged. The target is identified
    only by its stable truncated SHA-256 hash.
    """
    EXTRACTION_FAILURES.labels(mode, failure_code, error_type).inc()

    EXTRACTION_LOGGER.warning(
        "extraction_failed request_id=%s url_hash=%s mode=%s "
        "failure_code=%s error_type=%s duration_ms=%s status_code=%s",
        request_id or "unknown",
        url_hash(url),
        mode,
        failure_code,
        error_type,
        f"{duration_ms:.2f}" if duration_ms is not None else "none",
        status_code if status_code is not None else "none",
    )


def log_cache_lookup_completed(
    *,
    request_id: str | None,
    url: str,
    cache_hit: bool,
    cache_layer: str,
    age_seconds: float | None,
) -> None:
    """Emit a privacy-safe cache lookup event.



    Raw URLs are never logged; targets are identified only by url_hash.
    """
    layer = cache_layer if cache_hit else "none"
    outcome = "hit" if cache_hit else "miss"

    CACHE_LOOKUPS.labels(layer, outcome).inc()
    if cache_hit and age_seconds is not None:
        CACHE_LOOKUP_AGE.labels(layer).observe(max(0.0, age_seconds))

    EXTRACTION_LOGGER.info(
        "cache_lookup_completed request_id=%s url_hash=%s cache_hit=%s cache_layer=%s age_seconds=%s",
        request_id or "unknown",
        url_hash(url),
        cache_hit,
        layer,
        f"{age_seconds:.2f}" if age_seconds is not None else "none",
    )


def record_cache_tokens_saved(
    *,
    mode: str,
    cache_hit: bool,
    cache_layer: str,
    approx_tokens: int,
    tokens_saved_estimate: int,
) -> None:
    """Record aggregate token savings by cache outcome."""
    layer = cache_layer if cache_hit else "none"
    CACHE_TOKENS_SAVED.labels(mode, layer).inc(max(0, tokens_saved_estimate))


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


from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock

_MAX_TRACED_REQUESTS = 512
_MAX_STAGE_EVENTS_PER_REQUEST = 64
_TRACE_LOCK = Lock()
_REQUEST_TRACE_IDS: OrderedDict[str, str] = OrderedDict()
_STAGE_TRACES_BY_REQUEST: OrderedDict[str, deque[dict[str, object]]] = OrderedDict()


@dataclass(frozen=True)
class StageTraceEvent:
    request_id: str
    trace_id: str
    stage: str
    status: str
    duration_ms: float
    cache_layer: str | None = None
    extractor_version: str | None = None
    quality_score: float | None = None
    tokens_returned: int | None = None
    timestamp_utc: str = ""


def get_or_create_trace_id(request_id: str) -> str:
    """Return a deterministic or stored trace_id correlated with request_id."""
    normalized_req = request_id or uuid.uuid4().hex
    with _TRACE_LOCK:
        existing = _REQUEST_TRACE_IDS.get(normalized_req)
        if existing:
            _REQUEST_TRACE_IDS.move_to_end(normalized_req)
            return existing
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        _REQUEST_TRACE_IDS[normalized_req] = trace_id
        _REQUEST_TRACE_IDS.move_to_end(normalized_req)
        while len(_REQUEST_TRACE_IDS) > _MAX_TRACED_REQUESTS:
            _REQUEST_TRACE_IDS.popitem(last=False)
        return trace_id


def record_stage_trace(
    *,
    request_id: str,
    stage: str,
    status: str,
    duration_ms: float,
    trace_id: str | None = None,
    cache_layer: str | None = None,
    extractor_version: str | None = None,
    quality_score: float | None = None,
    tokens_returned: int | None = None,
) -> dict[str, object]:
    """Record and log a structured per-stage observability trace event."""
    resolved_request_id = request_id or "unknown"
    resolved_trace_id = trace_id or get_or_create_trace_id(resolved_request_id)
    event = StageTraceEvent(
        request_id=resolved_request_id,
        trace_id=resolved_trace_id,
        stage=stage,
        status=status,
        duration_ms=round(max(0.0, float(duration_ms)), 3),
        cache_layer=cache_layer,
        extractor_version=extractor_version,
        quality_score=quality_score,
        tokens_returned=tokens_returned,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    payload = asdict(event)

    with _TRACE_LOCK:
        _REQUEST_TRACE_IDS[resolved_request_id] = resolved_trace_id
        _REQUEST_TRACE_IDS.move_to_end(resolved_request_id)
        while len(_REQUEST_TRACE_IDS) > _MAX_TRACED_REQUESTS:
            _REQUEST_TRACE_IDS.popitem(last=False)

        bucket = _STAGE_TRACES_BY_REQUEST.get(resolved_request_id)
        if bucket is None:
            bucket = deque(maxlen=_MAX_STAGE_EVENTS_PER_REQUEST)
            _STAGE_TRACES_BY_REQUEST[resolved_request_id] = bucket
        bucket.append(payload)
        _STAGE_TRACES_BY_REQUEST.move_to_end(resolved_request_id)
        while len(_STAGE_TRACES_BY_REQUEST) > _MAX_TRACED_REQUESTS:
            _STAGE_TRACES_BY_REQUEST.popitem(last=False)

    EXTRACTION_LOGGER.info(
        "stage_trace request_id=%s trace_id=%s stage=%s status=%s duration_ms=%.3f cache_layer=%s extractor_version=%s quality_score=%s tokens_returned=%s",
        resolved_request_id,
        resolved_trace_id,
        stage,
        status,
        event.duration_ms,
        cache_layer or "none",
        extractor_version or "none",
        f"{quality_score:.4f}" if quality_score is not None else "none",
        tokens_returned if tokens_returned is not None else "none",
    )
    return payload


def get_stage_traces(request_id: str) -> list[dict[str, object]]:
    """Return recorded stage trace events for a request_id in chronological order."""
    with _TRACE_LOCK:
        bucket = _STAGE_TRACES_BY_REQUEST.get(request_id)
        if not bucket:
            return []
        return list(bucket)
