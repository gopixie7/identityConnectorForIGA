"""Base connector interface that all IGA connectors must implement."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from .models import Account, ConnectorStatus, Entitlement, OperationResult, PagedResult
from .operations import Operation
from .schema import ConnectorSchema

logger = logging.getLogger("iga_connector")


class BaseConnector(ABC):
    """Abstract base class for all IGA connectors.

    Subclass this to build a connector for any target system.
    Override only the operations your target system supports.

    Lifecycle:
        1. __init__  – receive configuration
        2. connect   – open a session / authenticate
        3. operations (create_account, list_accounts, …)
        4. close     – tear down the session

    Usage:
        async with MyConnector(config) as connector:
            status = await connector.test_connection()
            accounts = await connector.list_accounts()
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.logger = logging.getLogger(f"iga_connector.{self.__class__.__name__}")

    # --- lifecycle -------------------------------------------------------

    async def connect(self) -> None:
        """Open a connection / session to the target system.

        Called automatically when entering the async-with block.
        Override to perform authentication handshakes, token exchange, etc.
        """

    async def close(self) -> None:
        """Release resources held by the connector.

        Called automatically when exiting the async-with block.
        """

    async def __aenter__(self) -> BaseConnector:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # --- metadata --------------------------------------------------------

    @abstractmethod
    def get_schema(self) -> ConnectorSchema:
        """Return the full schema definition for this connector."""

    def supported_operations(self) -> list[Operation]:
        """Return the list of operations this connector supports.

        The default implementation inspects the schema's supported_operations list.
        """
        schema = self.get_schema()
        return [Operation(op) for op in schema.supported_operations]

    # --- connection test -------------------------------------------------

    @abstractmethod
    async def test_connection(self) -> ConnectorStatus:
        """Verify connectivity and credentials against the target system."""

    # --- account operations ----------------------------------------------

    async def create_account(self, account: Account) -> OperationResult:
        """Create a new account on the target system."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support create_account")

    async def update_account(
        self, identity: str, changes: dict[str, Any]
    ) -> OperationResult:
        """Update attributes on an existing account."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support update_account")

    async def delete_account(self, identity: str) -> OperationResult:
        """Delete (or deprovision) an account from the target system."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support delete_account")

    async def disable_account(self, identity: str) -> OperationResult:
        """Disable an account on the target system."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support disable_account")

    async def enable_account(self, identity: str) -> OperationResult:
        """Enable a previously disabled account."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support enable_account")

    async def get_account(self, identity: str) -> Account | None:
        """Retrieve a single account by its identity."""
        return None

    async def list_accounts(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        """List accounts from the target system with pagination."""
        return PagedResult(items=[], total_count=0, page_size=page_size)

    # --- entitlement operations ------------------------------------------

    async def get_entitlement(self, identity: str) -> Entitlement | None:
        """Retrieve a single entitlement by its identity."""
        return None

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        """List entitlements from the target system with pagination."""
        return PagedResult(items=[], total_count=0, page_size=page_size)

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        """Grant an entitlement to an account."""
        return OperationResult.fail(
            f"{self.__class__.__name__} does not support grant_entitlement"
        )

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        """Revoke an entitlement from an account."""
        return OperationResult.fail(
            f"{self.__class__.__name__} does not support revoke_entitlement"
        )

    # --- password operations ---------------------------------------------

    async def set_password(self, identity: str, new_password: str) -> OperationResult:
        """Set password for an account."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support set_password")

    async def reset_password(self, identity: str) -> OperationResult:
        """Trigger a password reset for an account."""
        return OperationResult.fail(f"{self.__class__.__name__} does not support reset_password")

    # --- reconciliation --------------------------------------------------

    async def full_reconciliation(self) -> list[Account]:
        """Perform a full reconciliation – return all accounts on the target."""
        result = await self.list_accounts(page_size=500)
        accounts: list[Account] = result.items  # type: ignore[assignment]
        while result.next_cursor:
            result = await self.list_accounts(page_size=500, cursor=result.next_cursor)
            accounts.extend(result.items)  # type: ignore[arg-type]
        return accounts

    async def incremental_reconciliation(
        self, since: str | None = None
    ) -> list[Account]:
        """Return accounts modified since the given checkpoint.

        Override this to implement delta-based reconciliation.
        Falls back to full_reconciliation by default.
        """
        return await self.full_reconciliation()
