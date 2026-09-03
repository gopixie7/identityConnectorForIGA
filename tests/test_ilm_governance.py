"""Tests for the governance inventory, blind spots, anti-patterns, and the pipeline."""

from datetime import datetime, timedelta, timezone

import pytest

from iga_connector.ilm import (
    ANTI_PATTERN_DESCRIPTIONS,
    AntiPattern,
    APMLifecycleStage,
    ApplicationRecord,
    AuthorizationModel,
    CertificationCadence,
    ConnectorCapabilityMap,
    CoverageLevel,
    EvolutionTrigger,
    GovernanceOperation,
    GovernanceOwnership,
    GovernancePolicyProfile,
    HealthObservation,
    ILMPipeline,
    IntegrationGovernanceInventory,
    IntegrationPath,
    LifecyclePhase,
    MaturityLevel,
    PromotionBlockedError,
    RegulatoryFramework,
    RiskClassification,
    Severity,
    detect_anti_patterns,
)

OP = GovernanceOperation
NOW = datetime.now(timezone.utc)


def application(**overrides) -> ApplicationRecord:
    defaults = dict(
        application_id="APP-1",
        name="Payments",
        stage=APMLifecycleStage.PRODUCTION,
        risk_classification=RiskClassification.HIGH,
        authorization_model=AuthorizationModel.LOCAL_USER_STORE,
        has_api_or_sdk=True,
    )
    defaults.update(overrides)
    return ApplicationRecord(**defaults)


def full_observation(integration_id: str, **overrides) -> HealthObservation:
    """An observation that measures all five indicators, all within threshold."""
    defaults = dict(
        integration_id=integration_id,
        observed_at=NOW,
        accounts_in_target=100,
        accounts_aggregated=100,
        provisioning_attempted=10,
        provisioning_succeeded=10,
        deprovisioning_latency_hours=1.0,
        entitlements_in_target=20,
        entitlements_enumerated=20,
        credential_expires_at=NOW + timedelta(days=120),
    )
    defaults.update(overrides)
    return HealthObservation(**defaults)


def ownership() -> GovernanceOwnership:
    return GovernanceOwnership(governance_owner="gov@x", technical_maintainer="eng@x")


def complete_map(record, path=IntegrationPath.CUSTOM_CONNECTOR) -> ConnectorCapabilityMap:
    capability_map = ConnectorCapabilityMap(
        integration_id=record.integration_id,
        application_id=record.application_id,
        path=path,
        ownership=ownership(),
    )
    for requirement in record.requirements.required_operations:
        capability_map.declare(requirement.operation, CoverageLevel.FULL, "All")
    return capability_map


@pytest.fixture
def pipeline() -> ILMPipeline:
    pipeline = ILMPipeline()
    pipeline.portfolio.last_synced_at = NOW
    return pipeline


def promoted(pipeline: ILMPipeline, app: ApplicationRecord):
    pipeline.portfolio.add(app)
    record = pipeline.discover(app, ownership=ownership())
    pipeline.declare_capability(record.integration_id, complete_map(record))
    return pipeline.promote(record.integration_id)


class TestAPMControlPlane:
    def test_production_transition_triggers_discovery(self, pipeline):
        pipeline.portfolio.add(application(stage=APMLifecycleStage.TESTING))
        event = pipeline.portfolio.emit_transition("APP-1", APMLifecycleStage.PRODUCTION)
        outcome = pipeline.on_apm_event(event)
        assert outcome.phase == LifecyclePhase.DEVELOPMENT
        assert outcome.requirements is not None
        assert outcome.strategy is not None

    def test_early_stage_transition_carries_no_obligation(self, pipeline):
        pipeline.portfolio.add(application(stage=APMLifecycleStage.PLANNED))
        event = pipeline.portfolio.emit_transition("APP-1", APMLifecycleStage.DEVELOPMENT)
        outcome = pipeline.on_apm_event(event)
        assert outcome.phase is None
        assert not pipeline.inventory.records

    def test_sunset_transition_opens_governed_retirement(self, pipeline):
        promoted(pipeline, application())
        event = pipeline.portfolio.emit_transition("APP-1", APMLifecycleStage.SUNSET)
        outcome = pipeline.on_apm_event(event)
        assert outcome.phase == LifecyclePhase.RETIREMENT
        assert outcome.retirement is not None
        assert outcome.retirement.outstanding()

    def test_unknown_application_transition_is_rejected(self, pipeline):
        with pytest.raises(KeyError):
            pipeline.portfolio.emit_transition("APP-MISSING", APMLifecycleStage.PRODUCTION)


class TestInventory:
    def test_promotion_is_gated_on_capability_declaration(self, pipeline):
        pipeline.portfolio.add(application())
        record = pipeline.discover(application(), ownership=ownership())
        with pytest.raises(PromotionBlockedError):
            pipeline.promote(record.integration_id)
        assert record.phase == LifecyclePhase.DISCOVERY

    def test_promotion_succeeds_once_capability_is_declared(self, pipeline):
        record = promoted(pipeline, application())
        assert record.phase == LifecyclePhase.OPERATION
        assert record.promoted_at is not None

    def test_duplicate_registration_is_rejected(self, pipeline):
        promoted(pipeline, application())
        with pytest.raises(Exception):
            pipeline.discover(application(), integration_id="app-1-integration")

    def test_health_history_is_bounded(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.inventory.max_health_history = 3
        for i in range(6):
            pipeline.observe(
                HealthObservation(
                    integration_id=record.integration_id, observed_at=NOW - timedelta(minutes=i)
                )
            )
        assert len(record.health_history) == 3

    def test_evolution_moves_the_integration_out_of_operation(self, pipeline):
        record = promoted(pipeline, application())
        record.capability_map.declare(OP.ENTITLEMENT_ENUMERATION, CoverageLevel.NONE)
        request = pipeline.evolve(
            record.integration_id,
            EvolutionTrigger.SOD_RULE_EXPANSION,
            policy=GovernancePolicyProfile(sod_ruleset_in_scope=True),
        )
        assert request.requires_connector_work
        assert record.phase == LifecyclePhase.EVOLUTION

        for stage in list(request.outstanding_stages()):
            request.record_stage(stage, "gov@x")
        pipeline.inventory.close_evolution(record.integration_id, request)
        assert record.phase == LifecyclePhase.OPERATION

    def test_retirement_without_an_open_window_is_refused(self, pipeline):
        record = promoted(pipeline, application())
        with pytest.raises(PromotionBlockedError):
            pipeline.retire(record.integration_id, "gov@x")

    def test_round_trip_through_yaml(self, pipeline, tmp_path):
        record = promoted(pipeline, application())
        pipeline.observe(
            HealthObservation(
                integration_id=record.integration_id,
                accounts_in_target=10,
                accounts_aggregated=10,
            )
        )
        path = pipeline.inventory.save(tmp_path / "inventory.yaml")
        restored = IntegrationGovernanceInventory.load(path)
        assert len(restored.records) == 1
        reloaded = restored.require(record.integration_id)
        assert reloaded.phase == LifecyclePhase.OPERATION
        assert reloaded.capability_map is not None
        assert reloaded.health_history


class TestBlindSpots:
    def test_uncovered_in_scope_application_is_a_blind_spot(self, pipeline):
        pipeline.portfolio.add(application(regulatory_scope=[RegulatoryFramework.SOX]))
        spots = pipeline.inventory.blind_spots(pipeline.portfolio)
        assert len(spots) == 1
        assert spots[0].severity == Severity.BLOCKING

    def test_application_out_of_scope_is_not_a_blind_spot(self, pipeline):
        pipeline.portfolio.add(application(in_governance_scope=False))
        assert not pipeline.inventory.blind_spots(pipeline.portfolio)

    def test_registered_but_unpromoted_integration_is_still_a_blind_spot(self, pipeline):
        app = application()
        pipeline.portfolio.add(app)
        pipeline.discover(app, ownership=ownership())
        spots = pipeline.inventory.blind_spots(pipeline.portfolio)
        assert len(spots) == 1
        assert "not in production governance" in spots[0].reason

    def test_promoted_integration_closes_the_blind_spot(self, pipeline):
        promoted(pipeline, application())
        assert not pipeline.inventory.blind_spots(pipeline.portfolio)

    def test_breached_coverage_is_nominal_not_effective(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(
            HealthObservation(
                integration_id=record.integration_id,
                accounts_in_target=1000,
                accounts_aggregated=500,
            )
        )
        spots = pipeline.inventory.blind_spots(pipeline.portfolio)
        assert len(spots) == 1
        assert "nominal, not effective" in spots[0].reason

    def test_partially_measured_health_is_not_effective_coverage(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(
            HealthObservation(
                integration_id=record.integration_id,
                accounts_in_target=100,
                accounts_aggregated=100,
            )
        )
        # Four of the five indicators went unmeasured: an unobserved connector
        # is ungoverned, so it does not close the blind spot.
        spots = pipeline.inventory.blind_spots(pipeline.portfolio)
        assert len(spots) == 1
        assert "nominal, not effective" in spots[0].reason

    def test_coverage_report_counts_scope_and_coverage(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(full_observation(record.integration_id))
        pipeline.portfolio.add(application(application_id="APP-2", name="Uncovered"))
        report = pipeline.coverage_report()
        assert report.applications_in_scope == 2
        assert report.applications_covered == 1
        assert report.coverage_rate == 0.5
        assert report.integrations_by_path[IntegrationPath.CUSTOM_CONNECTOR.value] == 1


class TestAntiPatterns:
    def test_no_health_observation_is_build_and_forget(self, pipeline):
        promoted(pipeline, application())
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        build = [f for f in findings if f.anti_pattern == AntiPattern.BUILD_AND_FORGET]
        assert any("No health observation" in f.evidence for f in build)

    def test_stale_health_observation_is_build_and_forget(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(
            HealthObservation(
                integration_id=record.integration_id, observed_at=NOW - timedelta(days=30)
            )
        )
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio, now=NOW)
        assert any("day(s) ago" in f.evidence for f in findings)

    def test_sunset_application_without_retirement_is_ungoverned(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.portfolio.emit_transition("APP-1", APMLifecycleStage.SUNSET)
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        assert any(f.anti_pattern == AntiPattern.UNGOVERNED_RETIREMENT for f in findings)
        assert record.retirement is None

    def test_retired_without_disposition_is_blocking(self, pipeline):
        record = promoted(pipeline, application())
        record.phase = LifecyclePhase.RETIRED
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        ungoverned = [f for f in findings if f.anti_pattern == AntiPattern.UNGOVERNED_RETIREMENT]
        assert ungoverned and ungoverned[0].severity == Severity.BLOCKING

    def test_only_technical_evolutions_is_an_anti_pattern(self, pipeline):
        record = promoted(pipeline, application())
        for _ in range(2):
            request = pipeline.evolve(
                record.integration_id, EvolutionTrigger.TARGET_TECHNICAL_CHANGE
            )
            request.raised_at = request.raised_at + timedelta(seconds=1)
            pipeline.inventory.record_evolution(request)
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        assert any(f.anti_pattern == AntiPattern.TECHNICAL_EVOLUTION_ONLY for f in findings)

    def test_missing_portfolio_is_apm_disconnection(self, pipeline):
        promoted(pipeline, application())
        findings = detect_anti_patterns(pipeline.inventory, portfolio=None)
        assert any(f.anti_pattern == AntiPattern.APM_IGA_DISCONNECTION for f in findings)

    def test_never_synced_portfolio_is_apm_disconnection(self, pipeline):
        promoted(pipeline, application())
        pipeline.portfolio.last_synced_at = None
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        assert any("never been synchronized" in f.evidence for f in findings)

    def test_integration_unknown_to_apm_is_flagged(self, pipeline):
        promoted(pipeline, application())
        pipeline.portfolio.applications = []
        findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
        assert any("no record in the application portfolio" in f.evidence for f in findings)

    def test_all_anti_patterns_have_framework_descriptions(self):
        assert set(ANTI_PATTERN_DESCRIPTIONS) == set(AntiPattern)

    def test_a_fully_governed_integration_has_no_findings(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(full_observation(record.integration_id))
        assert not detect_anti_patterns(pipeline.inventory, pipeline.portfolio)


class TestMaturity:
    def test_empty_program_is_reactive(self, pipeline):
        assert pipeline.maturity().level == MaturityLevel.REACTIVE

    def test_undeclared_production_integration_stays_at_level_one(self, pipeline):
        app = application()
        pipeline.portfolio.add(app)
        record = pipeline.discover(app, ownership=ownership())
        record.phase = LifecyclePhase.OPERATION
        assessment = pipeline.maturity()
        assert assessment.level == MaturityLevel.REACTIVE
        assert assessment.next_actions

    def test_fully_governed_program_reaches_adaptive(self, pipeline):
        record = promoted(pipeline, application())
        pipeline.observe(full_observation(record.integration_id))
        request = pipeline.evolve(
            record.integration_id,
            EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE,
            policy=GovernancePolicyProfile(certification_cadence=CertificationCadence.QUARTERLY),
        )
        for stage in list(request.outstanding_stages()):
            request.record_stage(stage, "gov@x")
        pipeline.inventory.close_evolution(record.integration_id, request)
        assert pipeline.maturity().level == MaturityLevel.ADAPTIVE
