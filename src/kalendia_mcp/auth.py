"""Token verification for the remote (HTTP) MCP transport. Phase 2, multi-user.

In HTTP mode the server is an OAuth 2.0 resource server: each request carries the caller's own
Kalendia personal access token (a `kld_...` value) as the bearer. This verifier validates that token
by making one cheap authed call to the Kalendia API (GET /billing/me); a 200 means the token resolves
to a user. Valid results are cached briefly so a busy client does not re-validate on every tool call.
Failures are never cached, so a revoked or freshly minted token takes effect immediately.
"""

import os
import time

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .client import DEFAULT_API_URL

_TOKEN_PREFIX = "kld_"
_CACHE_TTL_SECONDS = 60.0


class KalendiaTokenVerifier(TokenVerifier):
    """Validates Kalendia `kld_` personal access tokens against the live API."""

    def __init__(self) -> None:
        self._cache: dict[str, float] = {}  # token -> monotonic expiry of a known-good result

    def _api_url(self) -> str:
        return (os.environ.get("KALENDIA_API_URL") or DEFAULT_API_URL).rstrip("/")

    async def verify_token(self, token: str) -> AccessToken | None:
        # A non-kld_ bearer is not a Kalendia token; reject without a network call.
        if not token.startswith(_TOKEN_PREFIX):
            return None
        now = time.monotonic()
        expiry = self._cache.get(token)
        if expiry is not None and expiry > now:
            return _access(token)
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    f"{self._api_url()}/billing/me",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        except httpx.HTTPError:
            return None  # transport failure: treat as unverified, do not cache
        if resp.status_code != 200:
            return None
        self._cache[token] = now + _CACHE_TTL_SECONDS
        return _access(token)


def _access(token: str) -> AccessToken:
    # No scopes yet: a Kalendia token carries the user's full account access. The token itself is what
    # tools forward to the API (see server._client), so it is the meaningful field here.
    return AccessToken(token=token, client_id="kalendia-pat", scopes=[], subject="kalendia-user")
