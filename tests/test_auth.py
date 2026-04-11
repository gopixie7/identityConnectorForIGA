"""Tests for authentication strategies."""

import pytest
import httpx

from iga_connector.auth.authenticator import AuthConfig, Authenticator
from iga_connector.auth.basic_auth import BasicAuthenticator
from iga_connector.auth.api_key import ApiKeyAuthenticator


class TestBasicAuth:
    @pytest.mark.asyncio
    async def test_adds_authorization_header(self):
        auth = BasicAuthenticator(username="user", password="pass")
        request = httpx.Request("GET", "https://example.com")
        request = await auth.authenticate(request)
        assert request.headers["Authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_encodes_credentials(self):
        import base64

        auth = BasicAuthenticator(username="admin", password="secret")
        request = httpx.Request("GET", "https://example.com")
        request = await auth.authenticate(request)
        encoded = request.headers["Authorization"].split(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "admin:secret"


class TestApiKeyAuth:
    @pytest.mark.asyncio
    async def test_header_mode(self):
        auth = ApiKeyAuthenticator(api_key="my-key", header_name="X-Token")
        request = httpx.Request("GET", "https://example.com")
        request = await auth.authenticate(request)
        assert request.headers["X-Token"] == "my-key"

    @pytest.mark.asyncio
    async def test_query_mode(self):
        auth = ApiKeyAuthenticator(
            api_key="my-key", location="query", query_param_name="token"
        )
        request = httpx.Request("GET", "https://example.com/api")
        request = await auth.authenticate(request)
        assert "token=my-key" in str(request.url)


class TestAuthenticatorFactory:
    def test_basic(self):
        auth = Authenticator.from_config(
            AuthConfig(auth_type="basic", params={"username": "u", "password": "p"})
        )
        assert isinstance(auth, BasicAuthenticator)

    def test_api_key(self):
        auth = Authenticator.from_config(
            AuthConfig(auth_type="api_key", params={"api_key": "k"})
        )
        assert isinstance(auth, ApiKeyAuthenticator)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown auth_type"):
            Authenticator.from_config(AuthConfig(auth_type="kerberos"))
