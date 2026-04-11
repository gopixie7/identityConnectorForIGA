"""Configuration management for connectors.

Supports loading configuration from YAML files, JSON files,
environment variables, or plain dicts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..core.exceptions import ConfigurationError


class ConnectorConfig(BaseModel):
    """Top-level configuration for a connector instance."""

    connector_type: str = Field(description="Registered connector type, e.g. 'rest', 'scim'")
    name: str = Field(default="", description="Human-readable name for this connector instance")
    connection: dict[str, Any] = Field(
        default_factory=dict,
        description="Connection settings: base_url, auth, timeouts, etc.",
    )
    auth: dict[str, Any] = Field(
        default_factory=dict,
        description="Authentication configuration",
    )
    schema_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Override or extend the default schema",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra connector-specific options",
    )


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ${ENV_VAR} placeholders in config values."""
    if isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        var_name = data[2:-1]
        value = os.environ.get(var_name)
        if value is None:
            raise ConfigurationError(f"Environment variable '{var_name}' is not set")
        return value
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    return data


def load_config(source: str | Path | dict[str, Any]) -> ConnectorConfig:
    """Load connector configuration from a file path, dict, or env-resolved YAML/JSON.

    Examples:
        config = load_config("connector.yaml")
        config = load_config({"connector_type": "rest", "connection": {...}})
    """
    if isinstance(source, dict):
        resolved = _resolve_env_vars(source)
        return ConnectorConfig(**resolved)

    path = Path(source)
    if not path.exists():
        raise ConfigurationError(f"Config file not found: {path}")

    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    elif path.suffix == ".json":
        raw = json.loads(text)
    else:
        raise ConfigurationError(f"Unsupported config format: {path.suffix}")

    resolved = _resolve_env_vars(raw)
    return ConnectorConfig(**resolved)
