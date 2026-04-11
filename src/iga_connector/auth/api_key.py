"""API Key authentication."""

from __future__ import annotations

import httpx

from .authenticator import Authenticator


class ApiKeyAuthenticator(Authenticator):
    """Authenticate using a static API key sent as a header or query parameter."""

    def __init__(
        self,
        api_key: str,
        header_name: str = "X-API-Key",
        location: str = "header",
        query_param_name: str = "api_key",
    ) -> None:
        self.api_key = api_key
        self.header_name = header_name
        self.location = location  # "header" or "query"
        self.query_param_name = query_param_name

    async def authenticate(self, request: httpx.Request) -> httpx.Request:
        if self.location == "query":
            request.url = request.url.copy_merge_params(
                {self.query_param_name: self.api_key}
            )
        else:
            request.headers[self.header_name] = self.api_key
        return request
