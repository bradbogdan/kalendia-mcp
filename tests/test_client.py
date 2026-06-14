import httpx
import pytest
import respx

from kalendia_mcp.client import KalendiaAPIError, KalendiaClient

BASE = "https://api.test.kalendia"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("KALENDIA_API_URL", BASE)
    monkeypatch.setenv("KALENDIA_TOKEN", "kld_test")


@respx.mock
async def test_get_connections_sends_bearer_and_parses() -> None:
    route = respx.get(f"{BASE}/connections").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "provider": "google"}])
    )
    data = await KalendiaClient().get_connections()
    assert data[0]["id"] == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer kld_test"


@respx.mock
async def test_get_events_sends_window_params() -> None:
    route = respx.get(f"{BASE}/connections/4/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    await KalendiaClient().get_events(4, "primary", "2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z")
    params = route.calls.last.request.url.params
    assert params["from"] == "2026-06-15T00:00:00Z"
    assert params["to"] == "2026-06-16T00:00:00Z"


@respx.mock
async def test_401_raises_token_rejected() -> None:
    respx.get(f"{BASE}/sync/rules").mock(return_value=httpx.Response(401, json={"detail": "x"}))
    with pytest.raises(KalendiaAPIError) as exc:
        await KalendiaClient().get_sync_rules()
    assert exc.value.status_code == 401
    assert "token rejected" in exc.value.detail


@respx.mock
async def test_4xx_surfaces_detail() -> None:
    respx.post(f"{BASE}/sync/rules").mock(
        return_value=httpx.Response(422, json={"detail": "target calendar is read-only"})
    )
    with pytest.raises(KalendiaAPIError) as exc:
        await KalendiaClient().create_sync_rule(1, 2, "busy_only", "", True)
    assert exc.value.status_code == 422
    assert "read-only" in exc.value.detail


@respx.mock
async def test_delete_204_returns_none() -> None:
    respx.delete(f"{BASE}/sync/rules/5").mock(return_value=httpx.Response(204))
    assert await KalendiaClient().delete_sync_rule(5) is None


async def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KALENDIA_TOKEN", raising=False)
    with pytest.raises(KalendiaAPIError) as exc:
        await KalendiaClient().get_connections()
    assert "KALENDIA_TOKEN" in exc.value.detail
