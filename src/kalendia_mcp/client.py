"""Async HTTP client for the Kalendia REST API.

Authenticates with a personal access token (a `kld_...` value minted in Kalendia under
Settings > API tokens) sent as a bearer. The token and base URL are read from the environment at
request time (KALENDIA_TOKEN, KALENDIA_API_URL) so the MCP host's configured env is always honored.
Every method is a thin pass-through to one documented endpoint; no business logic lives here.
"""

import os
from typing import Any, cast

import httpx

DEFAULT_API_URL = "https://api.kalendia.io"


class KalendiaAPIError(Exception):
    """A non-2xx response from the Kalendia API (or a missing token). Carries the HTTP status and a
    human-readable detail so the MCP tool surfaces an actionable message, not a stack trace."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Kalendia API {status_code}: {detail}")


def _detail(response: httpx.Response) -> str:
    """Pull FastAPI's {"detail": ...} message if present, else a trimmed body."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        detail = cast("dict[str, object]", body).get("detail")
        if isinstance(detail, str):
            return detail
    return response.text[:300]


class KalendiaClient:
    def __init__(self, api_url: str | None = None, token: str | None = None) -> None:
        self._api_url_override = api_url
        self._token_override = token

    def _base_url(self) -> str:
        url = self._api_url_override or os.environ.get("KALENDIA_API_URL") or DEFAULT_API_URL
        return url.rstrip("/")

    def _token(self) -> str:
        token = self._token_override or os.environ.get("KALENDIA_TOKEN")
        if not token:
            raise KalendiaAPIError(
                0,
                "KALENDIA_TOKEN is not set. Mint one in Kalendia > Settings > API tokens and set it "
                "in the MCP server env.",
            )
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url()}{path}"
        headers = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.request(method, url, params=params, json=json, headers=headers)
        if response.status_code == 401:
            raise KalendiaAPIError(401, "token rejected (missing, invalid, or revoked). Check KALENDIA_TOKEN.")
        if response.status_code >= 400:
            raise KalendiaAPIError(response.status_code, _detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # --- reads ---

    async def get_connections(self) -> Any:
        return await self._request("GET", "/connections")

    async def get_calendars(self, connection_id: int) -> Any:
        return await self._request("GET", f"/connections/{connection_id}/calendars")

    async def get_sync_rules(self) -> Any:
        return await self._request("GET", "/sync/rules")

    async def get_events(self, connection_id: int, calendar_id: str, from_iso: str | None, to_iso: str | None) -> Any:
        params: dict[str, Any] = {}
        if from_iso:
            params["from"] = from_iso
        if to_iso:
            params["to"] = to_iso
        return await self._request(
            "GET",
            f"/connections/{connection_id}/calendars/{calendar_id}/events",
            params=params or None,
        )

    async def get_scheduling_pages(self) -> Any:
        return await self._request("GET", "/scheduling-pages")

    # --- writes ---

    async def create_sync_rule(
        self,
        source_calendar_id: int,
        target_calendar_id: int,
        visibility_mode: str,
        mirror_prefix: str,
        enabled: bool,
    ) -> Any:
        return await self._request(
            "POST",
            "/sync/rules",
            json={
                "source_calendar_id": source_calendar_id,
                "target_calendar_id": target_calendar_id,
                "visibility_mode": visibility_mode,
                "mirror_prefix": mirror_prefix,
                "enabled": enabled,
            },
        )

    async def delete_sync_rule(self, rule_id: int) -> None:
        await self._request("DELETE", f"/sync/rules/{rule_id}")

    async def run_sync_rule(self, rule_id: int) -> Any:
        return await self._request("POST", f"/sync/rules/{rule_id}/run")
