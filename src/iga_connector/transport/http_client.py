"""HTTP transport layer used by REST-based connectors."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..auth.authenticator import Authenticator
from ..core.exceptions import ConnectionError, OperationError

logger = logging.getLogger("iga_connector.transport")


class HttpTransport:
    """Thin async HTTP client wrapper with authentication and retries.

    Usage:
        transport = HttpTransport(base_url="https://api.example.com", authenticator=auth)
        async with transport:
            data = await transport.get("/users")
    """

    def __init__(
        self,
        base_url: str,
        authenticator: Authenticator | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.authenticator = authenticator
        self.timeout = timeout
        self.max_retries = max_retries
        self._default_headers = headers or {}
        self.verify_ssl = verify_ssl
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpTransport:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._default_headers,
            verify=self.verify_ssl,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ConnectionError("Transport not connected. Use 'async with' block.")
        return self._client

    async def _send(self, request: httpx.Request) -> httpx.Response:
        if self.authenticator:
            request = await self.authenticator.authenticate(request)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.send(request)
                if response.status_code >= 500 and attempt < self.max_retries:
                    logger.warning(
                        "Server error %s on attempt %d, retrying...",
                        response.status_code,
                        attempt,
                    )
                    continue
                return response
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("Transport error on attempt %d: %s", attempt, exc)

        raise ConnectionError(
            f"Request failed after {self.max_retries} attempts",
            cause=last_exc,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        request = self.client.build_request("GET", path, params=params)
        resp = await self._send(request)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        request = self.client.build_request("POST", path, json=json)
        resp = await self._send(request)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def put(self, path: str, json: dict[str, Any] | None = None) -> Any:
        request = self.client.build_request("PUT", path, json=json)
        resp = await self._send(request)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def patch(self, path: str, json: dict[str, Any] | None = None) -> Any:
        request = self.client.build_request("PATCH", path, json=json)
        resp = await self._send(request)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def delete(self, path: str) -> Any:
        request = self.client.build_request("DELETE", path)
        resp = await self._send(request)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def health_check(self, path: str = "/") -> bool:
        """Quick connectivity check – returns True if the target responds."""
        try:
            request = self.client.build_request("GET", path)
            resp = await self._send(request)
            return resp.status_code < 500
        except Exception:
            return False
