"""Verified ownership for the REST document reader.

Ownership is credential-level, not necessarily person-level.
Never derive snapshot ownership from client IP or unverified headers.
"""

import hashlib
import hmac

from fastapi import HTTPException
from starlette.requests import Request

from bintu_api.auth import has_valid_proxy_secret, verify_api_access
from bintu_api.settings import Settings


def reader_owner(request: Request, settings: Settings) -> str:
    """Authenticate and return an opaque, namespaced owner identity.

    Verified proxy traffic requires a subscriber identity. A shared direct
    API key represents one shared owner. Open development mode is not
    sufficient to access retained reader snapshots.
    """
    verify_api_access(request, settings)

    if has_valid_proxy_secret(request, settings):
        subscriber = request.headers.get("X-RapidAPI-User", "").strip()
        if (
            not subscriber
            or len(subscriber) > 256
            or not subscriber.isascii()
            or any(
                ord(character) < 33 or ord(character) > 126
                for character in subscriber
            )
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "reader_identity_required",
                    "message": (
                        "A valid gateway subscriber identity is required."
                    ),
                },
            )

        fingerprint = hashlib.sha256(
            subscriber.encode("utf-8")
        ).hexdigest()
        return f"reader:rapidapi:{fingerprint}"

    provided = request.headers.get("X-API-Key", "")
    if settings.api_key and hmac.compare_digest(
        provided.encode("utf-8"),
        settings.api_key.encode("utf-8"),
    ):
        fingerprint = hashlib.sha256(
            provided.encode("utf-8")
        ).hexdigest()
        return f"reader:apikey:{fingerprint}"

    raise HTTPException(
        status_code=401,
        detail={
            "code": "reader_auth_required",
            "message": (
                "The document reader requires a configured API key "
                "or verified gateway subscriber."
            ),
        },
        headers={"WWW-Authenticate": "ApiKey"},
    )
