"""LDAP / Active Directory Connector Template.

Connects to LDAP-compliant directories (Active Directory, OpenLDAP,
389 Directory Server) for user and group management.
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
    import ldap
    from ldap.ldapobject import LDAPObject
except ImportError:
    ldap = None  # type: ignore[assignment]
    LDAPObject = None  # type: ignore[assignment,misc]


@connector_registry.register("ldap")
class LdapConnector(BaseConnector):
    """Connector for LDAP / Active Directory target systems.

    Note: LDAP operations are synchronous; async wrappers are thin.
    For production use, consider running LDAP calls in a thread executor.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        if ldap is None:
            raise ImportError("python-ldap is required for the LDAP connector")

        conn = config.get("connection", {})
        self.ldap_url: str = conn["ldap_url"]
        self.bind_dn: str = conn.get("bind_dn", "")
        self.bind_password: str = conn.get("bind_password", "")
        self.use_ssl: bool = conn.get("use_ssl", True)

        opts = config.get("options", {})
        self.users_base_dn: str = opts["users_base_dn"]
        self.groups_base_dn: str = opts["groups_base_dn"]
        self.user_object_class: str = opts.get("user_object_class", "inetOrgPerson")
        self.group_object_class: str = opts.get("group_object_class", "groupOfNames")
        self.user_id_attr: str = opts.get("user_id_attr", "uid")
        self.user_display_attr: str = opts.get("user_display_attr", "cn")
        self.group_id_attr: str = opts.get("group_id_attr", "cn")
        self.member_attr: str = opts.get("member_attr", "member")

        self._conn: Any = None

    async def connect(self) -> None:
        self._conn = ldap.initialize(self.ldap_url)
        if self.use_ssl:
            self._conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
        self._conn.simple_bind_s(self.bind_dn, self.bind_password)

    async def close(self) -> None:
        if self._conn:
            self._conn.unbind_s()
            self._conn = None

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="ldap",
            display_name="LDAP / Active Directory Connector",
            version="1.0.0",
            description="Connector for LDAP-compliant directory services",
            connection_config=[
                ConnectionConfigField(name="ldap_url", required=True, description="e.g. ldaps://ldap.example.com:636"),
                ConnectionConfigField(name="bind_dn", required=True),
                ConnectionConfigField(name="bind_password", required=True),
            ],
            object_schemas=[
                ObjectSchema(
                    object_type="account",
                    identity_attribute=self.user_id_attr,
                    attributes=[
                        AttributeSchema(name="uid", required=True),
                        AttributeSchema(name="cn", required=True),
                        AttributeSchema(name="sn"),
                        AttributeSchema(name="givenName"),
                        AttributeSchema(name="mail"),
                        AttributeSchema(name="userPassword"),
                    ],
                ),
                ObjectSchema(
                    object_type="entitlement",
                    identity_attribute=self.group_id_attr,
                    attributes=[
                        AttributeSchema(name="cn", required=True),
                        AttributeSchema(name="description"),
                        AttributeSchema(name="member", multi_valued=True),
                    ],
                ),
            ],
            supported_operations=[
                Operation.TEST_CONNECTION.value,
                Operation.CREATE_ACCOUNT.value,
                Operation.DELETE_ACCOUNT.value,
                Operation.GET_ACCOUNT.value,
                Operation.LIST_ACCOUNTS.value,
                Operation.LIST_ENTITLEMENTS.value,
                Operation.GRANT_ENTITLEMENT.value,
                Operation.REVOKE_ENTITLEMENT.value,
                Operation.SET_PASSWORD.value,
            ],
        )

    async def test_connection(self) -> ConnectorStatus:
        start = time.time()
        try:
            self._conn.search_s(self.users_base_dn, ldap.SCOPE_BASE, "(objectClass=*)")
            elapsed = (time.time() - start) * 1000
            return ConnectorStatus(
                connected=True,
                message="LDAP bind successful",
                target_system=self.ldap_url,
                response_time_ms=elapsed,
            )
        except Exception as exc:
            return ConnectorStatus(connected=False, message=str(exc))

    def _dn_for_user(self, identity: str) -> str:
        return f"{self.user_id_attr}={identity},{self.users_base_dn}"

    def _dn_for_group(self, identity: str) -> str:
        return f"{self.group_id_attr}={identity},{self.groups_base_dn}"

    def _parse_ldap_user(self, dn: str, attrs: dict[str, list[bytes]]) -> Account:
        def _get(key: str) -> str:
            vals = attrs.get(key, [])
            return vals[0].decode("utf-8") if vals else ""

        return Account(
            identity=_get(self.user_id_attr),
            display_name=_get(self.user_display_attr),
            status=AccountStatus.ACTIVE,
            attributes={k: [v.decode() for v in vs] for k, vs in attrs.items()},
        )

    async def list_accounts(self, page_size: int = 50, cursor: str | None = None) -> PagedResult:
        search_filter = f"(objectClass={self.user_object_class})"
        results = self._conn.search_s(self.users_base_dn, ldap.SCOPE_SUBTREE, search_filter)
        accounts = [self._parse_ldap_user(dn, attrs) for dn, attrs in results if dn]
        return PagedResult(items=accounts, total_count=len(accounts), page_size=page_size)

    async def get_account(self, identity: str) -> Account | None:
        try:
            dn = self._dn_for_user(identity)
            results = self._conn.search_s(dn, ldap.SCOPE_BASE, "(objectClass=*)")
            if results:
                return self._parse_ldap_user(results[0][0], results[0][1])
        except Exception:
            pass
        return None

    async def create_account(self, account: Account) -> OperationResult:
        dn = self._dn_for_user(account.identity)
        attrs_list = [
            ("objectClass", [self.user_object_class.encode(), b"top"]),
            (self.user_id_attr, [account.identity.encode()]),
            (self.user_display_attr, [account.display_name.encode()]),
        ]
        for key, value in account.attributes.items():
            if key not in (self.user_id_attr, self.user_display_attr, "objectClass"):
                if isinstance(value, list):
                    attrs_list.append((key, [v.encode() if isinstance(v, str) else v for v in value]))
                elif isinstance(value, str):
                    attrs_list.append((key, [value.encode()]))
        self._conn.add_s(dn, attrs_list)
        return OperationResult.ok("LDAP account created", dn=dn)

    async def delete_account(self, identity: str) -> OperationResult:
        dn = self._dn_for_user(identity)
        self._conn.delete_s(dn)
        return OperationResult.ok("LDAP account deleted")

    async def set_password(self, identity: str, new_password: str) -> OperationResult:
        dn = self._dn_for_user(identity)
        self._conn.passwd_s(dn, None, new_password)
        return OperationResult.ok("Password set")

    async def list_entitlements(
        self, page_size: int = 50, cursor: str | None = None
    ) -> PagedResult:
        search_filter = f"(objectClass={self.group_object_class})"
        results = self._conn.search_s(self.groups_base_dn, ldap.SCOPE_SUBTREE, search_filter)
        entitlements = []
        for dn, attrs in results:
            if not dn:
                continue
            name_vals = attrs.get(self.group_id_attr, [])
            name = name_vals[0].decode() if name_vals else ""
            desc_vals = attrs.get("description", [])
            desc = desc_vals[0].decode() if desc_vals else ""
            entitlements.append(
                Entitlement(identity=name, name=name, description=desc, entitlement_type="group")
            )
        return PagedResult(items=entitlements, total_count=len(entitlements), page_size=page_size)

    async def grant_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        group_dn = self._dn_for_group(entitlement_identity)
        user_dn = self._dn_for_user(account_identity)
        mod = [(ldap.MOD_ADD, self.member_attr, [user_dn.encode()])]
        self._conn.modify_s(group_dn, mod)
        return OperationResult.ok("Member added to LDAP group")

    async def revoke_entitlement(
        self, account_identity: str, entitlement_identity: str
    ) -> OperationResult:
        group_dn = self._dn_for_group(entitlement_identity)
        user_dn = self._dn_for_user(account_identity)
        mod = [(ldap.MOD_DELETE, self.member_attr, [user_dn.encode()])]
        self._conn.modify_s(group_dn, mod)
        return OperationResult.ok("Member removed from LDAP group")
