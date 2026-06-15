"""Tool-level tests: each @mcp.tool wrapper shapes I/O and hits the right endpoint end to end."""

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
async def test_list_connections_shapes_output() -> None:
    respx.get(f"{BASE}/connections").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 7,
                    "provider": "google",
                    "provider_account_email": "a@b.com",
                    "status": "active",
                    "scopes": ["calendar"],
                    "access_token_expires_at": None,
                }
            ],
        )
    )
    out = await server.list_connections()
    assert out == [{"id": 7, "provider": "google", "email": "a@b.com", "status": "active", "scopes": ["calendar"]}]


@respx.mock
async def test_list_calendars_shapes_live_provider_view() -> None:
    # GET /connections/{id}/calendars returns the LIVE provider view (provider CalendarDTO):
    # provider_calendar_id/display_name/is_primary/is_writable/is_hidden, and NO db id or
    # sync_enabled. The tool surfaces exactly those fields.
    respx.get(f"{BASE}/connections/7/calendars").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "provider_calendar_id": "primary",
                    "display_name": "Brad",
                    "description": "",
                    "timezone": "Europe/Bucharest",
                    "color": "#fff",
                    "is_primary": True,
                    "is_writable": True,
                    "is_hidden": False,
                }
            ],
        )
    )
    out = await server.list_calendars(7)
    assert out[0] == {
        "name": "Brad",
        "provider_calendar_id": "primary",
        "is_primary": True,
        "is_writable": True,
        "is_hidden": False,
    }


@respx.mock
async def test_create_sync_rule_posts_full_body() -> None:
    route = respx.post(f"{BASE}/sync/rules").mock(return_value=httpx.Response(201, json={"id": 9}))
    out = await server.create_sync_rule(1, 2, "busy_only", "[P]", True)
    assert out == {"id": 9}
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "source_calendar_id": 1,
        "target_calendar_id": 2,
        "visibility_mode": "busy_only",
        "mirror_prefix": "[P]",
        "enabled": True,
    }


async def test_create_sync_rule_rejects_bad_visibility() -> None:
    with pytest.raises(ValueError):
        await server.create_sync_rule(1, 2, "nope")


@respx.mock
async def test_delete_sync_rule_returns_marker() -> None:
    respx.delete(f"{BASE}/sync/rules/3").mock(return_value=httpx.Response(204))
    assert await server.delete_sync_rule(3) == {"deleted": True, "rule_id": 3}


@respx.mock
async def test_run_sync_rule_passes_through_result() -> None:
    respx.post(f"{BASE}/sync/rules/3/run").mock(
        return_value=httpx.Response(
            200,
            json={"source_calendar_id": 1, "created": 4, "updated": 0, "deleted": 0, "errors": []},
        )
    )
    out = await server.run_sync_rule(3)
    assert out["created"] == 4


@respx.mock
async def test_get_agenda_returns_events() -> None:
    respx.get(f"{BASE}/connections/4/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"events": [{"title": "Standup"}]})
    )
    out = await server.get_agenda(4, "primary", "2026-06-15T00:00:00Z", None)
    assert out["events"][0]["title"] == "Standup"


@respx.mock
async def test_create_event_posts_full_body() -> None:
    route = respx.post(f"{BASE}/connections/1/calendars/primary/events").mock(
        return_value=httpx.Response(201, json={"event": {"title": "Demo"}})
    )
    out = await server.create_event(
        1,
        "primary",
        "Demo",
        "2026-08-01T10:00:00Z",
        "2026-08-01T10:30:00Z",
        attendees=["a@x.com"],
    )
    assert out["event"]["title"] == "Demo"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "title": "Demo",
        "start_at": "2026-08-01T10:00:00Z",
        "end_at": "2026-08-01T10:30:00Z",
        "description": None,
        "location": None,
        "attendees": ["a@x.com"],
        "all_day": False,
        "add_conference": False,
        "notify": True,
    }


@respx.mock
async def test_reschedule_event_patches_event_id_and_times() -> None:
    route = respx.patch(f"{BASE}/connections/1/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"event": {"title": "Standup"}})
    )
    out = await server.reschedule_event(
        1, "primary", "evt-9", "2026-08-02T14:00:00Z", "2026-08-02T14:30:00Z", notify=False
    )
    assert out["event"]["title"] == "Standup"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "event_id": "evt-9",
        "start_at": "2026-08-02T14:00:00Z",
        "end_at": "2026-08-02T14:30:00Z",
        "notify": False,
    }


@respx.mock
async def test_cancel_event_deletes_with_query_and_returns_marker() -> None:
    route = respx.delete(f"{BASE}/connections/1/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"deleted": True, "event_id": "evt-9"})
    )
    out = await server.cancel_event(1, "primary", "evt-9")
    assert out == {"deleted": True, "event_id": "evt-9"}
    params = route.calls.last.request.url.params
    assert params["event_id"] == "evt-9"
    assert params["notify"] == "true"
