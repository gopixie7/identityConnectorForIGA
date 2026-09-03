"""Integration governance anti-patterns.

The framework names four anti-patterns that occur across IGA programs of
varying maturity. Recognizing them is the first step toward remediation, so
they are implemented as detectors that run over the governance inventory and
the application portfolio rather than as prose.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field

from .apm import APMLifecycleStage, ApplicationPortfolio
from .evolution import EvolutionTrigger
from .inventory import IntegrationGovernanceInventory, IntegrationRecord
from .models import LifecyclePhase, Severity, utcnow


class AntiPattern(str, Enum):
    """The four named integration governance anti-patterns."""

    BUILD_AND_FORGET = "build_and_forget"
    UNGOVERNED_RETIREMENT = "ungoverned_retirement"
    TECHNICAL_EVOLUTION_ONLY = "technical_evolution_only"
    APM_IGA_DISCONNECTION = "apm_iga_disconnection"


ANTI_PATTERN_DESCRIPTIONS: dict[AntiPattern, str] = {
    AntiPattern.BUILD_AND_FORGET: (
        "The connector is deployed, the project is closed, and no lifecycle governance is "
        "established. The most prevalent and most costly anti-pattern, and the primary source "
        "of governance blind spots and connector degradation."
    ),
    AntiPattern.UNGOVERNED_RETIREMENT: (
        "Connectors are decommissioned without governance disposition — without orphaned "
        "account remediation, certification resolution, or audit trail preservation."
    ),
    AntiPattern.TECHNICAL_EVOLUTION_ONLY: (
        "Connector evolution is triggered exclusively by target application changes, with no "
        "process for governance-triggered evolution."
    ),
    AntiPattern.APM_IGA_DISCONNECTION: (
        "The APM system and the IGA platform are operated as independent silos, so application "
        "onboarding to IGA is driven by escalation and audit rather than application lifecycle."
    ),
}


class AntiPatternFinding(BaseModel):
    """One detected instance of an anti-pattern."""

    anti_pattern: AntiPattern
    severity: Severity = Severity.HIGH
    subject: str = Field(default="", description="Integration or application it was found on")
    evidence: str = ""
    remediation: str = ""

    @property
    def description(self) -> str:
        return ANTI_PATTERN_DESCRIPTIONS[self.anti_pattern]


def detect_anti_patterns(
    inventory: IntegrationGovernanceInventory,
    portfolio: ApplicationPortfolio | None = None,
    now: datetime | None = None,
    apm_sync_staleness_days: int = 30,
) -> list[AntiPatternFinding]:
    """Scan the governance inventory for all four anti-patterns."""
    now = now or utcnow()
    findings: list[AntiPatternFinding] = []
    for record in inventory.records:
        findings.extend(_build_and_forget(record, now))
        findings.extend(_ungoverned_retirement(record, portfolio))
        findings.extend(_technical_evolution_only(record))
    findings.extend(_apm_disconnection(inventory, portfolio, now, apm_sync_staleness_days))
    return findings


def _build_and_forget(record: IntegrationRecord, now: datetime) -> list[AntiPatternFinding]:
    """An integration in production with no live governance around it."""
    if record.phase not in (LifecyclePhase.OPERATION, LifecyclePhase.EVOLUTION):
        return []

    findings: list[AntiPatternFinding] = []
    if record.capability_map is None:
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.BUILD_AND_FORGET,
                severity=Severity.BLOCKING,
                subject=record.integration_id,
                evidence="In production governance with no capability specification registered.",
                remediation="Complete a retroactive capability declaration for this integration.",
            )
        )
    if record.ownership is None or not record.ownership.governance_owner:
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.BUILD_AND_FORGET,
                severity=Severity.HIGH,
                subject=record.integration_id,
                evidence="No named governance owner is accountable for this integration.",
                remediation="Name a governance owner distinct from the technical maintainer.",
            )
        )
    if not record.health_history:
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.BUILD_AND_FORGET,
                severity=Severity.HIGH,
                subject=record.integration_id,
                evidence="No health observation has ever been recorded.",
                remediation="Start collecting the five ILM health indicators for this connector.",
            )
        )
    else:
        thresholds = (
            record.requirements.health_thresholds.max_observation_age_hours
            if record.requirements
            else 168.0
        )
        last = record.health_history[-1].observed_at
        if now - last > timedelta(hours=thresholds):
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.BUILD_AND_FORGET,
                    severity=Severity.MEDIUM,
                    subject=record.integration_id,
                    evidence=(
                        f"Last health observation was {(now - last).days} day(s) ago, beyond "
                        f"the {thresholds:.0f}h governance window."
                    ),
                    remediation="Restore health collection; an unobserved connector is ungoverned.",
                )
            )
    return findings


def _ungoverned_retirement(
    record: IntegrationRecord, portfolio: ApplicationPortfolio | None
) -> list[AntiPatternFinding]:
    """Coverage removed, or its application decommissioned, without disposition."""
    findings: list[AntiPatternFinding] = []

    if record.phase == LifecyclePhase.RETIRED:
        retirement = record.retirement
        if retirement is None or not retirement.disposition.authorized:
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.UNGOVERNED_RETIREMENT,
                    severity=Severity.BLOCKING,
                    subject=record.integration_id,
                    evidence="Marked retired with no authorized governance disposition.",
                    remediation=(
                        "Reconstruct the retirement checklist: certification resolution, "
                        "entitlement disposition, orphan remediation, audit trail preservation."
                    ),
                )
            )
        elif retirement.outstanding():
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.UNGOVERNED_RETIREMENT,
                    severity=Severity.HIGH,
                    subject=record.integration_id,
                    evidence=(
                        "Retired with unresolved obligations: "
                        + ", ".join(i.obligation.value for i in retirement.outstanding())
                    ),
                    remediation="Discharge the remaining obligations and record the evidence.",
                )
            )

    if portfolio is not None and record.is_active:
        application = portfolio.get(record.application_id)
        decommissioned = application is not None and application.stage in (
            APMLifecycleStage.SUNSET,
            APMLifecycleStage.DECOMMISSIONED,
        )
        if decommissioned and record.retirement is None:
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.UNGOVERNED_RETIREMENT,
                    severity=Severity.HIGH,
                    subject=record.integration_id,
                    evidence=(
                        f"Application '{record.application_id}' has reached "
                        f"{application.stage.value if application else 'sunset'} in the APM, but "
                        "no governed retirement has been opened."
                    ),
                    remediation="Open the retirement window and work the obligation checklist.",
                )
            )
    return findings


def _technical_evolution_only(record: IntegrationRecord) -> list[AntiPatternFinding]:
    """Evolution history driven by target change alone, never by policy."""
    requests = record.evolution_requests
    if not requests:
        return []

    governance_triggered = [r for r in requests if r.trigger.is_governance_triggered]
    findings: list[AntiPatternFinding] = []
    if len(requests) >= 2 and not governance_triggered:
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.TECHNICAL_EVOLUTION_ONLY,
                severity=Severity.MEDIUM,
                subject=record.integration_id,
                evidence=(
                    f"All {len(requests)} recorded evolutions were triggered by "
                    f"{EvolutionTrigger.TARGET_TECHNICAL_CHANGE.value}; no policy change has "
                    "ever reached this integration."
                ),
                remediation=(
                    "Wire policy changes to an integration requirement specification update as "
                    "a standard workflow output."
                ),
            )
        )

    for request in governance_triggered:
        if request.is_closed():
            continue
        outstanding = ", ".join(s.value for s in request.outstanding_stages())
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.TECHNICAL_EVOLUTION_ONLY,
                severity=Severity.HIGH,
                subject=record.integration_id,
                evidence=(
                    f"Governance-triggered evolution ({request.trigger.value}) stalled with "
                    f"outstanding stages: {outstanding}."
                ),
                remediation=(
                    "Carry the policy decision through to a revised capability specification "
                    "before the next audit cycle."
                ),
            )
        )
    return findings


def _apm_disconnection(
    inventory: IntegrationGovernanceInventory,
    portfolio: ApplicationPortfolio | None,
    now: datetime,
    staleness_days: int,
) -> list[AntiPatternFinding]:
    """APM and IGA operated as independent silos."""
    if portfolio is None:
        return [
            AntiPatternFinding(
                anti_pattern=AntiPattern.APM_IGA_DISCONNECTION,
                severity=Severity.HIGH,
                subject="portfolio",
                evidence="No application portfolio is available to the governance inventory.",
                remediation=(
                    "Establish structured data exchange between the APM system and the IGA "
                    "platform so application lifecycle events drive integration governance."
                ),
            )
        ]

    findings: list[AntiPatternFinding] = []
    if portfolio.last_synced_at is None:
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.APM_IGA_DISCONNECTION,
                severity=Severity.MEDIUM,
                subject="portfolio",
                evidence="APM metadata has never been synchronized with the IGA platform.",
                remediation="Schedule APM synchronization and audit IGA-relevant field quality.",
            )
        )
    elif now - portfolio.last_synced_at > timedelta(days=staleness_days):
        findings.append(
            AntiPatternFinding(
                anti_pattern=AntiPattern.APM_IGA_DISCONNECTION,
                severity=Severity.MEDIUM,
                subject="portfolio",
                evidence=(
                    f"APM metadata was last synchronized "
                    f"{(now - portfolio.last_synced_at).days} day(s) ago."
                ),
                remediation="Restore APM synchronization.",
            )
        )

    known_ids = {a.application_id for a in portfolio.applications}
    for record in inventory.records:
        if record.application_id not in known_ids:
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.APM_IGA_DISCONNECTION,
                    severity=Severity.HIGH,
                    subject=record.integration_id,
                    evidence=(
                        f"Integration governs application '{record.application_id}', which has "
                        "no record in the application portfolio."
                    ),
                    remediation=(
                        "Reconcile the integration against the APM catalog; an application "
                        "unknown to the APM cannot emit the lifecycle events ILM depends on."
                    ),
                )
            )

    for application in portfolio.in_scope():
        if not inventory.for_application(application.application_id):
            findings.append(
                AntiPatternFinding(
                    anti_pattern=AntiPattern.APM_IGA_DISCONNECTION,
                    severity=Severity.MEDIUM,
                    subject=application.application_id,
                    evidence=(
                        "Application reached production in the APM without activating an IGA "
                        "onboarding workflow."
                    ),
                    remediation=(
                        "Route APM production transitions into governance-driven discovery."
                    ),
                )
            )
    return findings
