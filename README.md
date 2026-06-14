# kalendia-mcp

An MCP server for [Kalendia](https://kalendia.io). Drive your calendar sync and scheduling from an
MCP client (Claude Code, Claude Desktop): list connections and calendars, read your agenda, and
create / delete / run sync rules, all from chat.

## Tools (24)

The tool surface mirrors what a user can do in the Kalendia web app (everything reachable by an API
token; OAuth-redirect actions like connecting Google/Microsoft or Stripe checkout stay in the web UI,
and account deletion is intentionally not exposed).

Reads (read-only):
- `list_connections` — connected calendar accounts (Google, Microsoft, iCloud, ICS, Zoom).
- `list_calendars(connection_id)` — live provider calendars under one connection (no Kalendia id).
- `list_all_calendars` — every persisted calendar across accounts, with the numeric id used by rules/pages.
- `list_sync_rules` — all mirror rules.
- `get_agenda(connection_id, calendar_id, from_iso?, to_iso?)` — events in a window.
- `list_scheduling_pages` / `get_scheduling_page(page_id)` — booking pages.
- `get_availability(slug, from_iso?, to_iso?)` — bookable slots for a page.
- `get_billing` / `get_billing_overview` — plan, usage, limits.
- `get_audit_log(limit?)` — recent account activity.

Writes (the client confirms before firing):
- Sync rules: `create_sync_rule`, `run_sync_rule`, `delete_sync_rule` (destructive).
- Connections/calendars: `connect_icloud`, `connect_ics`, `refresh_calendars`, `discover_calendars`,
  `set_active_calendars`, `rename_calendar`, `disconnect_connection` (destructive).
- Scheduling pages: `create_scheduling_page`, `update_scheduling_page`, `delete_scheduling_page` (destructive).

## Setup

1. Mint a personal access token in Kalendia: Settings > API tokens. Copy it (shown once; starts with
   `kld_`).
2. Install deps: `uv sync`.
3. Configure the env: copy `.env.example` to `.env` and set `KALENDIA_TOKEN` (and
   `KALENDIA_API_URL` if testing against a local backend).

## Run

```
uv run kalendia-mcp          # stdio (default)
uv run kalendia-mcp --http   # Streamable HTTP
```

## Register in Claude Code

Add to your MCP config (e.g. `~/.claude.json`), filling in the token:

```json
{
  "mcpServers": {
    "kalendia": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/bogdan-georgebrad/Claude/Code/personal/kalendia-mcp", "kalendia-mcp"],
      "env": {
        "KALENDIA_TOKEN": "kld_your_token_here",
        "KALENDIA_API_URL": "https://api.kalendia.io"
      }
    }
  }
}
```

To test against a local backend instead, set `KALENDIA_API_URL` to `http://localhost:8002` and use a
token minted on that backend.

## Remote / multi-user (HTTP)

`uv run kalendia-mcp --http` runs the server over Streamable HTTP as an OAuth 2.0 resource server, so
ONE deployed instance serves many users: each request authenticates with the caller's own `kld_`
token (no per-user env var). It serves OAuth Protected Resource Metadata at
`/.well-known/oauth-protected-resource` (advertising Kalendia as the authorization server), rejects
unauthenticated/invalid tokens with `401` + `WWW-Authenticate`, validates a presented `kld_` token
against the Kalendia API, and forwards it to act as that user. Config via env:
`KALENDIA_MCP_HOST` / `KALENDIA_MCP_PORT` (bind), `KALENDIA_MCP_URL` (public URL in the metadata),
`KALENDIA_API_URL` (the Kalendia API).

Remaining for a public launch (tracked as Phase 2): hosting/deploy of this HTTP server, and full
OAuth authorization-server discovery (dynamic client registration + auth-code + PKCE) so clients can
mint tokens in-flow instead of pasting a `kld_` token. Today a client connects by presenting a
`kld_` bearer (minted in Settings > API tokens).

## Develop

```
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## Security

A token has the user's full account access (no scopes yet). Treat it like a password. Revoke a leaked
or stale token in Kalendia: Settings > API tokens.
