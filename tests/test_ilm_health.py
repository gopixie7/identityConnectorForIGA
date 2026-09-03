"""Tests for Phase 3 — operational health governance and silent failure."""

from datetime import datetime, timedelta, timezone

import pytest

from iga_connector.ilm import (
    EscalationTarget,
    GovernanceOwnership,
    HealthIndicator,
    HealthObservation,
    HealthState,
    HealthThresholds,
    assess_health,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def thresholds():
    return HealthThresholds(
        min_aggregation_completeness=0.99,
        min_provisioning_success_rate=0.98,
        max_deprovisioning_latency_hours=24.0,
        max_unmapped_entitlements=2,
        min_credential_days_remaining=21,
        max_observation_age_hours=72.0,
        silent_drift_tolerance=0.01,
    )


@pytest.fixture
def ownership():
    return GovernanceOwnership(governance_owner="gov@x.com", technical_maintainer="eng@x.com")


def healthy(**overrides) -> HealthObservation:
    defaults = dict(
        integration_id="int-1",
        observed_at=NOW,
        accounts_in_target=1000,
        accounts_aggregated=1000,
        provisioning_attempted=100,
        provisioning_succeeded=100,
        deprovisioning_latency_hours=1.0,
        entitlements_in_target=40,
        entitlements_enumerated=40,
        credential_expires_at=NOW + timedelta(days=90),
        errors_reported=0,
    )
    defaults.update(overrides)
    return HealthObservation(**defaults)


class TestObservationMetrics:
    def test_derived_rates(self):
        observation = healthy(accounts_aggregated=950, provisioning_succeeded=90)
        assert observation.aggregation_completeness == 0.95
        assert observation.provisioning_success_rate == 0.9

    def test_unmeasured_metrics_are_none(self):
        observation = HealthObservation(integration_id="int-1")
        assert observation.aggregation_completeness is None
        assert observation.provisioning_success_rate is None
        assert observation.unmapped_entitlements is None
        assert observation.credential_days_remaining(NOW) is None

    def test_empty_target_counts_as_complete(self):
        assert healthy(accounts_in_target=0, accounts_aggregated=0).aggregation_completeness == 1.0

    def test_unmapped_entitlements_never_negative(self):
        observation = healthy(entitlements_in_target=10, entitlements_enumerated=12)
        assert observation.unmapped_entitlements == 0


class TestAssessment:
    def test_healthy_observation(self, thresholds, ownership):
        assessment = assess_health(healthy(), thresholds, ownership=ownership, now=NOW)
        assert assessment.state == HealthState.HEALTHY
        assert assessment.escalate_to == EscalationTarget.NONE
        assert not assessment.actionable_indicators()

    def test_completeness_breach_escalates_to_governance_owner(self, thresholds, ownership):
        assessment = assess_health(
            healthy(accounts_aggregated=900), thresholds, ownership=ownership, now=NOW
        )
        assert assessment.state == HealthState.BREACH
        assert assessment.escalate_to == EscalationTarget.GOVERNANCE_OWNER
        assert assessment.escalation_contact == "gov@x.com"

    def test_degradation_escalates_to_technical_maintainer(self, thresholds, ownership):
        # Latency inside the budget but past the early-warning band.
        assessment = assess_health(
            healthy(deprovisioning_latency_hours=22.0), thresholds, ownership=ownership, now=NOW
        )
        assert assessment.state == HealthState.DEGRADED
        assert assessment.escalate_to == EscalationTarget.TECHNICAL_MAINTAINER

    def test_latency_breach_is_reported(self, thresholds):
        assessment = assess_health(healthy(deprovisioning_latency_hours=48.0), thresholds, now=NOW)
        indicator = assessment.indicator(HealthIndicator.DEPROVISIONING_LATENCY)
        assert indicator.state == HealthState.BREACH

    def test_schema_drift_breaches(self, thresholds):
        assessment = assess_health(
            healthy(entitlements_in_target=50, entitlements_enumerated=40), thresholds, now=NOW
        )
        indicator = assessment.indicator(HealthIndicator.ENTITLEMENT_SCHEMA_VALIDATION)
        assert indicator.state == HealthState.BREACH
        assert indicator.value == 10

    def test_expiring_credential_breaches(self, thresholds):
        assessment = assess_health(
            healthy(credential_expires_at=NOW + timedelta(days=5)), thresholds, now=NOW
        )
        indicator = assessment.indicator(HealthIndicator.CREDENTIAL_VALIDITY)
        assert indicator.state == HealthState.BREACH

    def test_unmeasured_indicator_is_unobserved(self, thresholds):
        assessment = assess_health(
            HealthObservation(integration_id="int-1", observed_at=NOW), thresholds, now=NOW
        )
        assert assessment.state == HealthState.UNOBSERVED
        assert assessment.escalate_to == EscalationTarget.GOVERNANCE_OWNER

    def test_stale_observation_is_a_governance_finding(self, thresholds):
        assessment = assess_health(
            healthy(observed_at=NOW - timedelta(days=10)), thresholds, now=NOW
        )
        assert assessment.state == HealthState.UNOBSERVED
        assert any(f.code == "health.stale_observation" for f in assessment.findings)


class TestSilentDegradation:
    def test_declining_completeness_without_errors_is_silent(self, thresholds, ownership):
        history = [healthy(observed_at=NOW - timedelta(hours=h)) for h in (3, 2, 1)]
        assessment = assess_health(
            healthy(accounts_aggregated=970), thresholds, history=history,
            ownership=ownership, now=NOW,
        )
        assert assessment.silent_degradation
        assert assessment.escalate_to == EscalationTarget.GOVERNANCE_OWNER
        assert any(f.code == "health.silent_degradation" for f in assessment.findings)

    def test_a_noisy_connector_is_not_silently_degrading(self, thresholds):
        history = [healthy(observed_at=NOW - timedelta(hours=h)) for h in (3, 2, 1)]
        assessment = assess_health(
            healthy(accounts_aggregated=900, errors_reported=12), thresholds,
            history=history, now=NOW,
        )
        assert not assessment.silent_degradation
        assert assessment.state == HealthState.BREACH

    def test_growing_unmapped_entitlement_set_is_silent_drift(self, thresholds):
        history = [
            healthy(observed_at=NOW - timedelta(hours=2), entitlements_in_target=40,
                    entitlements_enumerated=40)
        ]
        assessment = assess_health(
            healthy(entitlements_in_target=41, entitlements_enumerated=40),
            thresholds, history=history, now=NOW,
        )
        assert assessment.silent_degradation

    def test_falling_provisioning_rate_is_silent_drift(self, thresholds):
        history = [healthy(observed_at=NOW - timedelta(hours=2))]
        assessment = assess_health(
            healthy(provisioning_succeeded=95), thresholds, history=history, now=NOW
        )
        assert assessment.silent_degradation

    def test_no_history_means_no_drift_signal(self, thresholds):
        assessment = assess_health(healthy(accounts_aggregated=995), thresholds, now=NOW)
        assert not assessment.silent_degradation
        assert assessment.state == HealthState.HEALTHY

    def test_drift_within_tolerance_is_not_flagged(self, thresholds):
        history = [healthy(observed_at=NOW - timedelta(hours=2))]
        assessment = assess_health(
            healthy(accounts_aggregated=997), thresholds, history=history, now=NOW
        )
        assert not assessment.silent_degradation
