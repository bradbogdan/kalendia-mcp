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

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import KalendiaAPIError, KalendiaClient

logging.basicConfig(
    level=getattr(logging, os.environ.get("KALENDIA_LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(name="kalendia")
client = KalendiaClient()

_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

# Valid values for create_sync_rule's visibility_mode (kalendia.sync.visibility.VisibilityMode).
_VISIBILITY_MODES = ("busy_only", "title_only", "full_details")


# --- reads ---


@mcp.tool(annotations=_READ_ONLY)
async def list_connections() -> list[dict[str, Any]]:
    """List the user's connected calendar accounts (Google, Microsoft, iCloud, ICS, Zoom).

    Each item: id, provider, email, status, scopes. Use the id with list_calendars."""
    rows = await client.get_connections()
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
    """List the calendars under one connection. Each item: id (use as source/target in a sync rule),
    name, provider_calendar_id (use as calendar_id in get_agenda), is_primary, is_writable,
    sync_enabled. A sync rule's target must be a writable calendar."""
    rows = await client.get_calendars(connection_id)
    return [
        {
            "id": r["id"],
            "name": r.get("custom_name") or r["display_name"],
            "provider_calendar_id": r["provider_calendar_id"],
            "is_primary": r["is_primary"],
            "is_writable": r["is_writable"],
            "sync_enabled": r["sync_enabled"],
        }
        for r in rows
    ]


@mcp.tool(annotations=_READ_ONLY)
async def list_sync_rules() -> list[dict[str, Any]]:
    """List all sync (mirror) rules. Each rule mirrors events from a source calendar onto a target
    calendar. Returns id, source_calendar_id, target_calendar_id, visibility_mode, mirror_prefix,
    enabled."""
    return await client.get_sync_rules()


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
    return await client.get_events(connection_id, calendar_id, from_iso, to_iso)


@mcp.tool(annotations=_READ_ONLY)
async def list_scheduling_pages() -> list[dict[str, Any]]:
    """List the user's scheduling (booking) pages."""
    return await client.get_scheduling_pages()


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
    return await client.create_sync_rule(
        source_calendar_id, target_calendar_id, visibility_mode, mirror_prefix, enabled
    )


@mcp.tool(annotations=_DESTRUCTIVE)
async def delete_sync_rule(rule_id: int) -> dict[str, Any]:
    """Delete a sync rule (rule_id from list_sync_rules). The mirrored events it created on the
    target calendar are cleaned up afterward by Kalendia. This cannot be undone."""
    await client.delete_sync_rule(rule_id)
    return {"deleted": True, "rule_id": rule_id}


@mcp.tool(annotations=_MUTATING)
async def run_sync_rule(rule_id: int) -> dict[str, Any]:
    """Run a sync rule now (a full reconcile that backfills the target from the source). Returns
    counts of events created / updated / deleted, plus any per-event errors."""
    return await client.run_sync_rule(rule_id)


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
