"""Standard IGA operations supported by connectors."""

from enum import Enum


class Operation(str, Enum):
    """Standard operations that a connector can support.

    Not all connectors need to implement every operation.
    The connector's `supported_operations` method declares what it supports.
    """

    # Connection
    TEST_CONNECTION = "test_connection"

    # Account operations
    CREATE_ACCOUNT = "create_account"
    UPDATE_ACCOUNT = "update_account"
    DELETE_ACCOUNT = "delete_account"
    DISABLE_ACCOUNT = "disable_account"
    ENABLE_ACCOUNT = "enable_account"
    GET_ACCOUNT = "get_account"
    LIST_ACCOUNTS = "list_accounts"

    # Entitlement operations
    GET_ENTITLEMENT = "get_entitlement"
    LIST_ENTITLEMENTS = "list_entitlements"
    GRANT_ENTITLEMENT = "grant_entitlement"
    REVOKE_ENTITLEMENT = "revoke_entitlement"

    # Password operations
    SET_PASSWORD = "set_password"
    RESET_PASSWORD = "reset_password"

    # Reconciliation
    FULL_RECONCILIATION = "full_reconciliation"
    INCREMENTAL_RECONCILIATION = "incremental_reconciliation"
