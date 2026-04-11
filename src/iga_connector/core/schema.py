"""Schema definitions for connector attributes and object types."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AttributeType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    LIST = "list"
    OBJECT = "object"
    SECRET = "secret"


class AttributeSchema(BaseModel):
    """Schema for a single attribute on a target system object."""

    name: str
    display_name: str = ""
    attr_type: AttributeType = AttributeType.STRING
    required: bool = False
    multi_valued: bool = False
    readonly: bool = False
    description: str = ""
    default: Any = None
    allowed_values: list[Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()


class ObjectSchema(BaseModel):
    """Schema for a target system object type (account, entitlement, etc.)."""

    object_type: str = Field(description="e.g. 'account', 'entitlement', 'group'")
    display_name: str = ""
    identity_attribute: str = Field(
        default="id",
        description="Attribute used as the unique identifier",
    )
    attributes: list[AttributeSchema] = Field(default_factory=list)

    def get_attribute(self, name: str) -> AttributeSchema | None:
        return next((a for a in self.attributes if a.name == name), None)

    def required_attributes(self) -> list[AttributeSchema]:
        return [a for a in self.attributes if a.required]


class ConnectionConfigField(BaseModel):
    """Schema for a connection configuration parameter."""

    name: str
    display_name: str = ""
    field_type: AttributeType = AttributeType.STRING
    required: bool = True
    description: str = ""
    default: Any = None

    def model_post_init(self, __context: Any) -> None:
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()


class ConnectorSchema(BaseModel):
    """Full schema definition for a connector.

    This tells the IGA platform what configuration the connector needs,
    what object types it manages, and what operations it supports.
    """

    connector_name: str
    display_name: str = ""
    version: str = "1.0.0"
    description: str = ""
    connection_config: list[ConnectionConfigField] = Field(default_factory=list)
    object_schemas: list[ObjectSchema] = Field(default_factory=list)
    supported_operations: list[str] = Field(default_factory=list)

    def get_object_schema(self, object_type: str) -> ObjectSchema | None:
        return next((s for s in self.object_schemas if s.object_type == object_type), None)
