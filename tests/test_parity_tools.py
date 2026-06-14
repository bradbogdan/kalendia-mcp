"""Tests for the parity tools (connections/calendars management, scheduling-page CRUD, billing)."""

import json

import httpx
import pytest
import respx

from kalendia_mcp import server

BASE = "https://api.test.kalendia"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("KALENDIA_API_URL", BASE)
    monkeypatch.setenv("KALENDIA_TOKEN", "kld_test")


@respx.mock
async def test_connect_icloud_posts_credentials() -> None:
    route = respx.post(f"{BASE}/connections/icloud").mock(
        return_value=httpx.Response(201, json={"id": 9, "provider": "icloud"})
    )
    out = await server.connect_icloud("me@icloud.com", "abcd-efgh-ijkl-mnop")
    assert out["id"] == 9
    body = json.loads(route.calls.last.request.content)
    assert body == {"apple_id": "me@icloud.com", "app_specific_password": "abcd-efgh-ijkl-mnop"}


@respx.mock
async def test_connect_ics_posts_feed_url() -> None:
    route = respx.post(f"{BASE}/connections/ics").mock(
        return_value=httpx.Response(201, json={"id": 10, "provider": "ics"})
    )
    await server.connect_ics("https://example.com/cal.ics")
    assert json.loads(route.calls.last.request.content) == {"feed_url": "https://example.com/cal.ics"}


@respx.mock
async def test_rename_calendar_patches_custom_name() -> None:
    route = respx.patch(f"{BASE}/calendars/11").mock(
        return_value=httpx.Response(200, json={"id": 11, "custom_name": "Work"})
    )
    await server.rename_calendar(11, "Work")
    assert route.calls.last.request.method == "PATCH"
    assert json.loads(route.calls.last.request.content) == {"custom_name": "Work"}


@respx.mock
async def test_rename_calendar_clears_with_null() -> None:
    respx.patch(f"{BASE}/calendars/11").mock(return_value=httpx.Response(200, json={"id": 11}))
    await server.rename_calendar(11)  # custom_name defaults to None -> clears the override


async def test_set_active_calendars_rejects_empty_list() -> None:
    # Empty list would disconnect the whole account on the backend; the tool guards against it.
    with pytest.raises(ValueError):
        await server.set_active_calendars(3, [])


@respx.mock
async def test_set_active_calendars_puts_selection() -> None:
    route = respx.put(f"{BASE}/connections/3/calendars/selection").mock(
        return_value=httpx.Response(200, json={"connection_id": 3, "disconnected": False})
    )
    await server.set_active_calendars(3, [11, 12])
    assert json.loads(route.calls.last.request.content) == {"active_calendar_ids": [11, 12]}


@respx.mock
async def test_disconnect_connection_deletes() -> None:
    respx.delete(f"{BASE}/connections/3").mock(
        return_value=httpx.Response(200, json={"connection_id": 3, "disconnected": True})
    )
    out = await server.disconnect_connection(3)
    assert out["disconnected"] is True


@respx.mock
async def test_create_scheduling_page_builds_full_payload() -> None:
    route = respx.post(f"{BASE}/scheduling-pages").mock(
        return_value=httpx.Response(201, json={"id": 7, "slug": "intro"})
    )
    window = {"timezone": "Europe/Bucharest", "weekly": {"mon": [["09:00", "17:00"]]}}
    out = await server.create_scheduling_page(
        slug="intro",
        title="Intro call",
        duration_minutes=30,
        availability_window=window,
        source_calendar_ids=[1, 2],
        target_calendar_id=2,
        video_provider="google_meet",
    )
    assert out["id"] == 7
    body = json.loads(route.calls.last.request.content)
    assert body["slug"] == "intro"
    assert body["availability_window"] == window
    assert body["source_calendar_ids"] == [1, 2]
    assert body["target_calendar_id"] == 2
    assert body["video_provider"] == "google_meet"
    assert body["max_horizon_days"] == 60  # default carried through


async def test_create_scheduling_page_rejects_bad_video_provider() -> None:
    with pytest.raises(ValueError):
        await server.create_scheduling_page(
            slug="x",
            title="x",
            duration_minutes=30,
            availability_window={"timezone": "UTC", "weekly": {}},
            source_calendar_ids=[1],
            target_calendar_id=1,
            video_provider="skype",
        )


@respx.mock
async def test_update_scheduling_page_full_replace_includes_is_active() -> None:
    route = respx.put(f"{BASE}/scheduling-pages/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "is_active": False})
    )
    await server.update_scheduling_page(
        page_id=7,
        slug="intro",
        title="Intro",
        duration_minutes=45,
        availability_window={"timezone": "UTC", "weekly": {}},
        source_calendar_ids=[1],
        target_calendar_id=1,
        is_active=False,
    )
    body = json.loads(route.calls.last.request.content)
    assert body["is_active"] is False
    assert body["duration_minutes"] == 45


@respx.mock
async def test_delete_scheduling_page_returns_marker() -> None:
    respx.delete(f"{BASE}/scheduling-pages/7").mock(return_value=httpx.Response(204))
    assert await server.delete_scheduling_page(7) == {"deleted": True, "page_id": 7}


@respx.mock
async def test_get_availability_window_params() -> None:
    route = respx.get(f"{BASE}/scheduling-pages/intro/availability").mock(
        return_value=httpx.Response(200, json={"slug": "intro", "slots": []})
    )
    await server.get_availability("intro", "2026-06-16T00:00:00Z", "2026-06-17T00:00:00Z")
    params = route.calls.last.request.url.params
    assert params["from"] == "2026-06-16T00:00:00Z"
    assert params["to"] == "2026-06-17T00:00:00Z"


@respx.mock
async def test_get_billing_and_overview_and_audit() -> None:
    respx.get(f"{BASE}/billing/me").mock(return_value=httpx.Response(200, json={"plan": "pro", "is_comp": False}))
    respx.get(f"{BASE}/billing/overview").mock(
        return_value=httpx.Response(200, json={"plan": "pro", "usage": {"calendars": 5}})
    )
    audit = respx.get(f"{BASE}/audit-log").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "action": "api_token.create"}])
    )
    assert (await server.get_billing())["plan"] == "pro"
    assert (await server.get_billing_overview())["usage"]["calendars"] == 5
    out = await server.get_audit_log(25)
    assert out[0]["action"] == "api_token.create"
    assert audit.calls.last.request.url.params["limit"] == "25"


@respx.mock
async def test_list_all_calendars_passthrough() -> None:
    respx.get(f"{BASE}/calendars").mock(return_value=httpx.Response(200, json=[{"id": 1, "display_name": "Cal"}]))
    out = await server.list_all_calendars()
    assert out[0]["id"] == 1


@respx.mock
async def test_refresh_and_discover_calendars() -> None:
    respx.post(f"{BASE}/calendars/refresh").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    respx.post(f"{BASE}/connections/3/calendars/discover").mock(return_value=httpx.Response(200, json=[{"id": 2}]))
    assert (await server.refresh_calendars())[0]["id"] == 1
    assert (await server.discover_calendars(3))[0]["id"] == 2
