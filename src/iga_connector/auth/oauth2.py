"""OAuth 2.0 Client Credentials authentication."""

from __future__ import annotations

import time

import httpx

from .authenticator import Authenticator


class OAuth2Authenticator(Authenticator):
    """OAuth 2.0 Client Credentials flow.

    Automatically fetches and caches an access token,
    refreshing when it expires.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
    ) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._access_token: str | None = None
        self._expires_at: float = 0

    @property
    def _token_expired(self) -> bool:
        return self._access_token is None or time.time() >= self._expires_at

    async def refresh(self) -> None:
        async with httpx.AsyncClient() as client:
            data: dict[str, str] = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            if self.scope:
                data["scope"] = self.scope
            resp = await client.post(self.token_url, data=data)
            resp.raise_for_status()
            body = resp.json()
            self._access_token = body["access_token"]
            self._expires_at = time.time() + body.get("expires_in", 3600) - 60

    async def authenticate(self, request: httpx.Request) -> httpx.Request:
        if self._token_expired:
            await self.refresh()
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        return request
