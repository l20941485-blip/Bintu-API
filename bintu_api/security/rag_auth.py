"""Single-auth + server-controlled scoped JWT helper for non-mobile RAG routes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any, Literal

from fastapi import HTTPException, Request

from bintu_api.security.auth import _secret_matches, verify_api_access
from bintu_api.settings import Settings

RagScope = Literal["rag:tenant", "rag:docs"]
_RAG_JWT_ISSUER = "bintu-api-rag"
_RAG_JWT_AUDIENCE = "bintu-rag-service"
_RAG_JWT_TTL_SECONDS = 300


@dataclass(frozen=True)
class RagPrincipal:
    owner_identity: str | None
    scope: RagScope
    token_jti: str


def _parse_key_owner_map(raw_json: str) -> dict[str, str]:
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    mapping: dict[str, str] = {}
    for key, owner in parsed.items():
        if isinstance(key, str) and isinstance(owner, str):
            clean_key = key.strip()
            clean_owner = owner.strip()
            if clean_key and clean_owner:
                mapping[clean_key] = clean_owner
    return mapping


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _signing_key(settings: Settings) -> bytes:
    configured = (
        getattr(settings, "rag_jwt_secret", "")
        or getattr(settings, "api_key", "")
        or getattr(settings, "rapidapi_proxy_secret", "")
    )
    if configured:
        return hashlib.sha256(f"bintu-rag-jwt:{configured}".encode("utf-8")).digest()
    return hashlib.sha256(b"bintu-rag-ephemeral-local-key").digest()


def mint_server_rag_jwt(
    *,
    settings: Settings,
    owner_identity: str | None,
    scope: RagScope,
    ttl_seconds: int = _RAG_JWT_TTL_SECONDS,
) -> str:
    """Mint a short-lived, server-signed HS256 JWT bound to owner_identity and scope."""
    now = datetime.now(timezone.utc)
    iat = int(now.timestamp())
    exp = int((now + timedelta(seconds=max(ttl_seconds, 30))).timestamp())
    jti_seed = f"{owner_identity or 'docs'}:{scope}:{iat}:{exp}".encode("utf-8")
    jti = hashlib.sha256(jti_seed).hexdigest()[:24]

    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "iss": _RAG_JWT_ISSUER,
        "aud": _RAG_JWT_AUDIENCE,
        "sub": owner_identity or "shared:docs",
        "owner_identity": owner_identity,
        "scope": scope,
        "jti": jti,
        "iat": iat,
        "exp": exp,
    }

    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(_signing_key(settings), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def verify_server_rag_jwt(token: str, *, settings: Settings, required_scope: RagScope) -> RagPrincipal:
    """Verify signature, expiration, issuer, audience, and scope of a server-minted JWT."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Malformed internal RAG token."},
        )

    encoded_header, encoded_payload, encoded_sig = parts
    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        provided_sig = _b64url_decode(encoded_sig)
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Unable to decode internal RAG token."},
        ) from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Unsupported internal RAG token header."},
        )

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_sig = hmac.new(_signing_key(settings), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Invalid internal RAG token signature."},
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Invalid internal RAG token claims."},
        )

    now_ts = int(datetime.now(timezone.utc).timestamp())
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(exp, (int, float)) or not isinstance(iat, (int, float)):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Missing required timestamp claims."},
        )
    if exp <= now_ts or iat > now_ts + 5:
        raise HTTPException(
            status_code=401,
            detail={"code": "expired_rag_token", "message": "Internal RAG token expired or not yet valid."},
        )

    if payload.get("iss") != _RAG_JWT_ISSUER or payload.get("aud") != _RAG_JWT_AUDIENCE:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Invalid internal RAG token issuer or audience."},
        )

    scope = payload.get("scope")
    if scope != required_scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_rag_scope", "message": "Token scope is not permitted for this route."},
        )

    raw_owner = payload.get("owner_identity")
    owner_identity = raw_owner.strip() if isinstance(raw_owner, str) and raw_owner.strip() else None
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_rag_token", "message": "Missing token identifier."},
        )

    return RagPrincipal(owner_identity=owner_identity, scope=scope, token_jti=jti)


def authenticate_non_mobile_rag(request: Request, settings: Settings, *, required_scope: RagScope) -> RagPrincipal:
    """Authenticate caller once via X-API-Key/gateway and authorize via server-controlled JWT."""
    verify_api_access(request, settings)

    provided_key = request.headers.get("X-API-Key", "").strip()
    key_owners = _parse_key_owner_map(getattr(settings, "rag_api_key_owners_json", ""))

    resolved_owner: str | None = None
    for configured_key, owner_id in key_owners.items():
        if _secret_matches(provided_key, configured_key):
            resolved_owner = owner_id
            break

    if resolved_owner is None and provided_key and _secret_matches(provided_key, settings.api_key):
        default_owner = getattr(settings, "rag_default_owner", "").strip()
        resolved_owner = default_owner or None

    token = mint_server_rag_jwt(
        settings=settings,
        owner_identity=resolved_owner if required_scope == "rag:tenant" else None,
        scope=required_scope,
    )
    return verify_server_rag_jwt(token, settings=settings, required_scope=required_scope)
