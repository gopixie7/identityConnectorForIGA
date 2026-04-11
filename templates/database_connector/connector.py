"""Database Connector Template.

Connects to relational databases (PostgreSQL, MySQL, Oracle, SQL Server)
to manage user accounts and entitlements stored in tables.

Requires the `database` extra: pip install iga-connector-sdk[database]
"""

from __future__ import annotations

import time
from typing import Any

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
    ConnectionConfigField,
    ConnectorSchema,
    ObjectSchema,
)
from iga_connector.registry import connector_registry

try:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
except ImportError:
    raise ImportError(
        "Database connector requires sqlalchemy. "
        "Install with: pip install iga-connector-sdk[database]"
    )


@connector_registry.register("database")
class DatabaseConnector(BaseConnector):
    """Connector for relational database target systems."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        conn = config.get("connection", {})
        self.connection_string: str = conn["connection_string"]

        opts = config.get("options", {})
        self.accounts_table: str = opts.get("accounts_table", "users")
        self.entitlements_table: str = opts.get("entitlements_table", "roles")
        self.membership_table: str = opts.get("membership_table", "user_roles")
        self.identity_column: str = opts.get("identity_column", "id")
        self.username_column: str = opts.get("username_column", "username")
        self.status_column: str = opts.get("status_column", "status")
        self.display_name_column: str = opts.get("display_name_column", "display_name")

        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        self._engine = create_async_engine(self.connection_string, echo=False)

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._engine

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="database",
            display_name="Database Connector",
            version="1.0.0",
            description="Connector for relational database target systems",
            connection_config=[
                ConnectionConfigField(
                    name="connection_string",
                    required=True,
                    description="SQLAlchemy async connection string",
                ),
            ],
            object_schemas=[
                ObjectSchema(
                    object_type="account",
                    identity_attribute=self.identity_column,
                    attributes=[
                        AttributeSchema(name=self.identity_column, required=True),
                        AttributeSchema(name=self.username_column, required=True),
                        AttributeSchema(name=self.display_name_column),
                        AttributeSchema(name=self.status_column),
                    ],
                ),
                ObjectSchema(
                    object_type="entitlement",
                    identity_attribute="id",
                    attributes=[
                        AttributeSchema(name="id", required=True),
                        AttributeSchema(name="name", required=True),
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

    async def test_connection(self) -> ConnectorStatus:
        start = time.time()
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            elapsed = (time.time() - start) * 1000
            return ConnectorStatus(
                connected=True,
                message="Database reachable",
                target_system=self.connection_string.split("@")[-1] if "@" in self.connection_string else "database",
                response_time_ms=elapsed,
            )
        except Exception as exc:
            return ConnectorStatus(connected=False, message=str(exc))

    def _row_to_account(self, row: Any) -> Account:
        data = dict(row._mapping)
        raw_status = str(data.get(self.status_column, "active")).lower()
        status_map = {"active": AccountStatus.ACTIVE, "disabled": AccountStatus.DISABLED}
        return Account(
            identity=str(data[self.identity_column]),
            display_name=str(data.get(self.display_name_column, "")),
            status=status_map.get(raw_status, AccountStatus.UNKNOWN),
            attributes=data,
        )

    async def list_accounts(self, page_size: int = 50, cursor: str | None = None) -> PagedResult:
        offset = int(cursor) if cursor else 0
        query = text(
            f"SELECT * FROM {self.accounts_table} "
            f"ORDER BY {self.identity_column} LIMIT :limit OFFSET :offset"
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(query, {"limit": page_size, "offset": offset})
            rows = result.fetchall()
        accounts = [self._row_to_account(r) for r in rows]
        next_cursor = str(offset + page_size) if len(rows) == page_size else None
        return PagedResult(items=accounts, page_size=page_size, next_cursor=next_cursor)

    async def get_account(self, identity: str) -> Account | None:
        query = text(
            f"SELECT * FROM {self.accounts_table} WHERE {self.identity_column} = :id"
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(query, {"id": identity})
            row = result.fetchone()
        return self._row_to_account(row) if row else None

    async def create_account(self, account: Account) -> OperationResult:
        cols = [self.identity_column, self.username_column, self.display_name_column, self.status_column]
        vals = [account.identity, account.attributes.get(self.username_column, account.identity), account.display_name, account.status.value]
        placeholders = ", ".join(f":v{i}" for i in range(len(cols)))
        col_names = ", ".join(cols)
        query = text(f"INSERT INTO {self.accounts_table} ({col_names}) VALUES ({placeholders})")
        params = {f"v{i}": v for i, v in enumerate(vals)}
        async with self.engine.begin() as conn:
            await conn.execute(query, params)
        return OperationResult.ok("Account created in database")

    async def update_account(self, identity: str, changes: dict[str, Any]) -> OperationResult:
        set_clauses = ", ".join(f"{k} = :val_{k}" for k in changes)
        query = text(
            f"UPDATE {self.accounts_table} SET {set_clauses} "
            f"WHERE {self.identity_column} = :id"
        )
        params = {f"val_{k}": v for k, v in changes.items()}
        params["id"] = identity
        async with self.engine.begin() as conn:
            await conn.execute(query, params)
        return OperationResult.ok("Account updated in database")

    async def delete_account(self, identity: str) -> OperationResult:
        query = text(
            f"DELETE FROM {self.accounts_table} WHERE {self.identity_column} = :id"
        )
        async with self.engine.begin() as conn:
            await conn.execute(query, {"id": identity})
        return OperationResult.ok("Account deleted from database")

    async def disable_account(self, identity: str) -> OperationResult:
        return await self.update_account(identity, {self.status_column: "disabled"})

    async def enable_account(self, identity: str) -> OperationResult:
        return await self.update_account(identity, {self.status_column: "active"})

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        offset = int(cursor) if cursor else 0
        query = text(
            f"SELECT * FROM {self.entitlements_table} ORDER BY id LIMIT :limit OFFSET :offset"
        )
        async with self.engine.connect() as conn:
            result = await conn.execute(query, {"limit": page_size, "offset": offset})
            rows = result.fetchall()
        entitlements = [
            Entitlement(
                identity=str(dict(r._mapping)["id"]),
                name=str(dict(r._mapping).get("name", "")),
                entitlement_type="role",
                attributes=dict(r._mapping),
            )
            for r in rows
        ]
        next_cursor = str(offset + page_size) if len(rows) == page_size else None
        return PagedResult(items=entitlements, page_size=page_size, next_cursor=next_cursor)

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        query = text(
            f"INSERT INTO {self.membership_table} (user_id, role_id) VALUES (:uid, :rid)"
        )
        async with self.engine.begin() as conn:
            await conn.execute(query, {"uid": account_identity, "rid": entitlement_identity})
        return OperationResult.ok("Entitlement granted")

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        query = text(
            f"DELETE FROM {self.membership_table} WHERE user_id = :uid AND role_id = :rid"
        )
        async with self.engine.begin() as conn:
            await conn.execute(query, {"uid": account_identity, "rid": entitlement_identity})
        return OperationResult.ok("Entitlement revoked")
