"""Tests for Phase 1 — governance-driven discovery and strategy routing."""

import pytest

from iga_connector.ilm import (
    APMLifecycleStage,
    ApplicationRecord,
    AuthorizationModel,
    CertificationCadence,
    ConnectorGovernanceCharter,
    EntitlementGranularity,
    GovernanceOperation,
    GovernancePolicyProfile,
    IdentityPopulation,
    IntegrationPath,
    RegulatoryFramework,
    RiskClassification,
    decide_integration_path,
    derive_requirements,
)

OP = GovernanceOperation


def make_app(**overrides) -> ApplicationRecord:
    defaults = dict(
        application_id="APP-1",
        name="Test App",
        stage=APMLifecycleStage.PRODUCTION,
        has_api_or_sdk=True,
        authorization_model=AuthorizationModel.LOCAL_USER_STORE,
    )
    defaults.update(overrides)
    return ApplicationRecord(**defaults)


class TestDeriveRequirements:
    def test_regulatory_scope_mandates_operations(self):
        spec = derive_requirements(
            make_app(regulatory_scope=[RegulatoryFramework.SOX]),
            policy=GovernancePolicyProfile(certification_cadence=CertificationCadence.NONE),
        )
        assert spec.requires(OP.CERTIFICATION_FEED)
        assert spec.requires(OP.ENTITLEMENT_ENUMERATION)
        assert "SOX" in spec.requirement_for(OP.CERTIFICATION_FEED).sources

    def test_policy_alone_drives_requirements_without_regulation(self):
        spec = derive_requirements(make_app(), policy=GovernancePolicyProfile())
        assert spec.requires(OP.ACCOUNT_PROVISIONING)
        assert spec.requires(OP.ACCOUNT_DEPROVISIONING)
        assert spec.regulatory_scope == []
        assert any("No regulatory framework" in n for n in spec.notes)

    def test_sod_ruleset_mandates_entitlement_enumeration(self):
        spec = derive_requirements(
            make_app(),
            policy=GovernancePolicyProfile(
                certification_cadence=CertificationCadence.NONE, sod_ruleset_in_scope=True
            ),
        )
        requirement = spec.requirement_for(OP.ENTITLEMENT_ENUMERATION)
        assert requirement is not None
        assert "iga_policy:sod" in requirement.sources

    def test_non_human_population_adds_credential_rotation(self):
        spec = derive_requirements(make_app(identity_population=IdentityPopulation.NON_HUMAN))
        assert spec.requires(OP.NHI_CREDENTIAL_ROTATION)

    def test_ai_agent_population_adds_containment_operations(self):
        spec = derive_requirements(make_app(identity_population=IdentityPopulation.AI_AGENT))
        assert spec.requires(OP.SESSION_TERMINATION)
        assert spec.requires(OP.RISK_SIGNAL_SHARING)

    def test_thresholds_are_calibrated_to_risk(self):
        critical = derive_requirements(make_app(risk_classification=RiskClassification.CRITICAL))
        low = derive_requirements(make_app(risk_classification=RiskClassification.LOW))
        assert (
            critical.health_thresholds.min_aggregation_completeness
            > low.health_thresholds.min_aggregation_completeness
        )
        assert (
            critical.health_thresholds.max_deprovisioning_latency_hours
            < low.health_thresholds.max_deprovisioning_latency_hours
        )
        assert critical.priority < low.priority

    def test_policy_overrides_charter_latency_budget(self):
        spec = derive_requirements(
            make_app(risk_classification=RiskClassification.LOW),
            policy=GovernancePolicyProfile(max_deprovisioning_latency_hours=2.0),
        )
        assert spec.health_thresholds.max_deprovisioning_latency_hours == 2.0

    def test_custom_charter_changes_the_baseline(self):
        charter = ConnectorGovernanceCharter(
            regulatory_operations={RegulatoryFramework.SOX: [OP.SESSION_TERMINATION]}
        )
        spec = derive_requirements(
            make_app(regulatory_scope=[RegulatoryFramework.SOX]),
            policy=GovernancePolicyProfile(
                certification_cadence=CertificationCadence.NONE,
                joiner_workflow_enabled=False,
                mover_workflow_enabled=False,
                leaver_workflow_enabled=False,
                access_request_enabled=False,
            ),
            charter=charter,
        )
        assert spec.operations() == [OP.SESSION_TERMINATION]

    def test_permission_granularity_is_noted(self):
        spec = derive_requirements(
            make_app(),
            policy=GovernancePolicyProfile(
                entitlement_granularity=EntitlementGranularity.PERMISSION
            ),
        )
        assert any("Permission-level" in n for n in spec.notes)


class TestStrategyDecision:
    def test_directory_only_application_is_auto_compliant(self):
        decision = decide_integration_path(
            make_app(
                authorization_model=AuthorizationModel.DIRECTORY_GROUPS,
                has_local_user_store=False,
            )
        )
        assert decision.path == IntegrationPath.AUTO_COMPLIANT
        assert not decision.requires_dedicated_connector

    def test_directory_application_with_local_store_is_not_auto_compliant(self):
        decision = decide_integration_path(
            make_app(
                authorization_model=AuthorizationModel.DIRECTORY_GROUPS, has_local_user_store=True
            )
        )
        assert decision.path != IntegrationPath.AUTO_COMPLIANT

    def test_auto_compliant_warns_on_permission_level_certification(self):
        spec = derive_requirements(
            make_app(),
            policy=GovernancePolicyProfile(
                entitlement_granularity=EntitlementGranularity.PERMISSION
            ),
        )
        decision = decide_integration_path(
            make_app(
                authorization_model=AuthorizationModel.DIRECTORY_GROUPS,
                has_local_user_store=False,
            ),
            requirements=spec,
        )
        assert decision.path == IntegrationPath.AUTO_COMPLIANT
        assert decision.warnings

    @pytest.mark.parametrize(
        "overrides",
        [
            {"has_api_or_sdk": False},
            {"vendor_restriction": True},
            {"integration_cost_prohibitive": True},
        ],
    )
    def test_unconnectable_application_routes_to_itsm(self, overrides):
        decision = decide_integration_path(make_app(**overrides))
        assert decision.path == IntegrationPath.DISCONNECTED_ITSM
        assert decision.fulfillment_channel.value == "itsm_manual"

    def test_ootb_connector_is_preferred_when_gaps_are_acceptable(self):
        decision = decide_integration_path(make_app(ootb_connector_available=True))
        assert decision.path == IntegrationPath.OOTB_CONNECTOR

    def test_unacceptable_ootb_gaps_force_a_custom_connector(self):
        decision = decide_integration_path(
            make_app(ootb_connector_available=True), ootb_capability_gaps_acceptable=False
        )
        assert decision.path == IntegrationPath.CUSTOM_CONNECTOR
        assert decision.requires_dedicated_connector

    def test_hybrid_authorization_warns(self):
        decision = decide_integration_path(
            make_app(authorization_model=AuthorizationModel.HYBRID)
        )
        assert decision.warnings

    def test_every_path_carries_a_capability_obligation(self):
        applications = [
            make_app(
                authorization_model=AuthorizationModel.DIRECTORY_GROUPS, has_local_user_store=False
            ),
            make_app(has_api_or_sdk=False),
            make_app(ootb_connector_available=True),
            make_app(),
        ]
        for application in applications:
            assert decide_integration_path(application).capability_obligation
