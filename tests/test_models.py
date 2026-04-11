"""Tests for core data models."""

from iga_connector.core.models import (
    Account,
    AccountStatus,
    Entitlement,
    OperationResult,
    PagedResult,
)


class TestAccount:
    def test_create_minimal(self):
        acct = Account(identity="user1")
        assert acct.identity == "user1"
        assert acct.status == AccountStatus.ACTIVE
        assert acct.attributes == {}
        assert acct.entitlements == []

    def test_create_full(self):
        acct = Account(
            identity="user1",
            display_name="John Doe",
            status=AccountStatus.DISABLED,
            attributes={"email": "john@example.com"},
            entitlements=["admin", "reader"],
        )
        assert acct.display_name == "John Doe"
        assert acct.status == AccountStatus.DISABLED
        assert acct.attributes["email"] == "john@example.com"
        assert len(acct.entitlements) == 2


class TestEntitlement:
    def test_create(self):
        ent = Entitlement(identity="grp1", name="Admins")
        assert ent.identity == "grp1"
        assert ent.entitlement_type == "group"


class TestOperationResult:
    def test_ok(self):
        result = OperationResult.ok("Done", id="123")
        assert result.success is True
        assert result.data["id"] == "123"

    def test_fail(self):
        result = OperationResult.fail("Something broke")
        assert result.success is False
        assert "Something broke" in result.errors

    def test_fail_with_errors(self):
        result = OperationResult.fail("Bad", errors=["err1", "err2"])
        assert len(result.errors) == 2


class TestPagedResult:
    def test_empty(self):
        pr = PagedResult(items=[], page_size=25)
        assert pr.total_count is None
        assert pr.next_cursor is None
