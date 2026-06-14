# kalendia-mcp

An MCP server for [Kalendia](https://kalendia.io). Drive your calendar sync and scheduling from an
MCP client (Claude Code, Claude Desktop): list connections and calendars, read your agenda, and
create / delete / run sync rules, all from chat.

## Tools

Reads (read-only):
- `list_connections` — your connected calendar accounts (Google, Microsoft, iCloud, ICS, Zoom).
- `list_calendars(connection_id)` — calendars under one connection.
- `list_sync_rules` — all mirror rules.
- `get_agenda(connection_id, calendar_id, from_iso?, to_iso?)` — events in a window.
- `list_scheduling_pages` — your booking pages.

Writes (the client confirms before firing):
- `create_sync_rule(source_calendar_id, target_calendar_id, visibility_mode?, mirror_prefix?, enabled?)`
- `delete_sync_rule(rule_id)` (destructive)
- `run_sync_rule(rule_id)` — full reconcile now.

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

## Develop

```
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## Security

A token has the user's full account access (no scopes yet). Treat it like a password. Revoke a leaked
or stale token in Kalendia: Settings > API tokens.
