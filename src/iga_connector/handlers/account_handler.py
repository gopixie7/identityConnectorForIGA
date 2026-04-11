"""Reusable account CRUD handler for REST-based connectors.

This handler provides a configurable, spec-driven approach to account
management. Instead of writing custom code for every target system,
you define an endpoint specification and the handler does the rest.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.models import Account, AccountStatus, OperationResult, PagedResult
from ..transport.http_client import HttpTransport

logger = logging.getLogger("iga_connector.handlers.account")


class EndpointSpec:
    """Describes how the target system's REST API maps to account operations."""

    def __init__(
        self,
        list_path: str = "/users",
        get_path: str = "/users/{identity}",
        create_path: str = "/users",
        update_path: str = "/users/{identity}",
        delete_path: str = "/users/{identity}",
        disable_path: str | None = None,
        enable_path: str | None = None,
        identity_field: str = "id",
        display_name_field: str = "name",
        status_field: str = "status",
        status_mapping: dict[str, AccountStatus] | None = None,
        list_results_key: str | None = None,
        list_total_key: str | None = None,
        page_param: str = "page",
        page_size_param: str = "pageSize",
    ) -> None:
        self.list_path = list_path
        self.get_path = get_path
        self.create_path = create_path
        self.update_path = update_path
        self.delete_path = delete_path
        self.disable_path = disable_path
        self.enable_path = enable_path
        self.identity_field = identity_field
        self.display_name_field = display_name_field
        self.status_field = status_field
        self.status_mapping = status_mapping or {
            "active": AccountStatus.ACTIVE,
            "disabled": AccountStatus.DISABLED,
            "locked": AccountStatus.LOCKED,
        }
        self.list_results_key = list_results_key
        self.list_total_key = list_total_key
        self.page_param = page_param
        self.page_size_param = page_size_param


class AccountHandler:
    """Handles account CRUD operations against a REST target system.

    Uses an EndpointSpec to know which API paths and field names to use.
    """

    def __init__(self, transport: HttpTransport, spec: EndpointSpec) -> None:
        self.transport = transport
        self.spec = spec

    def _parse_account(self, data: dict[str, Any]) -> Account:
        raw_status = str(data.get(self.spec.status_field, "active")).lower()
        status = self.spec.status_mapping.get(raw_status, AccountStatus.UNKNOWN)
        return Account(
            identity=str(data[self.spec.identity_field]),
            display_name=str(data.get(self.spec.display_name_field, "")),
            status=status,
            attributes=data,
        )

    async def list_accounts(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        params: dict[str, Any] = {self.spec.page_size_param: page_size}
        if cursor:
            params[self.spec.page_param] = cursor

        data = await self.transport.get(self.spec.list_path, params=params)

        if self.spec.list_results_key and isinstance(data, dict):
            items_raw = data.get(self.spec.list_results_key, [])
            total = data.get(self.spec.list_total_key) if self.spec.list_total_key else None
        elif isinstance(data, list):
            items_raw = data
            total = None
        else:
            items_raw = data if isinstance(data, list) else []
            total = None

        accounts = [self._parse_account(item) for item in items_raw]
        return PagedResult(items=accounts, total_count=total, page_size=page_size)

    async def get_account(self, identity: str) -> Account | None:
        try:
            path = self.spec.get_path.format(identity=identity)
            data = await self.transport.get(path)
            return self._parse_account(data)
        except Exception as exc:
            logger.debug("get_account(%s) failed: %s", identity, exc)
            return None

    async def create_account(self, account: Account) -> OperationResult:
        payload = {
            self.spec.identity_field: account.identity,
            self.spec.display_name_field: account.display_name,
            **account.attributes,
        }
        data = await self.transport.post(self.spec.create_path, json=payload)
        return OperationResult.ok("Account created", **data)

    async def update_account(
        self, identity: str, changes: dict[str, Any]
    ) -> OperationResult:
        path = self.spec.update_path.format(identity=identity)
        data = await self.transport.patch(path, json=changes)
        return OperationResult.ok("Account updated", **data)

    async def delete_account(self, identity: str) -> OperationResult:
        path = self.spec.delete_path.format(identity=identity)
        await self.transport.delete(path)
        return OperationResult.ok("Account deleted")

    async def disable_account(self, identity: str) -> OperationResult:
        if self.spec.disable_path:
            path = self.spec.disable_path.format(identity=identity)
            await self.transport.post(path)
            return OperationResult.ok("Account disabled")
        return await self.update_account(identity, {self.spec.status_field: "disabled"})

    async def enable_account(self, identity: str) -> OperationResult:
        if self.spec.enable_path:
            path = self.spec.enable_path.format(identity=identity)
            await self.transport.post(path)
            return OperationResult.ok("Account enabled")
        return await self.update_account(identity, {self.spec.status_field: "active"})
