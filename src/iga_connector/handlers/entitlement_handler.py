"""Reusable entitlement handler for REST-based connectors."""

from __future__ import annotations

import logging
from typing import Any

from ..core.models import Entitlement, OperationResult, PagedResult
from ..transport.http_client import HttpTransport

logger = logging.getLogger("iga_connector.handlers.entitlement")


class EntitlementEndpointSpec:
    """Describes how the target system exposes entitlement (role/group) APIs."""

    def __init__(
        self,
        list_path: str = "/groups",
        get_path: str = "/groups/{identity}",
        grant_path: str = "/groups/{entitlement_id}/members",
        revoke_path: str = "/groups/{entitlement_id}/members/{account_id}",
        identity_field: str = "id",
        name_field: str = "name",
        description_field: str = "description",
        type_field: str | None = None,
        list_results_key: str | None = None,
        page_param: str = "page",
        page_size_param: str = "pageSize",
    ) -> None:
        self.list_path = list_path
        self.get_path = get_path
        self.grant_path = grant_path
        self.revoke_path = revoke_path
        self.identity_field = identity_field
        self.name_field = name_field
        self.description_field = description_field
        self.type_field = type_field
        self.list_results_key = list_results_key
        self.page_param = page_param
        self.page_size_param = page_size_param


class EntitlementHandler:
    """Handles entitlement operations against a REST target system."""

    def __init__(self, transport: HttpTransport, spec: EntitlementEndpointSpec) -> None:
        self.transport = transport
        self.spec = spec

    def _parse_entitlement(self, data: dict[str, Any]) -> Entitlement:
        return Entitlement(
            identity=str(data[self.spec.identity_field]),
            name=str(data.get(self.spec.name_field, "")),
            description=str(data.get(self.spec.description_field, "")),
            entitlement_type=str(data.get(self.spec.type_field, "group"))
            if self.spec.type_field
            else "group",
            attributes=data,
        )

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        params: dict[str, Any] = {self.spec.page_size_param: page_size}
        if cursor:
            params[self.spec.page_param] = cursor

        data = await self.transport.get(self.spec.list_path, params=params)

        if self.spec.list_results_key and isinstance(data, dict):
            items_raw = data.get(self.spec.list_results_key, [])
        elif isinstance(data, list):
            items_raw = data
        else:
            items_raw = []

        entitlements = [self._parse_entitlement(item) for item in items_raw]
        return PagedResult(items=entitlements, page_size=page_size)

    async def get_entitlement(self, identity: str) -> Entitlement | None:
        try:
            path = self.spec.get_path.format(identity=identity)
            data = await self.transport.get(path)
            return self._parse_entitlement(data)
        except Exception as exc:
            logger.debug("get_entitlement(%s) failed: %s", identity, exc)
            return None

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        path = self.spec.grant_path.format(entitlement_id=entitlement_identity)
        await self.transport.post(path, json={"member": account_identity})
        return OperationResult.ok("Entitlement granted")

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        path = self.spec.revoke_path.format(
            entitlement_id=entitlement_identity,
            account_id=account_identity,
        )
        await self.transport.delete(path)
        return OperationResult.ok("Entitlement revoked")
