"""Custom exceptions for the IGA Connector SDK."""


class ConnectorError(Exception):
    """Base exception for all connector errors."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class AuthenticationError(ConnectorError):
    """Raised when authentication to the target system fails."""


class ConnectionError(ConnectorError):
    """Raised when the connection to the target system cannot be established."""


class OperationError(ConnectorError):
    """Raised when a provisioning or reconciliation operation fails."""

    def __init__(
        self, message: str, operation: str | None = None, cause: Exception | None = None
    ):
        super().__init__(message, cause)
        self.operation = operation


class SchemaError(ConnectorError):
    """Raised when there is a schema definition or validation error."""


class ConfigurationError(ConnectorError):
    """Raised when connector configuration is invalid or missing."""
