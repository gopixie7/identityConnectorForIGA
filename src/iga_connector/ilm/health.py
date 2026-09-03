"""Phase 3 — Operational health governance.

Conventional connector monitoring asks whether the connector is running. ILM
recasts health monitoring as a governance obligation: thresholds and
escalation paths are set by the policy the connector serves, and the failure
mode that matters most is the silent one.

A connector that fails noisily is detectable and remediable. A connector that
degrades silently — aggregating a diminishing proportion of accounts, failing
deprovisioning without error propagation, enumerating an incomplete entitlement
set — accumulates governance blind spots across certification cycles.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field

from .charter import HealthThresholds
from .models import Finding, GovernanceOwnership, Severity, utcnow


class HealthIndicator(str, Enum):
    """The five indicators that characterize a connector's operational integrity."""

    AGGREGATION_COMPLETENESS = "aggregation_completeness"
    PROVISIONING_SUCCESS_RATE = "provisioning_success_rate"
    DEPROVISIONING_LATENCY = "deprovisioning_latency"
    ENTITLEMENT_SCHEMA_VALIDATION = "entitlement_schema_validation"
    CREDENTIAL_VALIDITY = "credential_validity"


class HealthState(str, Enum):
    """Governance state of an indicator or of the integration as a whole."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BREACH = "breach"
    UNOBSERVED = "unobserved"


class EscalationTarget(str, Enum):
    """Who a health condition is escalated to.

    The separation matters: governance degradation escalated to a technical
    support queue is how compliance exposure goes unowned.
    """

    NONE = "none"
    TECHNICAL_MAINTAINER = "technical_maintainer"
    GOVERNANCE_OWNER = "governance_owner"


class HealthObservation(BaseModel):
    """One measurement window for a connector's five health indicators."""

    integration_id: str
    observed_at: datetime = Field(default_factory=utcnow)

    accounts_in_target: int | None = Field(default=None, ge=0)
    accounts_aggregated: int | None = Field(default=None, ge=0)
    provisioning_attempted: int = Field(default=0, ge=0)
    provisioning_succeeded: int = Field(default=0, ge=0)
    deprovisioning_latency_hours: float | None = Field(default=None, ge=0)
    entitlements_in_target: int | None = Field(default=None, ge=0)
    entitlements_enumerated: int | None = Field(default=None, ge=0)
    credential_expires_at: datetime | None = None
    errors_reported: int = Field(
        default=0, ge=0, description="Errors the connector surfaced during the window"
    )

    @property
    def aggregation_completeness(self) -> float | None:
        """Proportion of target accounts successfully aggregated in the window."""
        if self.accounts_in_target is None or self.accounts_aggregated is None:
            return None
        if self.accounts_in_target == 0:
            return 1.0
        return self.accounts_aggregated / self.accounts_in_target

    @property
    def provisioning_success_rate(self) -> float | None:
        """Proportion of initiated provisioning actions executed at the target."""
        if self.provisioning_attempted == 0:
            return None
        return self.provisioning_succeeded / self.provisioning_attempted

    @property
    def unmapped_entitlements(self) -> int | None:
        """Entitlements present in the target that the connector does not enumerate."""
        if self.entitlements_in_target is None or self.entitlements_enumerated is None:
            return None
        return max(0, self.entitlements_in_target - self.entitlements_enumerated)

    def credential_days_remaining(self, now: datetime | None = None) -> float | None:
        """Days until the connector's service account credential expires."""
        if self.credential_expires_at is None:
            return None
        reference = now or utcnow()
        return (self.credential_expires_at - reference).total_seconds() / 86400.0


class IndicatorAssessment(BaseModel):
    """Governance assessment of a single health indicator."""

    indicator: HealthIndicator
    state: HealthState
    value: float | None = None
    threshold: float | None = None
    message: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.state in (HealthState.DEGRADED, HealthState.BREACH, HealthState.UNOBSERVED)


class HealthAssessment(BaseModel):
    """Governance verdict on a connector's operational health."""

    integration_id: str
    assessed_at: datetime = Field(default_factory=utcnow)
    state: HealthState = HealthState.HEALTHY
    indicators: list[IndicatorAssessment] = Field(default_factory=list)
    silent_degradation: bool = Field(
        default=False,
        description="Governance coverage is eroding without the connector reporting errors",
    )
    escalate_to: EscalationTarget = EscalationTarget.NONE
    escalation_contact: str = ""
    findings: list[Finding] = Field(default_factory=list)

    def indicator(self, indicator: HealthIndicator) -> IndicatorAssessment | None:
        return next((i for i in self.indicators if i.indicator == indicator), None)

    def actionable_indicators(self) -> list[IndicatorAssessment]:
        return [i for i in self.indicators if i.is_actionable]


_STATE_RANK: dict[HealthState, int] = {
    HealthState.HEALTHY: 0,
    HealthState.UNOBSERVED: 1,
    HealthState.DEGRADED: 2,
    HealthState.BREACH: 3,
}

#: Early-warning bands. Health monitoring thresholds must be calibrated to
#: detect degradation *before* it produces governance exposure, but a band that
#: is too wide reports every healthy window as degraded and trains its audience
#: to ignore it.
#:
#: For a rate, the band consumes a quarter of the headroom left above the
#: threshold; for a budget (latency, unmapped entitlements), it opens at 80% of
#: the budget; for a threshold expressed in days, at 110% of it.
_RATE_WARN_FRACTION = 0.25
_BUDGET_WARN_FRACTION = 0.8
_DAYS_WARN_FRACTION = 1.1


def assess_health(
    observation: HealthObservation,
    thresholds: HealthThresholds,
    history: list[HealthObservation] | None = None,
    ownership: GovernanceOwnership | None = None,
    now: datetime | None = None,
) -> HealthAssessment:
    """Assess one observation against governance-calibrated thresholds.

    `history` is the preceding observations for the same integration, oldest
    first; it is what makes silent degradation detectable, since a connector
    that is quietly losing coverage reports no errors at all.
    """
    now = now or utcnow()
    history = history or []
    indicators: list[IndicatorAssessment] = []
    findings: list[Finding] = []

    indicators.append(
        _assess_minimum(
            HealthIndicator.AGGREGATION_COMPLETENESS,
            observation.aggregation_completeness,
            thresholds.min_aggregation_completeness,
            "Aggregation completeness",
            "accounts are missing from the IGA platform's view of the target",
        )
    )
    indicators.append(
        _assess_minimum(
            HealthIndicator.PROVISIONING_SUCCESS_RATE,
            observation.provisioning_success_rate,
            thresholds.min_provisioning_success_rate,
            "Provisioning success rate",
            "provisioning failures that are not retried or escalated create access gaps",
        )
    )
    indicators.append(
        _assess_maximum(
            HealthIndicator.DEPROVISIONING_LATENCY,
            observation.deprovisioning_latency_hours,
            thresholds.max_deprovisioning_latency_hours,
            "Deprovisioning latency",
            "excessive latency creates an access exposure window",
        )
    )
    unmapped = observation.unmapped_entitlements
    indicators.append(
        _assess_maximum(
            HealthIndicator.ENTITLEMENT_SCHEMA_VALIDATION,
            float(unmapped) if unmapped is not None else None,
            float(thresholds.max_unmapped_entitlements),
            "Entitlement schema validation",
            "entitlements the connector does not enumerate are certification blind spots",
        )
    )
    indicators.append(
        _assess_minimum(
            HealthIndicator.CREDENTIAL_VALIDITY,
            observation.credential_days_remaining(now),
            float(thresholds.min_credential_days_remaining),
            "Credential validity",
            "credential expiration is the most common cause of silent connector failure",
        )
    )

    state = max((i.state for i in indicators), key=lambda s: _STATE_RANK[s])

    age_hours = (now - observation.observed_at).total_seconds() / 3600.0
    if age_hours > thresholds.max_observation_age_hours:
        state = _worse(state, HealthState.UNOBSERVED)
        findings.append(
            Finding(
                code="health.stale_observation",
                severity=Severity.HIGH,
                message=(
                    f"Last health observation is {age_hours:.0f}h old, beyond the "
                    f"{thresholds.max_observation_age_hours:.0f}h governance window."
                ),
                remediation="Restore health collection; an unobserved connector is ungoverned.",
            )
        )

    silent = _detect_silent_degradation(observation, history, thresholds)
    if silent:
        findings.append(
            Finding(
                code="health.silent_degradation",
                severity=Severity.HIGH,
                message=(
                    "Governance coverage is declining while the connector reports no errors: "
                    "degradation of this kind accumulates across certification cycles before "
                    "it becomes visible."
                ),
                remediation=(
                    "Investigate target application change, schema drift, or credential scope "
                    "reduction; escalate to the governance owner, not the support queue."
                ),
            )
        )
        state = _worse(state, HealthState.DEGRADED)

    for indicator in indicators:
        if indicator.state == HealthState.BREACH:
            findings.append(
                Finding(
                    code=f"health.breach.{indicator.indicator.value}",
                    severity=Severity.BLOCKING,
                    message=indicator.message,
                    remediation="Remediate before the next certification campaign closes.",
                )
            )

    escalate = EscalationTarget.NONE
    contact = ""
    if state == HealthState.BREACH or silent or state == HealthState.UNOBSERVED:
        escalate = EscalationTarget.GOVERNANCE_OWNER
        contact = ownership.governance_owner if ownership else ""
    elif state == HealthState.DEGRADED:
        escalate = EscalationTarget.TECHNICAL_MAINTAINER
        contact = ownership.technical_maintainer if ownership else ""

    return HealthAssessment(
        integration_id=observation.integration_id,
        assessed_at=now,
        state=state,
        indicators=indicators,
        silent_degradation=silent,
        escalate_to=escalate,
        escalation_contact=contact,
        findings=findings,
    )


def _worse(left: HealthState, right: HealthState) -> HealthState:
    return left if _STATE_RANK[left] >= _STATE_RANK[right] else right


def _assess_minimum(
    indicator: HealthIndicator,
    value: float | None,
    threshold: float,
    label: str,
    consequence: str,
) -> IndicatorAssessment:
    """Assess an indicator where a higher value is healthier."""
    if value is None:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.UNOBSERVED,
            threshold=threshold,
            message=f"{label} was not measured in this window.",
        )
    if value < threshold:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.BREACH,
            value=value,
            threshold=threshold,
            message=f"{label} {value:.4g} is below the governance threshold "
            f"{threshold:.4g}: {consequence}.",
        )
    warn_at = (
        threshold + (1.0 - threshold) * _RATE_WARN_FRACTION
        if threshold <= 1
        else threshold * _DAYS_WARN_FRACTION
    )
    if value < warn_at:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.DEGRADED,
            value=value,
            threshold=threshold,
            message=f"{label} {value:.4g} is within the early-warning band above "
            f"{threshold:.4g}.",
        )
    return IndicatorAssessment(
        indicator=indicator,
        state=HealthState.HEALTHY,
        value=value,
        threshold=threshold,
        message=f"{label} {value:.4g} meets the governance threshold.",
    )


def _assess_maximum(
    indicator: HealthIndicator,
    value: float | None,
    threshold: float,
    label: str,
    consequence: str,
) -> IndicatorAssessment:
    """Assess an indicator where a lower value is healthier."""
    if value is None:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.UNOBSERVED,
            threshold=threshold,
            message=f"{label} was not measured in this window.",
        )
    if value > threshold:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.BREACH,
            value=value,
            threshold=threshold,
            message=f"{label} {value:.4g} exceeds the governance threshold "
            f"{threshold:.4g}: {consequence}.",
        )
    if threshold > 0 and value > threshold * _BUDGET_WARN_FRACTION:
        return IndicatorAssessment(
            indicator=indicator,
            state=HealthState.DEGRADED,
            value=value,
            threshold=threshold,
            message=f"{label} {value:.4g} is approaching the governance threshold "
            f"{threshold:.4g}.",
        )
    return IndicatorAssessment(
        indicator=indicator,
        state=HealthState.HEALTHY,
        value=value,
        threshold=threshold,
        message=f"{label} {value:.4g} is within the governance threshold.",
    )


def _detect_silent_degradation(
    observation: HealthObservation,
    history: list[HealthObservation],
    thresholds: HealthThresholds,
) -> bool:
    """Detect coverage erosion that the connector itself is not reporting.

    Silence is the precondition: a connector throwing errors is already
    detectable. What ILM adds is the case where nothing is thrown and coverage
    still declines — falling aggregation completeness, or an entitlement set
    that the connector enumerates less and less of.
    """
    if observation.errors_reported > 0:
        return False

    current = observation.aggregation_completeness
    previous = [
        o.aggregation_completeness for o in history if o.aggregation_completeness is not None
    ]
    if current is not None and previous:
        baseline = max(previous[-3:])
        if baseline - current > thresholds.silent_drift_tolerance:
            return True

    unmapped_now = observation.unmapped_entitlements
    unmapped_before = [
        o.unmapped_entitlements for o in history if o.unmapped_entitlements is not None
    ]
    if unmapped_now is not None and unmapped_before and unmapped_now > min(unmapped_before[-3:]):
        return True

    rate_now = observation.provisioning_success_rate
    rates_before = [
        o.provisioning_success_rate for o in history if o.provisioning_success_rate is not None
    ]
    if rate_now is not None and rates_before:
        if max(rates_before[-3:]) - rate_now > thresholds.silent_drift_tolerance:
            return True

    return False


def observation_window(hours: float) -> tuple[datetime, datetime]:
    """Convenience helper returning the (start, end) of a collection window."""
    end = utcnow()
    return end - timedelta(hours=hours), end
