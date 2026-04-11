"""Tests for the BaseConnector interface and registry."""

from __future__ import annotations

from typing import Any

import pytest

from iga_connector.core.connector import BaseConnector
from iga_connector.core.models import ConnectorStatus, OperationResult
from iga_connector.core.schema import ConnectorSchema
from iga_connector.registry import ConnectorRegistry


class StubConnector(BaseConnector):
    """Minimal concrete connector for testing the base class."""

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="stub",
            supported_operations=["test_connection", "list_accounts"],
        )

    async def test_connection(self) -> ConnectorStatus:
        return ConnectorStatus(connected=True, message="stub OK")


class TestBaseConnector:
    @pytest.mark.asyncio
    async def test_lifecycle(self):
        connector = StubConnector(config={"key": "value"})
        async with connector:
            status = await connector.test_connection()
            assert status.connected is True

    @pytest.mark.asyncio
    async def test_unsupported_operations_return_fail(self):
        connector = StubConnector(config={})
        result = await connector.create_account(
            __import__("iga_connector.core.models", fromlist=["Account"]).Account(
                identity="x"
            )
        )
        assert result.success is False

    def test_supported_operations(self):
        connector = StubConnector(config={})
        ops = connector.supported_operations()
        assert len(ops) == 2


class TestConnectorRegistry:
    def test_register_and_create(self):
        registry = ConnectorRegistry()

        @registry.register("test_stub")
        class TestStub(StubConnector):
            pass

        connector = registry.create("test_stub", {"foo": "bar"})
        assert isinstance(connector, StubConnector)

    def test_unknown_type_raises(self):
        registry = ConnectorRegistry()
        with pytest.raises(Exception, match="Unknown connector type"):
            registry.get("nonexistent")

    def test_list_registered(self):
        registry = ConnectorRegistry()

        @registry.register("a")
        class A(StubConnector):
            pass

        @registry.register("b")
        class B(StubConnector):
            pass

        assert sorted(registry.list_registered()) == ["a", "b"]
