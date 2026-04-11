"""Data models for the IGA Connector SDK."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AccountStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class Account(BaseModel):
    """Represents a user account on a target system."""

    identity: str = Field(description="Unique identifier on the target system")
    display_name: str = Field(default="", description="Human-readable display name")
    status: AccountStatus = Field(default=AccountStatus.ACTIVE)
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Target-system-specific attributes",
    )
    entitlements: list[str] = Field(
        default_factory=list,
        description="List of entitlement IDs assigned to this account",
    )
    created_at: datetime | None = None
    modified_at: datetime | None = None


class Entitlement(BaseModel):
    """Represents an entitlement (role, group, permission) on a target system."""

    identity: str = Field(description="Unique identifier of the entitlement")
    name: str = Field(description="Human-readable name")
    entitlement_type: str = Field(
        default="group",
        description="Type of entitlement: group, role, permission, license, etc.",
    )
    description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)


class OperationResult(BaseModel):
    """Result of a connector operation."""

    success: bool
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    @classmethod
    def ok(cls, message: str = "OK", **data: Any) -> OperationResult:
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str, errors: list[str] | None = None) -> OperationResult:
        return cls(success=False, message=message, errors=errors or [message])


class ConnectorStatus(BaseModel):
    """Health / connectivity status returned by test_connection."""

    connected: bool
    message: str = ""
    target_system: str = ""
    response_time_ms: float | None = None


class PagedResult(BaseModel):
    """Paginated result set for list operations."""

    items: list[Account] | list[Entitlement]
    total_count: int | None = None
    next_cursor: str | None = None
    page_size: int = 50
