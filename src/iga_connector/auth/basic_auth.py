"""HTTP Basic Authentication."""

from __future__ import annotations

import base64

import httpx

from .authenticator import Authenticator


class BasicAuthenticator(Authenticator):
    """HTTP Basic Authentication (RFC 7617)."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    async def authenticate(self, request: httpx.Request) -> httpx.Request:
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode("ascii")
        request.headers["Authorization"] = f"Basic {credentials}"
        return request
