"""REST document reading; registered separately from legacy scrape routes."""

import asyncio
import hashlib
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import BaseModel, Field, StrictInt

from bintu_api import routes as scrape_routes
from bintu_api.auth import api_key_scheme, has_valid_proxy_secret
from bintu_api.database import DATABASE_TIMEOUT_SECONDS, increment_developer_usage
from bintu_api.reader_auth import reader_owner
from bintu_api.reader_extraction import (
    ReaderDocumentEmpty,
    ReaderDocumentTooLarge,
    snapshot_from_document,
)
from bintu_api.reader_store import SnapshotUnavailable, StoredPage
from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
)

logger = logging.getLogger("bintu_api.reader")
router = APIRouter(prefix="/api/v1/reader", tags=["Reader"])


class ReadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8192)
    max_tokens: StrictInt = Field(default=1000, ge=1, le=6000)
    include_nav: bool = False
    include_header: bool = False
    include_footer: bool = False


class ContinueRequest(BaseModel):
    cursor: str = Field(min_length=1, max_length=256)
    max_tokens: StrictInt = Field(default=1000, ge=1, le=6000)


class ReaderResponse(BaseModel):
    text: str
    start_offset: int
    end_offset: int
    has_more: bool
    next_cursor: str | None
    approx_tokens: int
    token_method: str
    boundary_split: bool
    budget_scope: str = "page_text_only"


def _response(result: StoredPage) -> ReaderResponse:
    fields = asdict(result.page)
    fields.pop("next_offset")
    return ReaderResponse(**fields, next_cursor=result.next_cursor)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
    )


async def _authorize(request: Request) -> str:
    owner = reader_owner(request, request.app.state.settings)
    await asyncio.to_thread(request.app.state.rate_limiter.check, owner)
    return owner


async def _record_usage(request: Request) -> None:
    settings = request.app.state.settings
    client = getattr(request.app.state, "supabase_client", None)
    if client is None or not has_valid_proxy_secret(request, settings):
        return

    subscriber = request.headers.get("X-RapidAPI-User", "").strip()
    try:
        await asyncio.wait_for(
            increment_developer_usage(client, subscriber),
            timeout=DATABASE_TIMEOUT_SECONDS,
        )
    except Exception as error:
        logger.warning(
            "reader_usage_increment_failed error_type=%s",
            type(error).__name__,
        )


async def _fetch_snapshot(request: Request, payload: ReadRequest):
    settings = request.app.state.settings
    target_id = hashlib.sha256(payload.url.encode("utf-8")).hexdigest()[:12]

    try:
        await scrape_routes._enforce_robots(
            payload.url, settings, target_id
        )
        document = await asyncio.to_thread(
            scrape_routes.fetch_html_document,
            payload.url,
            settings,
        )
        return await asyncio.to_thread(
            snapshot_from_document,
            document,
            requested_url=payload.url,
            include_nav=payload.include_nav,
            include_header=payload.include_header,
            include_footer=payload.include_footer,
        )
    except HTTPException:
        raise
    except TargetURLRejected as error:
        raise _error(
            400, "invalid_or_unsafe_url",
            "URL must be an allowed public HTTP or HTTPS address.",
        ) from error
    except UnsupportedMediaType as error:
        raise _error(
            415, "unsupported_media_type",
            "Only HTML and XHTML pages are supported.",
        ) from error
    except UnsupportedContentEncoding as error:
        raise _error(
            502, "unsupported_content_encoding",
            "The target returned invalid or unsupported compression.",
        ) from error
    except PayloadTooLarge as error:
        raise _error(
            413, "payload_too_large",
            "The page exceeds the configured upstream size limit.",
        ) from error
    except ReaderDocumentTooLarge as error:
        raise _error(
            413, "reader_document_too_large",
            "Extracted text exceeds the reader retention limit.",
        ) from error
    except ReaderDocumentEmpty as error:
        raise _error(
            422, "reader_document_empty",
            "No readable text was extracted.",
        ) from error
    except UpstreamHTTPError as error:
        denied = error.status_code in (401, 402, 403, 429)
        raise _error(
            502,
            "upstream_access_denied" if denied else "upstream_http_error",
            f"The target returned HTTP {error.status_code}.",
        ) from error
    except TooManyRedirects as error:
        raise _error(
            502, "too_many_redirects",
            "The target exceeded the redirect limit.",
        ) from error
    except TimeoutError as error:
        raise _error(
            504, "upstream_timeout",
            "The target did not respond in time.",
        ) from error
    except OSError as error:
        raise _error(
            502, "upstream_connection_error",
            "Could not connect to the target.",
        ) from error
    except Exception as error:
        logger.error(
            "reader_extraction_failed error_type=%s",
            type(error).__name__,
        )
        raise _error(
            500, "internal_error",
            "An internal extraction error occurred.",
        ) from error


@router.post(
    "/read",
    response_model=ReaderResponse,
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def read_document(request: Request, payload: ReadRequest):
    owner = await _authorize(request)
    snapshot = await _fetch_snapshot(request, payload)
    result = request.app.state.reader_store.create(
        snapshot,
        owner=owner,
        max_tokens=payload.max_tokens,
    )
    response = _response(result)
    await _record_usage(request)
    return response


@router.post(
    "/continue",
    response_model=ReaderResponse,
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def continue_document(request: Request, payload: ContinueRequest):
    owner = await _authorize(request)
    try:
        result = request.app.state.reader_store.read(
            payload.cursor,
            owner=owner,
            max_tokens=payload.max_tokens,
        )
    except SnapshotUnavailable as error:
        raise _error(
            404, "reader_snapshot_unavailable",
            "Continuation is unavailable. Start a new read.",
        ) from error

    response = _response(result)
    await _record_usage(request)
    return response
