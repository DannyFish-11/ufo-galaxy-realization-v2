"""
Tests for gateway security hardening (PR4) and key rotation (PR12)
===================================================================

Covers:
1. Bearer token auth middleware — disabled (default) and enabled modes.
2. WebSocket token auth via query param when auth is enabled.
3. Health endpoints are always accessible (auth-exempt).
4. TURN/STUN/Tailscale metadata in /api/v1/webrtc/endpoint.
5. TLS startup log logic (unit).
6. core.auth.is_auth_enabled helper.
7. Key rotation: multiple active tokens, token expiry, token revocation.
"""

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers — build a minimal app that wires the security middleware
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    """Minimal FastAPI app with BearerAuthMiddleware and test routes."""
    from galaxy_gateway.app import BearerAuthMiddleware

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/protected")
    async def protected():
        return {"data": "secret"}

    return app


# ---------------------------------------------------------------------------
# Tests: is_auth_enabled
# ---------------------------------------------------------------------------

class TestIsAuthEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)
        from core.auth import is_auth_enabled
        assert is_auth_enabled() is False

    def test_enabled_with_true(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        from core.auth import is_auth_enabled
        assert is_auth_enabled() is True

    def test_enabled_with_1(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "1")
        from core.auth import is_auth_enabled
        assert is_auth_enabled() is True

    def test_disabled_with_false(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        from core.auth import is_auth_enabled
        assert is_auth_enabled() is False


# ---------------------------------------------------------------------------
# Tests: require_auth FastAPI dependency
# ---------------------------------------------------------------------------

class TestRequireAuth:
    def test_passes_through_when_auth_disabled(self, monkeypatch):
        """require_auth is a no-op when GALAXY_AUTH_ENABLED is false."""
        import asyncio
        monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)
        from core.auth import require_auth
        result = asyncio.get_event_loop().run_until_complete(require_auth())
        assert result["authenticated"] is True
        assert result["auth_enabled"] is False

    def test_raises_401_when_enabled_no_token(self, monkeypatch):
        """When auth is enabled, missing Authorization header returns 401."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi import Depends
        from core.auth import require_auth

        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        monkeypatch.setenv("GALAXY_API_TOKEN", "s3cr3t")

        app = FastAPI()

        @app.get("/secure")
        async def secure(auth=Depends(require_auth)):
            return {"ok": True}

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/secure")
        assert resp.status_code == 401

    def test_passes_with_valid_token(self, monkeypatch):
        """require_auth returns auth dict when Bearer token is correct."""
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from core.auth import require_auth

        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        monkeypatch.setenv("GALAXY_API_TOKEN", "s3cr3t")

        app = FastAPI()

        @app.get("/secure")
        async def secure(auth=Depends(require_auth)):
            return auth

        with TestClient(app) as c:
            resp = c.get("/secure", headers={"Authorization": "Bearer s3cr3t"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True


# ---------------------------------------------------------------------------
# Tests: BearerAuthMiddleware — auth disabled (default)
# ---------------------------------------------------------------------------

class TestMiddlewareAuthDisabled:
    """When GALAXY_AUTH_ENABLED is unset/false, all requests pass through."""

    @pytest.fixture(autouse=True)
    def _disable_auth(self, monkeypatch):
        monkeypatch.delenv("GALAXY_AUTH_ENABLED", raising=False)

    def test_protected_endpoint_passes_without_token(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/api/v1/protected")
        assert resp.status_code == 200

    def test_health_passes_without_token(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: BearerAuthMiddleware — auth enabled
# ---------------------------------------------------------------------------

class TestMiddlewareAuthEnabled:
    """When GALAXY_AUTH_ENABLED=true and GALAXY_API_TOKEN is set."""

    TOKEN = "test-gateway-token-abc"

    @pytest.fixture(autouse=True)
    def _enable_auth(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        monkeypatch.setenv("GALAXY_API_TOKEN", self.TOKEN)

    def test_health_is_exempt(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/health")
        assert resp.status_code == 200

    def test_protected_rejects_missing_token(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/api/v1/protected")
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("error") == "unauthorized"

    def test_protected_rejects_wrong_token(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": "Bearer wrong-token"},
            )
        assert resp.status_code == 401

    def test_protected_accepts_correct_token(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN}"},
            )
        assert resp.status_code == 200

    def test_protected_accepts_token_via_query_param(self):
        """WebSocket clients can pass token as ?token= query parameter."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/protected?token={self.TOKEN}")
        assert resp.status_code == 200

    def test_protected_rejects_no_token_configured(self, monkeypatch):
        """When auth is enabled but no token is configured → 401 (fail-safe)."""
        monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/api/v1/protected")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: TURN / STUN / Tailscale metadata
# ---------------------------------------------------------------------------

class TestWebRTCEndpointMetadata:
    """get_webrtc_endpoint_info returns TURN/STUN/Tailscale when configured."""

    def test_no_ice_servers_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("GALAXY_STUN_URLS", raising=False)
        monkeypatch.delenv("GALAXY_TURN_URLS", raising=False)
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "ice_servers" not in info

    def test_stun_included_when_configured(self, monkeypatch):
        monkeypatch.setenv("GALAXY_STUN_URLS", "stun:stun.l.google.com:19302")
        monkeypatch.delenv("GALAXY_TURN_URLS", raising=False)
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "ice_servers" in info
        urls = [u for entry in info["ice_servers"] for u in entry["urls"]]
        assert "stun:stun.l.google.com:19302" in urls

    def test_turn_included_with_credentials(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TURN_URLS", "turn:turn.example.com:3478")
        monkeypatch.setenv("GALAXY_TURN_USERNAME", "user1")
        monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "pass1")
        monkeypatch.delenv("GALAXY_STUN_URLS", raising=False)
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "ice_servers" in info
        turn_entries = [e for e in info["ice_servers"] if any("turn:" in u for u in e["urls"])]
        assert turn_entries
        assert turn_entries[0]["username"] == "user1"
        assert turn_entries[0]["credential"] == "pass1"

    def test_multiple_ice_servers(self, monkeypatch):
        monkeypatch.setenv("GALAXY_STUN_URLS", "stun:s1.example.com:3478,stun:s2.example.com:3478")
        monkeypatch.setenv("GALAXY_TURN_URLS", "turn:t.example.com:3478")
        monkeypatch.setenv("GALAXY_TURN_USERNAME", "u")
        monkeypatch.setenv("GALAXY_TURN_CREDENTIAL", "p")
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert len(info["ice_servers"]) == 2  # STUN entry + TURN entry

    def test_no_tailscale_when_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TAILSCALE_ENABLED", "false")
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "tailscale" not in info

    def test_tailscale_metadata_included_when_enabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TAILSCALE_ENABLED", "true")
        monkeypatch.setenv("GALAXY_TAILSCALE_HOST", "gw.example.ts.net")
        monkeypatch.setenv("GALAXY_TAILSCALE_TAG", "tag:gateway")
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "tailscale" in info
        ts = info["tailscale"]
        assert ts["enabled"] is True
        assert ts["host"] == "gw.example.ts.net"
        assert ts["tag"] == "tag:gateway"

    def test_tailscale_no_host_or_tag(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TAILSCALE_ENABLED", "1")
        monkeypatch.delenv("GALAXY_TAILSCALE_HOST", raising=False)
        monkeypatch.delenv("GALAXY_TAILSCALE_TAG", raising=False)
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        ts = info.get("tailscale", {})
        assert ts.get("enabled") is True
        assert "host" not in ts
        assert "tag" not in ts

    def test_existing_fields_always_present(self, monkeypatch):
        """Core WebRTC fields remain in the response regardless of extras."""
        monkeypatch.delenv("GALAXY_STUN_URLS", raising=False)
        monkeypatch.delenv("GALAXY_TURN_URLS", raising=False)
        monkeypatch.delenv("GALAXY_TAILSCALE_ENABLED", raising=False)
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        for key in ("node95_url", "ws_signaling_path", "gateway_ws_url", "gateway_ws_path"):
            assert key in info


# ---------------------------------------------------------------------------
# Tests: TLS startup log (unit — does not actually start uvicorn)
# ---------------------------------------------------------------------------

class TestTLSStartupLog:
    def test_tls_disabled_when_cert_missing(self, monkeypatch):
        """When TLS env vars are absent, main() calls uvicorn without ssl args."""
        monkeypatch.delenv("GALAXY_TLS_CERT", raising=False)
        monkeypatch.delenv("GALAXY_TLS_KEY", raising=False)

        import uvicorn
        import galaxy_gateway.app as gw_app

        called_with = {}

        def _fake_run(app, **kwargs):
            called_with.update(kwargs)

        original = uvicorn.run
        try:
            uvicorn.run = _fake_run
            gw_app.main()
        finally:
            uvicorn.run = original

        assert "ssl_certfile" not in called_with

    def test_tls_enabled_when_cert_and_key_set(self, monkeypatch):
        """When TLS env vars are set, main() passes ssl_certfile and ssl_keyfile."""
        monkeypatch.setenv("GALAXY_TLS_CERT", "/fake/cert.pem")
        monkeypatch.setenv("GALAXY_TLS_KEY", "/fake/key.pem")

        import uvicorn
        import galaxy_gateway.app as gw_app

        called_with = {}

        def _fake_run(app, **kwargs):
            called_with.update(kwargs)

        original = uvicorn.run
        try:
            uvicorn.run = _fake_run
            gw_app.main()
        finally:
            uvicorn.run = original

        assert called_with.get("ssl_certfile") == "/fake/cert.pem"
        assert called_with.get("ssl_keyfile") == "/fake/key.pem"

    def test_tls_disabled_when_only_cert_set(self, monkeypatch):
        """Both cert AND key must be set; missing key means TLS stays off."""
        monkeypatch.setenv("GALAXY_TLS_CERT", "/fake/cert.pem")
        monkeypatch.delenv("GALAXY_TLS_KEY", raising=False)

        import uvicorn
        import galaxy_gateway.app as gw_app

        called_with = {}

        def _fake_run(app, **kwargs):
            called_with.update(kwargs)

        original = uvicorn.run
        try:
            uvicorn.run = _fake_run
            gw_app.main()
        finally:
            uvicorn.run = original

        assert "ssl_certfile" not in called_with


# ---------------------------------------------------------------------------
# Tests: Key Rotation — core.auth helpers (PR12)
# ---------------------------------------------------------------------------

class TestGetActiveTokens:
    """Unit tests for the multi-key get_active_tokens() helper."""

    def test_single_token_returned(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-single")
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        assert get_active_tokens() == ["tok-single"]

    def test_multi_tokens_returned(self, monkeypatch):
        monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
        monkeypatch.setenv("GALAXY_API_TOKENS", "tok-a,tok-b,tok-c")
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        assert get_active_tokens() == ["tok-a", "tok-b", "tok-c"]

    def test_single_and_multi_tokens_combined(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-legacy")
        monkeypatch.setenv("GALAXY_API_TOKENS", "tok-new")
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        tokens = get_active_tokens()
        assert "tok-legacy" in tokens
        assert "tok-new" in tokens

    def test_revoked_token_excluded(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-good")
        monkeypatch.setenv("GALAXY_API_TOKENS", "tok-bad")
        monkeypatch.setenv("GALAXY_REVOKED_TOKENS", "tok-bad")
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        tokens = get_active_tokens()
        assert "tok-good" in tokens
        assert "tok-bad" not in tokens

    def test_expired_single_token_excluded(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-old")
        monkeypatch.setenv("GALAXY_API_TOKEN_EXPIRY", "2020-01-01T00:00:00Z")
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        from core.auth import get_active_tokens
        tokens = get_active_tokens()
        assert "tok-old" not in tokens
        assert tokens == []

    def test_future_expiry_token_included(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-future")
        monkeypatch.setenv("GALAXY_API_TOKEN_EXPIRY", "2099-01-01T00:00:00Z")
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        from core.auth import get_active_tokens
        assert "tok-future" in get_active_tokens()

    def test_duplicate_tokens_deduplicated(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-dup")
        monkeypatch.setenv("GALAXY_API_TOKENS", "tok-dup")
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        tokens = get_active_tokens()
        assert tokens.count("tok-dup") == 1

    def test_empty_when_no_tokens_set(self, monkeypatch):
        monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)
        from core.auth import get_active_tokens
        assert get_active_tokens() == []

    def test_invalid_expiry_treated_as_not_expired(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN", "tok-ok")
        monkeypatch.setenv("GALAXY_API_TOKEN_EXPIRY", "not-a-date")
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        from core.auth import get_active_tokens
        # Unparseable expiry is ignored; token remains active
        assert "tok-ok" in get_active_tokens()


class TestMiddlewareKeyRotation:
    """BearerAuthMiddleware accepts any token in the active set."""

    TOKEN_OLD = "tok-old-key"
    TOKEN_NEW = "tok-new-key"

    @pytest.fixture(autouse=True)
    def _enable_auth(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
        # Both old and new token active during overlap window
        monkeypatch.setenv("GALAXY_API_TOKEN", self.TOKEN_OLD)
        monkeypatch.setenv("GALAXY_API_TOKENS", self.TOKEN_NEW)
        monkeypatch.delenv("GALAXY_REVOKED_TOKENS", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKEN_EXPIRY", raising=False)

    def test_old_token_accepted_during_overlap(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN_OLD}"},
            )
        assert resp.status_code == 200

    def test_new_token_accepted_during_overlap(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN_NEW}"},
            )
        assert resp.status_code == 200

    def test_revoked_token_rejected(self, monkeypatch):
        monkeypatch.setenv("GALAXY_REVOKED_TOKENS", self.TOKEN_OLD)
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN_OLD}"},
            )
        assert resp.status_code == 401

    def test_unknown_token_still_rejected(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": "Bearer totally-unknown"},
            )
        assert resp.status_code == 401

    def test_expired_primary_token_rejected(self, monkeypatch):
        monkeypatch.setenv("GALAXY_API_TOKEN_EXPIRY", "2020-01-01T00:00:00Z")
        # Only the expired primary token is configured; GALAXY_API_TOKENS is cleared
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN_OLD}"},
            )
        assert resp.status_code == 401

    def test_new_token_valid_after_old_token_expires(self, monkeypatch):
        """After old key expires, the new key in GALAXY_API_TOKENS still works."""
        monkeypatch.setenv("GALAXY_API_TOKEN_EXPIRY", "2020-01-01T00:00:00Z")
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/protected",
                headers={"Authorization": f"Bearer {self.TOKEN_NEW}"},
            )
        assert resp.status_code == 200
