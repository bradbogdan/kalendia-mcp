#!/usr/bin/env python3
"""Kalendia MCP server.

Exposes Kalendia (calendar sync / scheduling) as MCP tools so an MCP client can list connections and
calendars, read an agenda, and create / delete / run sync rules from chat. Read tools are marked
read-only; create/delete/run are marked as mutations so the client can confirm before firing.

Auth is a Kalendia personal access token via the KALENDIA_TOKEN env var (see client.py). Transport
is stdio by default; pass --http to run Streamable HTTP.
"""

import logging
import os
import sys
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from .auth import KalendiaTokenVerifier
from .client import KalendiaAPIError, KalendiaClient

logging.basicConfig(
    level=getattr(logging, os.environ.get("KALENDIA_LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_API_URL = os.environ.get("KALENDIA_API_URL") or "https://api.kalendia.io"
# Public URL this server is reached at when run remotely (HTTP). Advertised in the OAuth protected
# resource metadata; override per deployment.
_MCP_URL = os.environ.get("KALENDIA_MCP_URL") or "https://mcp.kalendia.io"

# One instance serves both transports. In HTTP (remote, multi-user) mode the auth layer enforces a
# bearer token per request via the verifier; in stdio (single-user) mode the auth layer is inert and
# the token comes from the KALENDIA_TOKEN env var (see _client). Configuring auth does not affect
# stdio.
mcp = FastMCP(
    name="kalendia",
    host=os.environ.get("KALENDIA_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("KALENDIA_MCP_PORT", "8080")),
    token_verifier=KalendiaTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(_API_URL),
        resource_server_url=AnyHttpUrl(_MCP_URL),
        required_scopes=[],
    ),
)


def _client() -> KalendiaClient:
    """Resolve the Kalendia client for this request. In HTTP (remote) mode each request is
    authenticated by the caller's own kld_ token, exposed via the auth context, so one server
    instance serves many users. In stdio (single-user) mode there is no auth context, so fall back to
    the KALENDIA_TOKEN env var."""
    try:
        access = get_access_token()
    except Exception:  # noqa: BLE001 - no auth context (stdio path) -> env token
        access = None
    if access is not None:
        return KalendiaClient(token=access.token)
    return KalendiaClient()


_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

# Valid values for create_sync_rule's visibility_mode (kalendia.sync.visibility.VisibilityMode).
_VISIBILITY_MODES = ("busy_only", "title_only", "full_details")
# Valid video_provider values for a scheduling page (zoom additionally needs a zoom_connection_id).
_VIDEO_PROVIDERS = ("none", "google_meet", "teams", "zoom")


# --- reads ---


@mcp.tool(annotations=_READ_ONLY)
async def list_connections() -> list[dict[str, Any]]:
    """List the user's connected calendar accounts (Google, Microsoft, iCloud, ICS, Zoom).

    Each item: id, provider, email, status, scopes. Use the id with list_calendars."""
    rows = await _client().get_connections()
    return [
        {
            "id": r["id"],
            "provider": r["provider"],
            "email": r["provider_account_email"],
            "status": r["status"],
            "scopes": r.get("scopes", []),
        }
        for r in rows
    ]


@mcp.tool(annotations=_READ_ONLY)
async def list_calendars(connection_id: int) -> list[dict[str, Any]]:
    """List the LIVE provider calendars under one connection (a fresh fetch from the provider): each
    item is name, provider_calendar_id (use this as calendar_id in get_agenda), is_primary,
    is_writable, is_hidden. This is the provider view and has NO Kalendia calendar id; to get the
    numeric calendar id needed for sync rules and scheduling pages, use list_all_calendars."""
    rows = await _client().get_calendars(connection_id)
    return [
        {
            "name": r["display_name"],
            "provider_calendar_id": r["provider_calendar_id"],
            "is_primary": r["is_primary"],
            "is_writable": r["is_writable"],
            "is_hidden": r.get("is_hidden", False),
        }
        for r in rows
    ]


@mcp.tool(annotations=_READ_ONLY)
async def list_sync_rules() -> list[dict[str, Any]]:
    """List all sync (mirror) rules. Each rule mirrors events from a source calendar onto a target
    calendar. Returns id, source_calendar_id, target_calendar_id, visibility_mode, mirror_prefix,
    enabled."""
    return await _client().get_sync_rules()


@mcp.tool(annotations=_READ_ONLY)
async def get_agenda(
    connection_id: int,
    calendar_id: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Read events from one calendar in a time window.

    connection_id comes from list_connections; calendar_id is a calendar's provider_calendar_id from
    list_calendars (e.g. an email, or "primary"). from_iso / to_iso are ISO-8601 datetimes
    (e.g. "2026-06-15T00:00:00Z"); omit them to use Kalendia's default window. Returns {events: [...]}.
    """
    return await _client().get_events(connection_id, calendar_id, from_iso, to_iso)


@mcp.tool(annotations=_READ_ONLY)
async def list_scheduling_pages() -> list[dict[str, Any]]:
    """List the user's scheduling (booking) pages."""
    return await _client().get_scheduling_pages()


# --- writes (the client should confirm with the user before calling these) ---


@mcp.tool(annotations=_MUTATING)
async def create_sync_rule(
    source_calendar_id: int,
    target_calendar_id: int,
    visibility_mode: str = "busy_only",
    mirror_prefix: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    """Create a sync rule that mirrors events from source_calendar_id onto target_calendar_id.

    Calendar ids come from list_calendars; the target must be writable. visibility_mode is one of
    "busy_only" (hide all details, default), "title_only", or "full_details". mirror_prefix is an
    optional string prepended to mirrored event titles (e.g. "[Personal]"). Set enabled=False to
    create it paused. Mirrors the source's current events into the target on creation."""
    if visibility_mode not in _VISIBILITY_MODES:
        raise ValueError(f"visibility_mode must be one of {_VISIBILITY_MODES}, got {visibility_mode!r}")
    return await _client().create_sync_rule(
        source_calendar_id, target_calendar_id, visibility_mode, mirror_prefix, enabled
    )


@mcp.tool(annotations=_DESTRUCTIVE)
async def delete_sync_rule(rule_id: int) -> dict[str, Any]:
    """Delete a sync rule (rule_id from list_sync_rules). The mirrored events it created on the
    target calendar are cleaned up afterward by Kalendia. This cannot be undone."""
    await _client().delete_sync_rule(rule_id)
    return {"deleted": True, "rule_id": rule_id}


@mcp.tool(annotations=_MUTATING)
async def run_sync_rule(rule_id: int) -> dict[str, Any]:
    """Run a sync rule now (a full reconcile that backfills the target from the source). Returns
    counts of events created / updated / deleted, plus any per-event errors."""
    return await _client().run_sync_rule(rule_id)


# --- event writes (the client should confirm with the user before calling these) ---


@mcp.tool(annotations=_MUTATING)
async def create_event(
    connection_id: int,
    calendar_id: str,
    title: str,
    start_iso: str,
    end_iso: str,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    all_day: bool = False,
    add_conference: bool = False,
    notify: bool = True,
) -> dict[str, Any]:
    """Create a calendar event.

    connection_id from list_connections; calendar_id is a writable calendar's provider_calendar_id
    from list_calendars. start_iso / end_iso are ISO-8601 datetimes (e.g. "2026-06-20T14:00:00Z";
    naive is read as UTC). attendees is a list of email addresses; notify=True (default) emails them
    an invitation. add_conference=True attaches a native video link (Google Meet / Teams). The
    target must be writable and must NOT be the target of a sync rule. Returns {event: {...}}."""
    return await _client().create_event(
        connection_id,
        calendar_id,
        {
            "title": title,
            "start_at": start_iso,
            "end_at": end_iso,
            "description": description,
            "location": location,
            "attendees": attendees or [],
            "all_day": all_day,
            "add_conference": add_conference,
            "notify": notify,
        },
    )


@mcp.tool(annotations=_MUTATING)
async def reschedule_event(
    connection_id: int,
    calendar_id: str,
    event_id: str,
    start_iso: str,
    end_iso: str,
    notify: bool = True,
) -> dict[str, Any]:
    """Reschedule one event to a new time window (the core "move this call" action).

    connection_id from list_connections; calendar_id from list_calendars; event_id is the event's
    provider_event_id from get_agenda. For a recurring meeting, pass the specific occurrence's id
    (get_agenda returns each occurrence separately) to move just that one. start_iso / end_iso are
    ISO-8601 datetimes. Only the time changes: title, attendees, location, and the video link are
    preserved. notify=True (default) emails the attendees about the new time. Returns {event:
    {...}}."""
    return await _client().reschedule_event(
        connection_id,
        calendar_id,
        {"event_id": event_id, "start_at": start_iso, "end_at": end_iso, "notify": notify},
    )


@mcp.tool(annotations=_DESTRUCTIVE)
async def cancel_event(
    connection_id: int,
    calendar_id: str,
    event_id: str,
    notify: bool = True,
) -> dict[str, Any]:
    """Cancel (delete) one event. Cannot be undone.

    connection_id from list_connections; calendar_id from list_calendars; event_id from get_agenda.
    notify=True (default) sends a cancellation to the attendees. An unknown event returns an error on
    Google / Microsoft; iCloud treats an already-deleted event as success."""
    await _client().cancel_event(connection_id, calendar_id, event_id, notify)
    return {"deleted": True, "event_id": event_id}


# --- connections + calendars ---


@mcp.tool(annotations=_READ_ONLY)
async def list_all_calendars() -> list[dict[str, Any]]:
    """List every calendar across all connected accounts as a flat list (id, connection_id,
    provider_calendar_id, display_name, custom_name, is_primary, is_writable, sync_enabled). Use the
    calendar id as a sync-rule source/target or a scheduling-page calendar."""
    return await _client().get_all_calendars()


@mcp.tool(annotations=_MUTATING)
async def connect_icloud(apple_id: str, app_specific_password: str) -> dict[str, Any]:
    """Connect an Apple iCloud calendar. Requires an app-specific password (NOT your normal Apple
    password; generate one at appleid.apple.com under Sign-In and Security). Credentials are
    validated before saving. Returns the new connection."""
    return await _client().connect_icloud(apple_id, app_specific_password)


@mcp.tool(annotations=_MUTATING)
async def connect_ics(feed_url: str) -> dict[str, Any]:
    """Connect a read-only calendar from a public ICS feed URL (an https/webcal .ics link). The feed
    is fetched and parsed to validate it. An ICS calendar can be a sync source but not a target."""
    return await _client().connect_ics(feed_url)


@mcp.tool(annotations=_MUTATING)
async def refresh_calendars() -> list[dict[str, Any]]:
    """Re-discover calendars across ALL connected accounts in one call (picks up calendars created
    since the account was connected). A connection whose provider errors is skipped, not fatal."""
    return await _client().refresh_calendars()


@mcp.tool(annotations=_MUTATING)
async def discover_calendars(connection_id: int) -> list[dict[str, Any]]:
    """Re-discover the calendars under one connection (connection_id from list_connections). Newly
    visible calendars are auto-activated up to the plan's calendar limit."""
    return await _client().discover_calendars(connection_id)


@mcp.tool(annotations=_MUTATING)
async def set_active_calendars(connection_id: int, active_calendar_ids: list[int]) -> dict[str, Any]:
    """Set which calendars under a connection are active (synced and usable in rules/pages). This
    REPLACES the full active set for that connection. Note: passing an empty list would disconnect
    the whole account, so this tool rejects an empty list; use disconnect_connection for that."""
    if not active_calendar_ids:
        raise ValueError("active_calendar_ids is empty; to remove the whole account use disconnect_connection")
    return await _client().set_active_calendars(connection_id, active_calendar_ids)


@mcp.tool(annotations=_MUTATING)
async def rename_calendar(calendar_id: int, custom_name: str | None = None) -> dict[str, Any]:
    """Set a friendly display name for a calendar (calendar_id from list_calendars). Pass null or an
    empty string to clear the override and fall back to the provider's name."""
    return await _client().rename_calendar(calendar_id, custom_name)


@mcp.tool(annotations=_DESTRUCTIVE)
async def disconnect_connection(connection_id: int) -> dict[str, Any]:
    """Disconnect a calendar account: permanently deletes the connection and its stored credentials,
    pauses any booking pages that targeted its calendars, and removes sync rules that used them. The
    provider OAuth grant is revoked best-effort. Cannot be undone (you would reconnect from scratch).
    Returns which pages were paused and how many rules were removed."""
    return await _client().disconnect_connection(connection_id)


# --- scheduling pages ---


@mcp.tool(annotations=_READ_ONLY)
async def get_scheduling_page(page_id: int) -> dict[str, Any]:
    """Get one scheduling (booking) page's full config, including its availability_window. Fetch this
    before update_scheduling_page, since update is a full replace."""
    return await _client().get_scheduling_page(page_id)


@mcp.tool(annotations=_READ_ONLY)
async def get_availability(slug: str, from_iso: str | None = None, to_iso: str | None = None) -> dict[str, Any]:
    """Get bookable slots for a scheduling page by its slug, optionally within an ISO-8601 UTC window
    (from_iso/to_iso). Returns {slug, title, duration_minutes, slots: [ISO datetimes]}. Omit the
    window for the page's full horizon."""
    return await _client().get_availability(slug, from_iso, to_iso)


@mcp.tool(annotations=_MUTATING)
async def create_scheduling_page(
    slug: str,
    title: str,
    duration_minutes: int,
    availability_window: dict[str, Any],
    source_calendar_ids: list[int],
    target_calendar_id: int,
    video_provider: str = "none",
    buffer_before_min: int = 0,
    buffer_after_min: int = 0,
    min_notice_minutes: int = 0,
    max_horizon_days: int = 60,
    zoom_connection_id: int | None = None,
    booking_webhook_url: str | None = None,
) -> dict[str, Any]:
    """Create a scheduling (booking) page.

    slug is the public URL suffix (unique per account). availability_window is
    {"timezone": "<IANA, e.g. Europe/Bucharest>", "weekly": {"mon": [["09:00","17:00"]], "tue": [...]}}
    where each day key (mon..sun) maps to a list of [start, end] "HH:MM" intervals; omit a day for no
    availability. source_calendar_ids are checked for conflicts; target_calendar_id (must be writable
    and active) is where confirmed bookings are created. video_provider is one of
    none | google_meet | teams | zoom (zoom also needs zoom_connection_id)."""
    if video_provider not in _VIDEO_PROVIDERS:
        raise ValueError(f"video_provider must be one of {_VIDEO_PROVIDERS}, got {video_provider!r}")
    return await _client().create_scheduling_page(
        {
            "slug": slug,
            "title": title,
            "duration_minutes": duration_minutes,
            "availability_window": availability_window,
            "source_calendar_ids": source_calendar_ids,
            "target_calendar_id": target_calendar_id,
            "video_provider": video_provider,
            "buffer_before_min": buffer_before_min,
            "buffer_after_min": buffer_after_min,
            "min_notice_minutes": min_notice_minutes,
            "max_horizon_days": max_horizon_days,
            "zoom_connection_id": zoom_connection_id,
            "booking_webhook_url": booking_webhook_url,
        }
    )


@mcp.tool(annotations=_MUTATING)
async def update_scheduling_page(
    page_id: int,
    slug: str,
    title: str,
    duration_minutes: int,
    availability_window: dict[str, Any],
    source_calendar_ids: list[int],
    target_calendar_id: int,
    video_provider: str = "none",
    buffer_before_min: int = 0,
    buffer_after_min: int = 0,
    min_notice_minutes: int = 0,
    max_horizon_days: int = 60,
    zoom_connection_id: int | None = None,
    booking_webhook_url: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    """Update a scheduling page. This is a FULL REPLACE: call get_scheduling_page first, change the
    fields you want, and pass every field back (any omitted optional field resets to its default).
    Set is_active=False to pause the page. Field meanings match create_scheduling_page."""
    if video_provider not in _VIDEO_PROVIDERS:
        raise ValueError(f"video_provider must be one of {_VIDEO_PROVIDERS}, got {video_provider!r}")
    return await _client().update_scheduling_page(
        page_id,
        {
            "slug": slug,
            "title": title,
            "duration_minutes": duration_minutes,
            "availability_window": availability_window,
            "source_calendar_ids": source_calendar_ids,
            "target_calendar_id": target_calendar_id,
            "video_provider": video_provider,
            "buffer_before_min": buffer_before_min,
            "buffer_after_min": buffer_after_min,
            "min_notice_minutes": min_notice_minutes,
            "max_horizon_days": max_horizon_days,
            "zoom_connection_id": zoom_connection_id,
            "booking_webhook_url": booking_webhook_url,
            "is_active": is_active,
        },
    )


@mcp.tool(annotations=_DESTRUCTIVE)
async def delete_scheduling_page(page_id: int) -> dict[str, Any]:
    """Delete a scheduling page (page_id from list_scheduling_pages). Cannot be undone."""
    await _client().delete_scheduling_page(page_id)
    return {"deleted": True, "page_id": page_id}


# --- billing + audit (read) ---


@mcp.tool(annotations=_READ_ONLY)
async def get_billing() -> dict[str, Any]:
    """Get the current plan and subscription status: plan, tier, subscription_status,
    current_period_end, is_comp."""
    return await _client().get_billing()


@mcp.tool(annotations=_READ_ONLY)
async def get_billing_overview() -> dict[str, Any]:
    """Get plan plus current usage and limits: usage {calendars, scheduling_pages} against limits
    {max_calendars, max_scheduling_pages, teams_app, custom_domain} (null limit = unlimited)."""
    return await _client().get_billing_overview()


@mcp.tool(annotations=_READ_ONLY)
async def get_audit_log(limit: int = 50) -> list[dict[str, Any]]:
    """Get recent account audit-log entries, most recent first: id, action, target_type, target_id,
    payload, created_at. limit is clamped to 1..500."""
    return await _client().get_audit_log(limit)


def main() -> None:
    transport = "streamable-http" if "--http" in sys.argv else "stdio"
    try:
        mcp.run(transport=transport)
    except KeyboardInterrupt:
        pass
    except KalendiaAPIError as exc:
        logger.error("Kalendia API error: %s", exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - log and exit non-zero so the host sees the failure
        logger.exception("Server error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
