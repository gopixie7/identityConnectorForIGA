"""REST API Connector Template.

This template connects to any target system that exposes a REST API
for user/account and entitlement management.

Quick start:
    1. Copy this file into your project.
    2. Update the endpoint specs and schema to match your target system.
    3. Register the connector and run it.
"""

from __future__ import annotations

import time
from typing import Any

from iga_connector.auth.authenticator import AuthConfig, Authenticator
from iga_connector.core.connector import BaseConnector
from iga_connector.core.models import (
    Account,
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


@connector_registry.register("rest")
class RestConnector(BaseConnector):
    """Generic REST API connector.

    Works out of the box for target systems that follow common REST conventions.
    Customize by adjusting the EndpointSpec and schema in __init__.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        # ---- connection ---------------------------------------------------
        conn = config.get("connection", {})
        self.base_url: str = conn["base_url"]

        # ---- auth ---------------------------------------------------------
        auth_cfg = config.get("auth", {})
        self.authenticator: Authenticator | None = None
        if auth_cfg:
            self.authenticator = Authenticator.from_config(AuthConfig(**auth_cfg))

        # ---- transport ----------------------------------------------------
        self.transport = HttpTransport(
            base_url=self.base_url,
            authenticator=self.authenticator,
            timeout=conn.get("timeout", 30),
            verify_ssl=conn.get("verify_ssl", True),
        )

        # ---- endpoint specs (customise these for your target) -------------
        opts = config.get("options", {})
        acct_opts = opts.get("account_endpoint", {})
        ent_opts = opts.get("entitlement_endpoint", {})

        self.account_handler = AccountHandler(
            self.transport, EndpointSpec(**acct_opts)
        )
        self.entitlement_handler = EntitlementHandler(
            self.transport, EntitlementEndpointSpec(**ent_opts)
        )

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        await self.transport.__aenter__()

    async def close(self) -> None:
        await self.transport.__aexit__(None, None, None)

    # -- schema -------------------------------------------------------------

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="rest",
            display_name="REST API Connector",
            version="1.0.0",
            description="Generic connector for REST-based target systems",
            connection_config=[
                ConnectionConfigField(
                    name="base_url", required=True, description="Base URL of the target API"
                ),
                ConnectionConfigField(
                    name="timeout",
                    field_type=AttributeType.INTEGER,
                    required=False,
                    default=30,
                ),
            ],
            object_schemas=[
                ObjectSchema(
                    object_type="account",
                    identity_attribute="id",
                    attributes=[
                        AttributeSchema(name="id", required=True),
                        AttributeSchema(name="username", required=True),
                        AttributeSchema(name="email", attr_type=AttributeType.STRING),
                        AttributeSchema(name="first_name"),
                        AttributeSchema(name="last_name"),
                        AttributeSchema(
                            name="status",
                            allowed_values=["active", "disabled", "locked"],
                        ),
                    ],
                ),
                ObjectSchema(
                    object_type="entitlement",
                    identity_attribute="id",
                    attributes=[
                        AttributeSchema(name="id", required=True),
                        AttributeSchema(name="name", required=True),
                        AttributeSchema(name="description"),
                    ],
                ),
            ],
            supported_operations=[op.value for op in Operation],
        )

    # -- connection test ----------------------------------------------------

    async def test_connection(self) -> ConnectorStatus:
        start = time.time()
        ok = await self.transport.health_check(
            self.config.get("options", {}).get("health_path", "/")
        )
        elapsed = (time.time() - start) * 1000
        return ConnectorStatus(
            connected=ok,
            message="Connection successful" if ok else "Connection failed",
            target_system=self.base_url,
            response_time_ms=elapsed,
        )

    # -- account delegates --------------------------------------------------

    async def create_account(self, account: Account) -> OperationResult:
        return await self.account_handler.create_account(account)

    async def update_account(self, identity: str, changes: dict[str, Any]) -> OperationResult:
        return await self.account_handler.update_account(identity, changes)

    async def delete_account(self, identity: str) -> OperationResult:
        return await self.account_handler.delete_account(identity)

    async def disable_account(self, identity: str) -> OperationResult:
        return await self.account_handler.disable_account(identity)

    async def enable_account(self, identity: str) -> OperationResult:
        return await self.account_handler.enable_account(identity)

    async def get_account(self, identity: str) -> Account | None:
        return await self.account_handler.get_account(identity)

    async def list_accounts(self, page_size: int = 50, cursor: str | None = None) -> PagedResult:
        return await self.account_handler.list_accounts(page_size, cursor)

    # -- entitlement delegates ----------------------------------------------

    async def get_entitlement(self, identity: str) -> Entitlement | None:
        return await self.entitlement_handler.get_entitlement(identity)

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        return await self.entitlement_handler.list_entitlements(page_size, cursor)

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        return await self.entitlement_handler.grant_entitlement(
            account_identity, entitlement_identity
        )

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        return await self.entitlement_handler.revoke_entitlement(
            account_identity, entitlement_identity
        )
