"""SCIM 2.0 Connector Template.

Connects to any SCIM-compliant target system (Azure AD, Okta, etc.)
using the standard /Users and /Groups endpoints.

SCIM RFC: https://datatracker.ietf.org/doc/html/rfc7644
"""

from __future__ import annotations

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
from iga_connector.registry import connector_registry
from iga_connector.transport.http_client import HttpTransport


@connector_registry.register("scim")
class ScimConnector(BaseConnector):
    """SCIM 2.0 connector for identity provisioning."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        conn = config.get("connection", {})
        self.base_url: str = conn["base_url"].rstrip("/")

        auth_cfg = config.get("auth", {})
        authenticator = Authenticator.from_config(AuthConfig(**auth_cfg)) if auth_cfg else None

        self.transport = HttpTransport(
            base_url=self.base_url,
            authenticator=authenticator,
            timeout=conn.get("timeout", 30),
            headers={"Content-Type": "application/scim+json"},
            verify_ssl=conn.get("verify_ssl", True),
        )

    async def connect(self) -> None:
        await self.transport.__aenter__()

    async def close(self) -> None:
        await self.transport.__aexit__(None, None, None)

    # -- schema --

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="scim",
            display_name="SCIM 2.0 Connector",
            version="1.0.0",
            description="Connector for SCIM 2.0 compliant systems",
            connection_config=[
                ConnectionConfigField(name="base_url", required=True),
            ],
            object_schemas=[
                ObjectSchema(
                    object_type="account",
                    identity_attribute="id",
                    attributes=[
                        AttributeSchema(name="id", required=True, readonly=True),
                        AttributeSchema(name="userName", required=True),
                        AttributeSchema(name="displayName"),
                        AttributeSchema(name="name.givenName"),
                        AttributeSchema(name="name.familyName"),
                        AttributeSchema(name="emails", multi_valued=True),
                        AttributeSchema(name="active", attr_type=AttributeType.BOOLEAN),
                    ],
                ),
                ObjectSchema(
                    object_type="entitlement",
                    identity_attribute="id",
                    attributes=[
                        AttributeSchema(name="id", required=True, readonly=True),
                        AttributeSchema(name="displayName", required=True),
                        AttributeSchema(name="members", multi_valued=True),
                    ],
                ),
            ],
            supported_operations=[
                Operation.TEST_CONNECTION.value,
                Operation.CREATE_ACCOUNT.value,
                Operation.UPDATE_ACCOUNT.value,
                Operation.DELETE_ACCOUNT.value,
                Operation.DISABLE_ACCOUNT.value,
                Operation.ENABLE_ACCOUNT.value,
                Operation.GET_ACCOUNT.value,
                Operation.LIST_ACCOUNTS.value,
                Operation.LIST_ENTITLEMENTS.value,
                Operation.GRANT_ENTITLEMENT.value,
                Operation.REVOKE_ENTITLEMENT.value,
            ],
        )

    # -- connection test --

    async def test_connection(self) -> ConnectorStatus:
        start = time.time()
        try:
            await self.transport.get("/ServiceProviderConfig")
            elapsed = (time.time() - start) * 1000
            return ConnectorStatus(
                connected=True,
                message="SCIM service reachable",
                target_system=self.base_url,
                response_time_ms=elapsed,
            )
        except Exception as exc:
            return ConnectorStatus(connected=False, message=str(exc))

    # -- helpers --

    def _parse_scim_user(self, data: dict[str, Any]) -> Account:
        active = data.get("active", True)
        return Account(
            identity=data["id"],
            display_name=data.get("displayName", data.get("userName", "")),
            status=AccountStatus.ACTIVE if active else AccountStatus.DISABLED,
            attributes=data,
        )

    def _build_scim_user(self, account: Account) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": account.attributes.get("userName", account.identity),
            "displayName": account.display_name,
            "active": account.status == AccountStatus.ACTIVE,
        }
        for key in ("name", "emails", "phoneNumbers"):
            if key in account.attributes:
                payload[key] = account.attributes[key]
        return payload

    # -- account operations --

    async def create_account(self, account: Account) -> OperationResult:
        payload = self._build_scim_user(account)
        data = await self.transport.post("/Users", json=payload)
        return OperationResult.ok("SCIM user created", id=data.get("id"))

    async def update_account(self, identity: str, changes: dict[str, Any]) -> OperationResult:
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            **changes,
        }
        await self.transport.put(f"/Users/{identity}", json=payload)
        return OperationResult.ok("SCIM user updated")

    async def delete_account(self, identity: str) -> OperationResult:
        await self.transport.delete(f"/Users/{identity}")
        return OperationResult.ok("SCIM user deleted")

    async def disable_account(self, identity: str) -> OperationResult:
        return await self.update_account(identity, {"active": False})

    async def enable_account(self, identity: str) -> OperationResult:
        return await self.update_account(identity, {"active": True})

    async def get_account(self, identity: str) -> Account | None:
        try:
            data = await self.transport.get(f"/Users/{identity}")
            return self._parse_scim_user(data)
        except Exception:
            return None

    async def list_accounts(self, page_size: int = 50, cursor: str | None = None) -> PagedResult:
        params: dict[str, Any] = {"count": page_size}
        if cursor:
            params["startIndex"] = int(cursor)
        data = await self.transport.get("/Users", params=params)
        resources = data.get("Resources", [])
        total = data.get("totalResults")
        accounts = [self._parse_scim_user(r) for r in resources]
        start_index = data.get("startIndex", 1)
        next_cursor = str(start_index + page_size) if len(resources) == page_size else None
        return PagedResult(
            items=accounts, total_count=total, page_size=page_size, next_cursor=next_cursor
        )

    # -- entitlement operations --

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        params: dict[str, Any] = {"count": page_size}
        if cursor:
            params["startIndex"] = int(cursor)
        data = await self.transport.get("/Groups", params=params)
        resources = data.get("Resources", [])
        entitlements = [
            Entitlement(
                identity=r["id"],
                name=r.get("displayName", ""),
                entitlement_type="group",
                attributes=r,
            )
            for r in resources
        ]
        start_index = data.get("startIndex", 1)
        next_cursor = str(start_index + page_size) if len(resources) == page_size else None
        return PagedResult(items=entitlements, page_size=page_size, next_cursor=next_cursor)

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        patch = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": account_identity}],
                }
            ],
        }
        await self.transport.patch(f"/Groups/{entitlement_identity}", json=patch)
        return OperationResult.ok("Member added to SCIM group")

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        patch = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "remove",
                    "path": f'members[value eq "{account_identity}"]',
                }
            ],
        }
        await self.transport.patch(f"/Groups/{entitlement_identity}", json=patch)
        return OperationResult.ok("Member removed from SCIM group")
