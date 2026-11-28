from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bintu_api.api.discovery import router as discovery_router
from bintu_api.security.auth import verify_supabase_user
from bintu_api.settings import Settings


def _build_test_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.include_router(discovery_router)

    @app.get("/protected-check")
    def protected_check(request: Request):
        return {"user": verify_supabase_user(request, app.state.settings)}

    return app


def test_oauth_protected_resource_defaults_and_supabase_fallback():
    settings = Settings(
        api_key="test-api-key",
        rapidapi_proxy_secret="",
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon-key",
    )
    app = _build_test_app(settings)
    client = TestClient(app)

    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "http://testserver"
    assert payload["authorization_servers"] == ["https://example.supabase.co/auth/v1"]
    assert payload["bearer_methods_supported"] == ["header"]
    assert payload["resource_documentation"] == "http://testserver/llms.txt"


def test_oauth_protected_resource_explicit_config():
    settings = Settings(
        api_key="test-api-key",
        rapidapi_proxy_secret="",
        oauth_resource_url="https://bintu-api.onrender.com",
        oauth_authorization_servers="https://auth.example.com, https://issuer2.example.com",
    )
    app = _build_test_app(settings)
    client = TestClient(app)

    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "https://bintu-api.onrender.com"
    assert payload["authorization_servers"] == [
        "https://auth.example.com",
        "https://issuer2.example.com",
    ]
    assert payload["resource_documentation"] == "https://bintu-api.onrender.com/llms.txt"


def test_bearer_401_challenge_includes_resource_metadata():
    settings = Settings(
        api_key="test-api-key",
        rapidapi_proxy_secret="",
        oauth_resource_url="https://bintu-api.onrender.com",
    )
    app = _build_test_app(settings)
    client = TestClient(app)

    response = client.get("/protected-check")
    assert response.status_code == 401
    challenge = response.headers.get("www-authenticate", "")
    assert 'Bearer resource_metadata="https://bintu-api.onrender.com/.well-known/oauth-protected-resource"' in challenge
