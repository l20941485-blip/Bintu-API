import json

from bintu_api import cli
from bintu_api.settings import Settings


def test_cli_check_config_outputs_summary_without_leaking_secrets(monkeypatch, capsys):
    secret_api_key = "super-secret-api-key-value"
    secret_supabase_key = "super-secret-service-role-key"
    settings = Settings(
        api_key=secret_api_key,
        rapidapi_proxy_secret="secret-proxy-value",
        mcp_api_key="secret-mcp-value",
        supabase_url="https://example.supabase.co",
        supabase_anon_key="secret-anon-key",
        supabase_service_role_key=secret_supabase_key,
        oauth_resource_url="https://bintu-api.onrender.com",
        oauth_authorization_servers="https://auth.example.com",
    )
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))

    rc = cli.main(["check-config"])
    assert rc == 0

    captured = capsys.readouterr()
    assert secret_api_key not in captured.out
    assert secret_supabase_key not in captured.out
    assert "secret-proxy-value" not in captured.out
    assert "secret-mcp-value" not in captured.out
    assert "secret-anon-key" not in captured.out

    parsed = json.loads(captured.out)
    assert parsed["has_api_key"] is True
    assert parsed["has_mcp_api_key"] is True
    assert parsed["has_rapidapi_proxy_secret"] is True
    assert parsed["has_supabase_service_role_key"] is True
    assert parsed["oauth_resource_url"] == "https://bintu-api.onrender.com"
    assert parsed["oauth_authorization_servers"] == ["https://auth.example.com"]


def test_cli_serve_invokes_uvicorn(monkeypatch):
    calls = {}

    def fake_run(app_target, host, port, reload):
        calls["app_target"] = app_target
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    rc = cli.main(["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"])
    assert rc == 0
    assert calls == {
        "app_target": "main:app",
        "host": "0.0.0.0",
        "port": 9000,
        "reload": True,
    }
