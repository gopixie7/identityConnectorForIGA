"""Example: Building a custom REST connector for a fictional HR system.

This example shows how to:
  1. Subclass the REST connector or BaseConnector directly
  2. Customise endpoint specs for your target system
  3. Run the connector against a live API

Run:
    python examples/sample_rest_connector.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from iga_connector.auth.authenticator import AuthConfig, Authenticator
from iga_connector.core.connector import BaseConnector
from iga_connector.core.models import (
    Account,
    AccountStatus,
    ConnectorStatus,
    Entitlement,
    OperationResult,
    PagedResult,
)
from iga_connector.core.operations import Operation
from iga_connector.core.schema import (
    AttributeSchema,
    AttributeType,
    ConnectionConfigField,
    ConnectorSchema,
    ObjectSchema,
)
from iga_connector.handlers.account_handler import AccountHandler, EndpointSpec
from iga_connector.handlers.entitlement_handler import (
    EntitlementEndpointSpec,
    EntitlementHandler,
)
from iga_connector.registry import connector_registry
from iga_connector.transport.http_client import HttpTransport
from iga_connector.utils import setup_logging


# ---------------------------------------------------------------------------
# 1. Define your connector
# ---------------------------------------------------------------------------
@connector_registry.register("sample_hr")
class SampleHrConnector(BaseConnector):
    """Connector for the fictional 'Acme HR' REST API."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        conn = config["connection"]

        auth_cfg = config.get("auth")
        authenticator = (
            Authenticator.from_config(AuthConfig(**auth_cfg)) if auth_cfg else None
        )

        self.transport = HttpTransport(
            base_url=conn["base_url"],
            authenticator=authenticator,
            timeout=conn.get("timeout", 30),
        )

        # Map the Acme HR API's specific paths and field names
        self.account_handler = AccountHandler(
            self.transport,
            EndpointSpec(
                list_path="/api/employees",
                get_path="/api/employees/{identity}",
                create_path="/api/employees",
                update_path="/api/employees/{identity}",
                delete_path="/api/employees/{identity}",
                identity_field="employeeId",
                display_name_field="fullName",
                status_field="employmentStatus",
                status_mapping={
                    "employed": AccountStatus.ACTIVE,
                    "terminated": AccountStatus.DISABLED,
                },
                list_results_key="employees",
                list_total_key="total",
            ),
        )

        self.entitlement_handler = EntitlementHandler(
            self.transport,
            EntitlementEndpointSpec(
                list_path="/api/departments",
                get_path="/api/departments/{identity}",
                grant_path="/api/departments/{entitlement_id}/members",
                revoke_path="/api/departments/{entitlement_id}/members/{account_id}",
                identity_field="deptId",
                name_field="deptName",
            ),
        )

    async def connect(self) -> None:
        await self.transport.__aenter__()

    async def close(self) -> None:
        await self.transport.__aexit__(None, None, None)

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="sample_hr",
            display_name="Acme HR Connector",
            version="1.0.0",
            description="Sample connector for the Acme HR REST API",
            connection_config=[
                ConnectionConfigField(name="base_url", required=True),
            ],
            object_schemas=[
                ObjectSchema(
                    object_type="account",
                    identity_attribute="employeeId",
                    attributes=[
                        AttributeSchema(name="employeeId", required=True),
                        AttributeSchema(name="fullName", required=True),
                        AttributeSchema(name="email"),
                        AttributeSchema(name="department"),
                        AttributeSchema(
                            name="employmentStatus",
                            allowed_values=["employed", "terminated"],
                        ),
                    ],
                ),
            ],
            supported_operations=[op.value for op in Operation],
        )

    async def test_connection(self) -> ConnectorStatus:
        start = time.time()
        ok = await self.transport.health_check("/api/health")
        elapsed = (time.time() - start) * 1000
        return ConnectorStatus(
            connected=ok,
            message="Acme HR API reachable" if ok else "Connection failed",
            target_system=self.config["connection"]["base_url"],
            response_time_ms=elapsed,
        )

    async def create_account(self, account: Account) -> OperationResult:
        return await self.account_handler.create_account(account)

    async def update_account(self, identity: str, changes: dict[str, Any]) -> OperationResult:
        return await self.account_handler.update_account(identity, changes)

    async def delete_account(self, identity: str) -> OperationResult:
        return await self.account_handler.delete_account(identity)

    async def get_account(self, identity: str) -> Account | None:
        return await self.account_handler.get_account(identity)

    async def list_accounts(self, page_size: int = 50, cursor: str | None = None) -> PagedResult:
        return await self.account_handler.list_accounts(page_size, cursor)

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        return await self.entitlement_handler.list_entitlements(page_size, cursor)


# ---------------------------------------------------------------------------
# 2. Use the connector
# ---------------------------------------------------------------------------
async def main() -> None:
    setup_logging("INFO")

    config = {
        "connection": {
            "base_url": "https://hr-api.acme.example.com",
            "timeout": 15,
        },
        "auth": {
            "auth_type": "api_key",
            "params": {
                "api_key": "demo-key-12345",
                "header_name": "X-HR-Token",
            },
        },
    }

    # Using the registry
    connector = connector_registry.create("sample_hr", config)

    async with connector:
        # Test connectivity
        status = await connector.test_connection()
        print(f"Connected: {status.connected} – {status.message}")

        # List accounts (will fail against a fake URL, but shows the pattern)
        # accounts = await connector.list_accounts(page_size=10)
        # print(f"Found {len(accounts.items)} accounts")


if __name__ == "__main__":
    asyncio.run(main())
