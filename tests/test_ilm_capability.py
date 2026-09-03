"""Tests for Phase 2 — connector capability specifications and their validation."""

import pytest

from iga_connector.core import Account, ConnectorStatus
from iga_connector.core.connector import BaseConnector
from iga_connector.core.schema import ConnectorSchema
from iga_connector.ilm import (
    APMLifecycleStage,
    ApplicationRecord,
    CertificationCadence,
    ConnectorCapabilityMap,
    CoverageLevel,
    EntitlementGranularity,
    GovernanceOperation,
    GovernanceOwnership,
    GovernancePolicyProfile,
    IntegrationPath,
    Severity,
    derive_requirements,
)

OP = GovernanceOperation


@pytest.fixture
def requirements():
    return derive_requirements(
        ApplicationRecord(
            application_id="APP-1", stage=APMLifecycleStage.PRODUCTION, has_api_or_sdk=True
        ),
        policy=GovernancePolicyProfile(certification_cadence=CertificationCadence.ANNUAL),
    )


@pytest.fixture
def ownership():
    return GovernanceOwnership(
        governance_owner="gov@example.com", technical_maintainer="eng@example.com"
    )


def full_map(requirements, ownership, **overrides) -> ConnectorCapabilityMap:
    capability_map = ConnectorCapabilityMap(
        integration_id="int-1", application_id="APP-1", ownership=ownership, **overrides
    )
    for requirement in requirements.required_operations:
        capability_map.declare(requirement.operation, CoverageLevel.FULL, "All")
    return capability_map


class TestCoverageLevel:
    def test_satisfies_ordering(self):
        assert CoverageLevel.FULL.satisfies(CoverageLevel.PARTIAL)
        assert CoverageLevel.PARTIAL.satisfies(CoverageLevel.PARTIAL)
        assert not CoverageLevel.PARTIAL.satisfies(CoverageLevel.FULL)
        assert not CoverageLevel.NONE.satisfies(CoverageLevel.PARTIAL)


class TestDeclaration:
    def test_declare_replaces_previous_declaration(self, ownership):
        capability_map = ConnectorCapabilityMap(
            integration_id="int-1", application_id="APP-1", ownership=ownership
        )
        capability_map.declare(OP.IDENTITY_AGGREGATION, CoverageLevel.PARTIAL)
        capability_map.declare(OP.IDENTITY_AGGREGATION, CoverageLevel.FULL)
        assert len(capability_map.declarations) == 1
        assert capability_map.coverage_of(OP.IDENTITY_AGGREGATION) == CoverageLevel.FULL

    def test_gap_without_control_is_uncontrolled(self, ownership):
        capability_map = ConnectorCapabilityMap(
            integration_id="int-1", application_id="APP-1", ownership=ownership
        )
        capability_map.declare(OP.ENTITLEMENT_ENUMERATION, CoverageLevel.PARTIAL)
        capability_map.declare(
            OP.NHI_CREDENTIAL_ROTATION, CoverageLevel.NONE, gap_control="Secrets manager"
        )
        assert len(capability_map.gaps()) == 2
        assert len(capability_map.uncontrolled_gaps()) == 1

    def test_undeclared_operation_reports_no_coverage(self, ownership):
        capability_map = ConnectorCapabilityMap(
            integration_id="int-1", application_id="APP-1", ownership=ownership
        )
        assert capability_map.coverage_of(OP.CERTIFICATION_FEED) == CoverageLevel.NONE


class TestValidation:
    def test_full_coverage_validates(self, requirements, ownership):
        validation = full_map(requirements, ownership).validate_against(requirements)
        assert validation.compliant
        assert validation.promotable()

    def test_undeclared_required_operation_blocks(self, requirements, ownership):
        capability_map = full_map(requirements, ownership)
        capability_map.declarations = [
            d for d in capability_map.declarations if d.operation != OP.ACCOUNT_DEPROVISIONING
        ]
        validation = capability_map.validate_against(requirements)
        assert not validation.promotable()
        assert validation.blocking_findings[0].code == "capability.undeclared"

    def test_uncontrolled_gap_on_required_operation_blocks(self, requirements, ownership):
        capability_map = full_map(requirements, ownership)
        capability_map.declare(OP.ACCOUNT_DEPROVISIONING, CoverageLevel.PARTIAL)
        validation = capability_map.validate_against(requirements)
        assert not validation.promotable()
        assert any(f.code == "capability.gap" for f in validation.findings)

    def test_documented_compensating_control_unblocks(self, requirements, ownership):
        capability_map = full_map(requirements, ownership)
        capability_map.declare(
            OP.ACCOUNT_DEPROVISIONING,
            CoverageLevel.PARTIAL,
            gap_control="ITSM ticket closes the deprovisioning action within 24h",
        )
        validation = capability_map.validate_against(requirements)
        assert validation.promotable()
        assert any(f.code == "capability.gap_controlled" for f in validation.findings)

    def test_gap_control_can_be_disallowed_by_charter(self, requirements, ownership):
        capability_map = full_map(requirements, ownership)
        capability_map.declare(
            OP.ACCOUNT_DEPROVISIONING, CoverageLevel.PARTIAL, gap_control="Manual review"
        )
        validation = capability_map.validate_against(
            requirements, allow_partial_with_gap_control=False
        )
        assert not validation.promotable()

    def test_missing_ownership_blocks(self, requirements):
        capability_map = ConnectorCapabilityMap(integration_id="int-1", application_id="APP-1")
        for requirement in requirements.required_operations:
            capability_map.declare(requirement.operation, CoverageLevel.FULL)
        validation = capability_map.validate_against(requirements)
        assert not validation.promotable()
        assert any(f.code == "ownership.missing" for f in validation.findings)

    def test_unseparated_ownership_is_flagged_but_not_blocking(self, requirements):
        capability_map = full_map(
            requirements,
            GovernanceOwnership(governance_owner="same@x.com", technical_maintainer="same@x.com"),
        )
        validation = capability_map.validate_against(requirements)
        finding = next(f for f in validation.findings if f.code == "ownership.not_separated")
        assert finding.severity == Severity.HIGH
        assert validation.promotable()

    def test_itsm_path_requires_a_declared_sla(self, requirements, ownership):
        capability_map = full_map(
            requirements, ownership, path=IntegrationPath.DISCONNECTED_ITSM
        )
        assert not capability_map.validate_against(requirements).promotable()
        capability_map.fulfillment_sla_hours = 24.0
        assert capability_map.validate_against(requirements).promotable()

    def test_permission_granularity_flags_partial_enumeration(self, ownership):
        requirements = derive_requirements(
            ApplicationRecord(
                application_id="APP-1", stage=APMLifecycleStage.PRODUCTION, has_api_or_sdk=True
            ),
            policy=GovernancePolicyProfile(
                entitlement_granularity=EntitlementGranularity.PERMISSION
            ),
        )
        capability_map = full_map(requirements, ownership)
        capability_map.declare(
            OP.ENTITLEMENT_ENUMERATION,
            CoverageLevel.PARTIAL,
            gap_control="Manual supplement",
        )
        validation = capability_map.validate_against(requirements)
        assert any(f.code == "capability.granularity" for f in validation.findings)

    def test_unrequired_uncontrolled_gap_is_low_severity(self, requirements, ownership):
        capability_map = full_map(requirements, ownership)
        capability_map.declare(OP.SESSION_TERMINATION, CoverageLevel.NONE)
        validation = capability_map.validate_against(requirements)
        finding = next(f for f in validation.findings if f.code == "capability.uncontrolled_gap")
        assert finding.severity == Severity.LOW
        assert validation.promotable()


class _PartialConnector(BaseConnector):
    """Aggregates and provisions, but cannot deprovision or enumerate entitlements."""

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(
            connector_name="partial_app",
            version="2.1.0",
            supported_operations=["list_accounts", "create_account", "update_account"],
        )

    async def test_connection(self) -> ConnectorStatus:
        return ConnectorStatus(connected=True)

    async def create_account(self, account: Account):  # pragma: no cover - not exercised
        raise NotImplementedError


class TestDerivationFromConnector:
    def test_coverage_is_derived_from_supported_operations(self, ownership):
        capability_map = ConnectorCapabilityMap.from_connector(
            _PartialConnector({}), integration_id="int-1", application_id="APP-1",
            ownership=ownership,
        )
        assert capability_map.connector_name == "partial_app"
        assert capability_map.connector_version == "2.1.0"
        assert capability_map.coverage_of(OP.IDENTITY_AGGREGATION) == CoverageLevel.FULL
        assert capability_map.coverage_of(OP.ACCOUNT_PROVISIONING) == CoverageLevel.FULL
        assert capability_map.coverage_of(OP.ACCOUNT_DEPROVISIONING) == CoverageLevel.NONE
        assert capability_map.coverage_of(OP.ENTITLEMENT_ENUMERATION) == CoverageLevel.NONE

    def test_partially_satisfied_operation_is_partial(self, ownership):
        class _AccountsOnly(_PartialConnector):
            def get_schema(self) -> ConnectorSchema:
                return ConnectorSchema(
                    connector_name="accounts_only", supported_operations=["list_accounts"]
                )

        capability_map = ConnectorCapabilityMap.from_connector(
            _AccountsOnly({}), integration_id="int-1", application_id="APP-1", ownership=ownership
        )
        # A certification feed needs accounts *and* entitlements.
        assert capability_map.coverage_of(OP.CERTIFICATION_FEED) == CoverageLevel.PARTIAL

    def test_derived_map_fails_validation_where_the_connector_falls_short(
        self, requirements, ownership
    ):
        capability_map = ConnectorCapabilityMap.from_connector(
            _PartialConnector({}), integration_id="int-1", application_id="APP-1",
            ownership=ownership,
        )
        validation = capability_map.validate_against(requirements)
        assert not validation.promotable()
        gaps = {f.operation for f in validation.blocking_findings}
        assert OP.ACCOUNT_DEPROVISIONING in gaps
