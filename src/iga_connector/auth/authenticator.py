"""Base authenticator interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

import httpx


class AuthConfig(BaseModel):
    """Configuration shared across authentication strategies."""

    auth_type: str
    params: dict[str, Any] = {}


class Authenticator(ABC):
    """Abstract base for all authentication strategies.

    Authenticators are responsible for enriching outgoing HTTP requests
    with the credentials required by the target system.
    """

    @abstractmethod
    async def authenticate(self, request: httpx.Request) -> httpx.Request:
        """Inject credentials into an outgoing request."""

    async def refresh(self) -> None:
        """Refresh credentials (e.g., token rotation).

        Override when the auth strategy supports proactive refresh.
        """

    @classmethod
    def from_config(cls, config: AuthConfig) -> Authenticator:
        """Factory: build the right Authenticator subclass from a config dict."""
        from .basic_auth import BasicAuthenticator
        from .oauth2 import OAuth2Authenticator
        from .api_key import ApiKeyAuthenticator

        registry: dict[str, type[Authenticator]] = {
            "basic": BasicAuthenticator,
            "oauth2": OAuth2Authenticator,
            "api_key": ApiKeyAuthenticator,
        }
        auth_cls = registry.get(config.auth_type)
        if auth_cls is None:
            raise ValueError(
                f"Unknown auth_type '{config.auth_type}'. "
                f"Supported: {list(registry.keys())}"
            )
        return auth_cls(**config.params)
