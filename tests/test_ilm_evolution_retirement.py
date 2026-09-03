"""Tests for Phase 4 (governance-triggered evolution) and Phase 5 (governed retirement)."""

from datetime import date

import pytest

from iga_connector.ilm import (
    ConnectorCapabilityMap,
    ConnectorGovernanceCharter,
    CoverageLevel,
    EvolutionTrigger,
    GovernanceOperation,
    GovernanceOwnership,
    GovernedRetirement,
    IdentityPopulation,
    IntegrationRequirementSpec,
    RegulatoryFramework,
    RequiredOperation,
    RetirementBlockedError,
    RetirementObligation,
    Severity,
    TraceabilityStage,
    evaluate_evolution,
)

OP = GovernanceOperation


def spec(*operations) -> IntegrationRequirementSpec:
    return IntegrationRequirementSpec(
        application_id="APP-1",
        required_operations=[
            RequiredOperation(operation=op, coverage=CoverageLevel.FULL, sources=["SOX"])
            for op in operations
        ],
    )


@pytest.fixture
def capability_map():
    capability_map = ConnectorCapabilityMap(
        integration_id="int-1",
        application_id="APP-1",
        ownership=GovernanceOwnership(governance_owner="gov@x", technical_maintainer="eng@x"),
    )
    capability_map.declare(OP.IDENTITY_AGGREGATION, CoverageLevel.FULL)
    capability_map.declare(OP.ENTITLEMENT_ENUMERATION, CoverageLevel.PARTIAL)
    return capability_map


class TestEvolution:
    def test_policy_change_surfaces_the_capability_gap(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.SOD_RULE_EXPANSION,
            spec(OP.IDENTITY_AGGREGATION, OP.ENTITLEMENT_ENUMERATION), capability_map,
        )
        assert request.requires_connector_work
        change = request.capability_changes[0]
        assert change.operation == OP.ENTITLEMENT_ENUMERATION
        assert change.current_coverage == CoverageLevel.PARTIAL
        assert change.severity == Severity.HIGH

    def test_a_controlled_gap_lowers_severity(self, capability_map):
        capability_map.declare(
            OP.ENTITLEMENT_ENUMERATION, CoverageLevel.PARTIAL, gap_control="Manual supplement"
        )
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.SOD_RULE_EXPANSION, spec(OP.ENTITLEMENT_ENUMERATION),
            capability_map,
        )
        assert request.capability_changes[0].severity == Severity.MEDIUM

    def test_satisfied_requirements_produce_no_change(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.RISK_RECLASSIFICATION, spec(OP.IDENTITY_AGGREGATION),
            capability_map,
        )
        assert not request.requires_connector_work

    def test_absent_capability_map_treats_everything_as_missing(self):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.REGULATORY_SCOPE_EXPANSION, spec(OP.CERTIFICATION_FEED)
        )
        assert request.capability_changes[0].current_coverage == CoverageLevel.NONE

    def test_governance_trigger_opens_with_a_recorded_policy_decision(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE,
            spec(OP.ENTITLEMENT_ENUMERATION), capability_map,
        )
        assert TraceabilityStage.POLICY_DECISION in request.completed_stages()
        assert TraceabilityStage.CAPABILITY_MAP_REVISION in request.outstanding_stages()
        assert not request.is_closed()

    def test_technical_trigger_owes_no_policy_decision(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.TARGET_TECHNICAL_CHANGE, spec(OP.IDENTITY_AGGREGATION),
            capability_map,
        )
        assert TraceabilityStage.POLICY_DECISION not in request.required_stages()

    def test_full_trace_closes_the_request(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.SOD_RULE_EXPANSION, spec(OP.ENTITLEMENT_ENUMERATION),
            capability_map,
        )
        for stage in list(request.outstanding_stages()):
            request.record_stage(stage, completed_by="gov@x")
        assert request.is_closed()

    def test_recording_a_stage_twice_does_not_duplicate_it(self, capability_map):
        request = evaluate_evolution(
            "int-1", EvolutionTrigger.SOD_RULE_EXPANSION, spec(OP.IDENTITY_AGGREGATION),
            capability_map,
        )
        request.record_stage(TraceabilityStage.REQUIREMENT_SPEC_UPDATE, "a")
        request.record_stage(TraceabilityStage.REQUIREMENT_SPEC_UPDATE, "b")
        steps = [s for s in request.trace if s.stage == TraceabilityStage.REQUIREMENT_SPEC_UPDATE]
        assert len(steps) == 1
        assert steps[0].completed_by == "b"

    @pytest.mark.parametrize(
        "trigger,governance",
        [
            (EvolutionTrigger.SOD_RULE_EXPANSION, True),
            (EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE, True),
            (EvolutionTrigger.REGULATORY_SCOPE_EXPANSION, True),
            (EvolutionTrigger.RISK_RECLASSIFICATION, True),
            (EvolutionTrigger.TARGET_TECHNICAL_CHANGE, False),
        ],
    )
    def test_trigger_classification(self, trigger, governance):
        assert trigger.is_governance_triggered is governance


class TestGovernedRetirement:
    def test_workforce_checklist_has_four_obligations(self):
        retirement = GovernedRetirement.open("int-1", "APP-1")
        assert len(retirement.items) == 4
        assert RetirementObligation.CREDENTIAL_INVALIDATION not in {
            i.obligation for i in retirement.items
        }

    def test_nhi_retirement_adds_credential_invalidation(self):
        retirement = GovernedRetirement.open(
            "int-1", "APP-1", identity_population=IdentityPopulation.NON_HUMAN
        )
        assert retirement.item(RetirementObligation.CREDENTIAL_INVALIDATION) is not None

    def test_retention_follows_the_longest_obligation_in_scope(self):
        retirement = GovernedRetirement.open(
            "int-1", "APP-1",
            regulatory_scope=[RegulatoryFramework.PCI_DSS, RegulatoryFramework.SOX],
            charter=ConnectorGovernanceCharter(),
        )
        assert retirement.disposition.audit_retention_years == 7

    def test_default_retention_without_regulatory_scope(self):
        assert GovernedRetirement.open("int-1").disposition.audit_retention_years == 3

    def test_authorization_is_refused_while_obligations_stand(self):
        retirement = GovernedRetirement.open("int-1", "APP-1")
        with pytest.raises(RetirementBlockedError) as exc:
            retirement.authorize("gov@x")
        assert len(exc.value.obligations) == 4
        assert not retirement.disposition.authorized

    def test_resolution_requires_evidence(self):
        retirement = GovernedRetirement.open("int-1", "APP-1")
        with pytest.raises(ValueError):
            retirement.resolve(
                RetirementObligation.ORPHANED_ACCOUNT_REMEDIATION, "gov@x", evidence="  "
            )

    def test_unknown_obligation_is_rejected(self):
        retirement = GovernedRetirement.open("int-1", "APP-1")
        with pytest.raises(KeyError):
            retirement.resolve(RetirementObligation.CREDENTIAL_INVALIDATION, "gov@x", "EV")

    def test_authorization_sets_the_retention_horizon(self):
        retirement = GovernedRetirement.open(
            "int-1", "APP-1", regulatory_scope=[RegulatoryFramework.SOX]
        )
        for item in list(retirement.items):
            retirement.resolve(item.obligation, "gov@x", evidence=f"EV-{item.obligation.value}")
        disposition = retirement.authorize("gov@x", notes="Application decommissioned")
        assert disposition.authorized
        assert retirement.is_complete()
        assert disposition.retain_until is not None
        assert disposition.retain_until > date.today()

    def test_every_obligation_carries_its_framework_text(self):
        retirement = GovernedRetirement.open(
            "int-1", "APP-1", identity_population=IdentityPopulation.AI_AGENT
        )
        assert all(item.description for item in retirement.items)
