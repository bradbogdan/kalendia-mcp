"""Phase 2 (remote/HTTP multi-user) tests: the kld_ token verifier and per-request token resolution."""

import httpx
import pytest
import respx
from mcp.server.auth.provider import AccessToken

from kalendia_mcp import server
from kalendia_mcp.auth import KalendiaTokenVerifier

BASE = "https://api.test.kalendia"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("KALENDIA_API_URL", BASE)


@respx.mock
async def test_verifier_accepts_valid_kld_token() -> None:
    route = respx.get(f"{BASE}/billing/me").mock(return_value=httpx.Response(200, json={"plan": "pro"}))
    access = await KalendiaTokenVerifier().verify_token("kld_good")
    assert isinstance(access, AccessToken)
    assert access.token == "kld_good"
    assert route.calls.last.request.headers["Authorization"] == "Bearer kld_good"


@respx.mock
async def test_verifier_rejects_invalid_token() -> None:
    respx.get(f"{BASE}/billing/me").mock(return_value=httpx.Response(401, json={"detail": "x"}))
    assert await KalendiaTokenVerifier().verify_token("kld_bad") is None


async def test_verifier_rejects_non_kld_without_network() -> None:
    # No respx mock is active here; a network call would raise. The verifier must short-circuit a
    # non-kld_ bearer (e.g. a JWT) before making any request.
    assert await KalendiaTokenVerifier().verify_token("eyJ.header.sig") is None


@respx.mock
async def test_verifier_caches_valid_result() -> None:
    route = respx.get(f"{BASE}/billing/me").mock(return_value=httpx.Response(200, json={}))
    verifier = KalendiaTokenVerifier()
    await verifier.verify_token("kld_x")
    await verifier.verify_token("kld_x")
    assert route.call_count == 1  # second call served from the 60s cache


@respx.mock
async def test_verifier_does_not_cache_failures() -> None:
    route = respx.get(f"{BASE}/billing/me").mock(return_value=httpx.Response(401, json={}))
    verifier = KalendiaTokenVerifier()
    await verifier.verify_token("kld_x")
    await verifier.verify_token("kld_x")
    assert route.call_count == 2  # a revoked/invalid token is re-checked every time


@respx.mock
async def test_per_request_token_reaches_the_api_in_http_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # In HTTP mode the auth context carries the caller's token; the bearer that reaches the API on a
    # tool call must be that per-request token (so one instance serves many users).
    monkeypatch.setattr(
        server,
        "get_access_token",
        lambda: AccessToken(token="kld_per_request", client_id="x", scopes=[]),
    )
    route = respx.get(f"{BASE}/sync/rules").mock(return_value=httpx.Response(200, json=[]))
    await server.list_sync_rules()
    assert route.calls.last.request.headers["Authorization"] == "Bearer kld_per_request"


@respx.mock
async def test_env_token_reaches_the_api_in_stdio_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # In stdio mode there is no auth context; the bearer must come from KALENDIA_TOKEN.
    monkeypatch.setattr(server, "get_access_token", lambda: None)
    monkeypatch.setenv("KALENDIA_TOKEN", "kld_env")
    route = respx.get(f"{BASE}/sync/rules").mock(return_value=httpx.Response(200, json=[]))
    await server.list_sync_rules()
    assert route.calls.last.request.headers["Authorization"] == "Bearer kld_env"
