"""Connector registry / factory.

Register connector classes by name so they can be instantiated
from configuration without hard-coding imports.

Usage:
    from iga_connector.registry import connector_registry

    # Register
    @connector_registry.register("my_rest_app")
    class MyRestConnector(BaseConnector): ...

    # Instantiate from config
    connector = connector_registry.create("my_rest_app", config_dict)
"""

from __future__ import annotations

from typing import Any

from .core.connector import BaseConnector
from .core.exceptions import ConfigurationError


class ConnectorRegistry:
    """Global registry that maps connector type names to their classes."""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseConnector]] = {}

    def register(
        self, name: str
    ):  # -> Callable[[type[BaseConnector]], type[BaseConnector]]
        """Decorator to register a connector class under a given name."""

        def decorator(cls: type[BaseConnector]) -> type[BaseConnector]:
            self._registry[name] = cls
            return cls

        return decorator

    def get(self, name: str) -> type[BaseConnector]:
        cls = self._registry.get(name)
        if cls is None:
            raise ConfigurationError(
                f"Unknown connector type '{name}'. "
                f"Registered types: {list(self._registry.keys())}"
            )
        return cls

    def create(self, name: str, config: dict[str, Any]) -> BaseConnector:
        """Instantiate a registered connector with the given config."""
        cls = self.get(name)
        return cls(config)

    def list_registered(self) -> list[str]:
        return list(self._registry.keys())


# Singleton instance
connector_registry = ConnectorRegistry()
