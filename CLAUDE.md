# CLAUDE.md

Type: Project (personal)

MCP server that exposes Kalendia (kalendia.io, the calendar sync / scheduling product) as tools so an
MCP client (Claude) can drive it from chat: list connections and calendars, read an agenda, and
create / delete / run sync rules.

## Architecture

- `src/kalendia_mcp/client.py` — `KalendiaClient`, a thin async httpx wrapper over the Kalendia REST
  API. One method per endpoint, no business logic. Reads `KALENDIA_TOKEN` + `KALENDIA_API_URL` from
  the environment at request time. Raises `KalendiaAPIError(status_code, detail)` on any non-2xx.
- `src/kalendia_mcp/server.py` — the `FastMCP` instance and the `@mcp.tool()` definitions (27 tools
  at parity with the web app's owner actions, incl. event writes create_event / reschedule_event /
  cancel_event). Tools are thin: shape inputs/outputs, delegate to the
  client via `_client()`. Read tools are annotated `readOnlyHint`; deletes/disconnect are
  `destructiveHint`; other writes are mutations. `_client()` resolves the token per request: the auth
  context's token in HTTP mode, else `KALENDIA_TOKEN`.
- `src/kalendia_mcp/auth.py` — `KalendiaTokenVerifier` (Phase 2). In HTTP mode the server is an OAuth
  resource server; the verifier validates a presented `kld_` token against the Kalendia API and the
  per-request token is what tools forward (multi-user from one instance).
- Transport is stdio by default (`main()`, single-user via env token); `--http` runs Streamable HTTP
  (multi-user, per-request token). One `FastMCP` instance serves both; auth config is inert on stdio.

## Auth

Kalendia accepts a personal access token (a `kld_...` value) as a bearer. Mint one in the app under
Settings > API tokens. The backend resolves a `kld_` bearer in `current_user_id` (the same dependency
the whole API uses), so the token has the user's full access. There is no separate scope system yet:
a token can do anything the user can. Treat it like a password.

## Conventions

- Python >= 3.10, `uv` for env + run, `hatchling` build. ruff line-length 120 (E/F/I/UP), pyright
  strict, pytest + pytest-asyncio (`asyncio_mode = auto`), respx for HTTP mocking.
- No emojis, em dashes, or en dashes (workspace rule). Use commas, colons, periods, or parentheses.
- Keep the client a pure pass-through; do not add Kalendia business logic here (it lives in the
  backend). A new endpoint = a new client method + a new tool, nothing more.

## Quality gate

`uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`

## Related

Backend repo: `~/Claude/Code/personal/kalendia` (the `api_tokens` package + `/account/tokens` issue
the tokens this server consumes; `auth/dependency.py` resolves them).
