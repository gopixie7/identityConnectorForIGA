"""The integration governance inventory.

The inventory is the registry of record for ILM: every integration, whatever
path it took, is registered here with its requirement specification, its
capability specification, its named owners, its health history, and its
retirement disposition.

Two things become possible once the inventory exists. Blind-spot mapping —
comparing the application portfolio against active coverage — makes visible the
applications that policy governs but no integration reaches. And anti-pattern
detection has something to run against.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..core.exceptions import ConfigurationError
from .apm import ApplicationPortfolio, ApplicationRecord
from .capability import CapabilityValidation, ConnectorCapabilityMap
from .charter import ConnectorGovernanceCharter
from .discovery import IntegrationRequirementSpec
from .evolution import EvolutionRequest
from .health import HealthAssessment, HealthObservation, HealthState, assess_health
from .models import (
    Finding,
    GovernanceOwnership,
    IntegrationPath,
    LifecyclePhase,
    RiskClassification,
    Severity,
    utcnow,
)
from .retirement import GovernedRetirement
from .strategy import StrategyDecision


class PromotionBlockedError(Exception):
    """Raised when an integration is promoted to production governance too early."""

    def __init__(self, message: str, findings: list[Finding] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


class IntegrationRecord(BaseModel):
    """One integration, tracked across all five lifecycle phases."""

    integration_id: str
    application_id: str
    phase: LifecyclePhase = LifecyclePhase.DISCOVERY
    path: IntegrationPath | None = None
    requirements: IntegrationRequirementSpec | None = None
    strategy: StrategyDecision | None = None
    capability_map: ConnectorCapabilityMap | None = None
    ownership: GovernanceOwnership | None = None
    health_history: list[HealthObservation] = Field(default_factory=list)
    last_assessment: HealthAssessment | None = None
    evolution_requests: list[EvolutionRequest] = Field(default_factory=list)
    retirement: GovernedRetirement | None = None
    registered_at: datetime = Field(default_factory=utcnow)
    promoted_at: datetime | None = None
    retired_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """True while the integration is providing production governance coverage."""
        return self.phase in (
            LifecyclePhase.OPERATION,
            LifecyclePhase.EVOLUTION,
            LifecyclePhase.RETIREMENT,
        )

    @property
    def provides_coverage(self) -> bool:
        """True when this integration counts as governance coverage for its application."""
        return self.is_active and self.capability_map is not None

    def open_evolution_requests(self) -> list[EvolutionRequest]:
        return [r for r in self.evolution_requests if not r.is_closed()]


class BlindSpot(BaseModel):
    """An in-scope application with no active, functioning integration covering it."""

    application_id: str
    application_name: str = ""
    risk_classification: RiskClassification = RiskClassification.MODERATE
    reason: str = ""
    severity: Severity = Severity.HIGH
    regulatory_scope: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """Portfolio-level view of governance coverage."""

    generated_at: datetime = Field(default_factory=utcnow)
    applications_in_scope: int = 0
    applications_covered: int = 0
    blind_spots: list[BlindSpot] = Field(default_factory=list)
    integrations_by_phase: dict[str, int] = Field(default_factory=dict)
    integrations_by_path: dict[str, int] = Field(default_factory=dict)
    unhealthy_integrations: list[str] = Field(default_factory=list)

    @property
    def coverage_rate(self) -> float:
        """Proportion of in-scope applications reached by an active integration."""
        if self.applications_in_scope == 0:
            return 1.0
        return self.applications_covered / self.applications_in_scope


class IntegrationGovernanceInventory(BaseModel):
    """Registry of record for every governed integration.

    Usage:
        inventory = IntegrationGovernanceInventory(charter=charter)
        record = inventory.register("crm-prod", requirements, strategy)
        inventory.attach_capability_map("crm-prod", capability_map)
        inventory.promote("crm-prod")           # validates before production
        inventory.record_health(observation)
        report = inventory.coverage_report(portfolio)
    """

    charter: ConnectorGovernanceCharter = Field(default_factory=ConnectorGovernanceCharter)
    records: list[IntegrationRecord] = Field(default_factory=list)
    max_health_history: int = Field(
        default=50, ge=1, description="Observations retained per integration"
    )

    # --- registration -----------------------------------------------------

    def get(self, integration_id: str) -> IntegrationRecord | None:
        return next((r for r in self.records if r.integration_id == integration_id), None)

    def require(self, integration_id: str) -> IntegrationRecord:
        record = self.get(integration_id)
        if record is None:
            raise KeyError(f"Integration '{integration_id}' is not in the governance inventory")
        return record

    def for_application(self, application_id: str) -> list[IntegrationRecord]:
        return [r for r in self.records if r.application_id == application_id]

    def register(
        self,
        integration_id: str,
        requirements: IntegrationRequirementSpec,
        strategy: StrategyDecision | None = None,
        ownership: GovernanceOwnership | None = None,
    ) -> IntegrationRecord:
        """Register an integration at the end of Phase 1."""
        if self.get(integration_id) is not None:
            raise ConfigurationError(f"Integration '{integration_id}' is already registered")
        record = IntegrationRecord(
            integration_id=integration_id,
            application_id=requirements.application_id,
            phase=LifecyclePhase.DISCOVERY,
            requirements=requirements,
            strategy=strategy,
            path=strategy.path if strategy else None,
            ownership=ownership,
        )
        self.records.append(record)
        return record

    def attach_capability_map(
        self, integration_id: str, capability_map: ConnectorCapabilityMap
    ) -> IntegrationRecord:
        """Attach the Phase 2 capability specification and enter development."""
        record = self.require(integration_id)
        record.capability_map = capability_map
        if capability_map.ownership is not None:
            record.ownership = capability_map.ownership
        record.path = capability_map.path
        if record.phase == LifecyclePhase.DISCOVERY:
            record.phase = LifecyclePhase.DEVELOPMENT
        return record

    # --- promotion --------------------------------------------------------

    def validate_capability(self, integration_id: str) -> CapabilityValidation:
        """Validate declared capability against the governance baseline."""
        record = self.require(integration_id)
        if record.requirements is None:
            raise PromotionBlockedError(
                f"'{integration_id}' has no integration requirement specification; "
                "Phase 1 discovery has not been completed."
            )
        if record.capability_map is None:
            return CapabilityValidation(
                application_id=record.application_id,
                compliant=False,
                findings=[
                    Finding(
                        code="capability.map_missing",
                        severity=Severity.BLOCKING,
                        message="No capability specification is registered for this integration.",
                        remediation="Declare capability before production promotion.",
                    )
                ],
            )
        return record.capability_map.validate_against(
            record.requirements,
            allow_partial_with_gap_control=self.charter.allow_partial_coverage_with_gap_control,
            require_separated_ownership=self.charter.require_separated_ownership,
        )

    def promote(self, integration_id: str) -> IntegrationRecord:
        """Promote an integration into production governance.

        The charter's promotion gate is enforced here: an integration whose
        capability specification is missing, or which carries a blocking
        validation finding, does not reach production governance.
        """
        record = self.require(integration_id)
        validation = self.validate_capability(integration_id)
        if self.charter.require_capability_map_before_production and not validation.promotable():
            raise PromotionBlockedError(
                f"'{integration_id}' cannot be promoted: "
                + "; ".join(f.message for f in validation.blocking_findings),
                findings=validation.blocking_findings,
            )
        record.phase = LifecyclePhase.OPERATION
        record.promoted_at = utcnow()
        return record

    # --- phase 3 ----------------------------------------------------------

    def record_health(self, observation: HealthObservation) -> HealthAssessment:
        """Record an observation and assess it against the governance thresholds."""
        record = self.require(observation.integration_id)
        thresholds = (
            record.requirements.health_thresholds
            if record.requirements
            else self.charter.thresholds_for(RiskClassification.MODERATE)
        )
        assessment = assess_health(
            observation,
            thresholds=thresholds,
            history=record.health_history,
            ownership=record.ownership,
        )
        record.health_history.append(observation)
        if len(record.health_history) > self.max_health_history:
            record.health_history = record.health_history[-self.max_health_history :]
        record.last_assessment = assessment
        return assessment

    # --- phase 4 ----------------------------------------------------------

    def record_evolution(self, request: EvolutionRequest) -> IntegrationRecord:
        """Track an evolution request against its integration."""
        record = self.require(request.integration_id)
        record.evolution_requests = [
            r for r in record.evolution_requests if not _same_request(r, request)
        ]
        record.evolution_requests.append(request)
        if request.requires_connector_work and record.phase == LifecyclePhase.OPERATION:
            record.phase = LifecyclePhase.EVOLUTION
        return record

    def close_evolution(self, integration_id: str, request: EvolutionRequest) -> IntegrationRecord:
        """Return an integration to operation once an evolution is fully traced."""
        record = self.require(integration_id)
        self.record_evolution(request)
        if record.phase == LifecyclePhase.EVOLUTION and not record.open_evolution_requests():
            record.phase = LifecyclePhase.OPERATION
        return record

    # --- phase 5 ----------------------------------------------------------

    def open_retirement(self, retirement: GovernedRetirement) -> IntegrationRecord:
        """Open the governed retirement window for an integration."""
        record = self.require(retirement.integration_id)
        record.retirement = retirement
        record.phase = LifecyclePhase.RETIREMENT
        return record

    def retire(self, integration_id: str, authorized_by: str, notes: str = "") -> IntegrationRecord:
        """Authorize disposition and mark the integration retired.

        Raises `RetirementBlockedError` while any obligation is outstanding.
        """
        record = self.require(integration_id)
        if record.retirement is None:
            raise PromotionBlockedError(
                f"'{integration_id}' has no open retirement: technical removal without a "
                "governance disposition is an ungoverned retirement."
            )
        record.retirement.authorize(authorized_by=authorized_by, notes=notes)
        record.phase = LifecyclePhase.RETIRED
        record.retired_at = utcnow()
        return record

    # --- portfolio views --------------------------------------------------

    def blind_spots(self, portfolio: ApplicationPortfolio) -> list[BlindSpot]:
        """Applications in governance scope that no active integration covers.

        A blind spot is invisible by construction, so it is derived rather than
        reported: it is what remains when active coverage is subtracted from
        the portfolio that policy places in scope.
        """
        spots: list[BlindSpot] = []
        for application in portfolio.in_scope():
            records = self.for_application(application.application_id)
            covering = [r for r in records if r.provides_coverage]
            if covering:
                unhealthy = [
                    r
                    for r in covering
                    if r.last_assessment is not None
                    and r.last_assessment.state in (HealthState.BREACH, HealthState.UNOBSERVED)
                ]
                if not unhealthy:
                    continue
                reason = (
                    "Covered by an integration whose health has breached its governance "
                    "thresholds; coverage is nominal, not effective."
                )
            elif records:
                reason = (
                    "An integration is registered but is not in production governance "
                    f"(phase: {records[0].phase.value})."
                )
            else:
                reason = "No integration is registered for this in-scope application."

            spots.append(
                BlindSpot(
                    application_id=application.application_id,
                    application_name=application.name,
                    risk_classification=application.risk_classification,
                    reason=reason,
                    severity=_blind_spot_severity(application),
                    regulatory_scope=[f.value for f in application.regulatory_scope],
                )
            )
        return spots

    def coverage_report(self, portfolio: ApplicationPortfolio) -> CoverageReport:
        """Portfolio-level governance coverage, the reporting artifact ILM produces."""
        in_scope = portfolio.in_scope()
        spots = self.blind_spots(portfolio)
        blind_ids = {s.application_id for s in spots}

        by_phase: dict[str, int] = {}
        by_path: dict[str, int] = {}
        unhealthy: list[str] = []
        for record in self.records:
            by_phase[record.phase.value] = by_phase.get(record.phase.value, 0) + 1
            if record.path is not None:
                by_path[record.path.value] = by_path.get(record.path.value, 0) + 1
            if record.last_assessment and record.last_assessment.state != HealthState.HEALTHY:
                unhealthy.append(record.integration_id)

        return CoverageReport(
            applications_in_scope=len(in_scope),
            applications_covered=len([a for a in in_scope if a.application_id not in blind_ids]),
            blind_spots=spots,
            integrations_by_phase=by_phase,
            integrations_by_path=by_path,
            unhealthy_integrations=unhealthy,
        )

    # --- persistence ------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        """Persist the inventory to YAML or JSON."""
        target = Path(path)
        payload = json.loads(self.model_dump_json())
        if target.suffix in (".yaml", ".yml"):
            target.write_text(yaml.safe_dump(payload, sort_keys=False))
        elif target.suffix == ".json":
            target.write_text(json.dumps(payload, indent=2))
        else:
            raise ConfigurationError(f"Unsupported inventory format: {target.suffix}")
        return target

    @classmethod
    def load(cls, source: str | Path | dict[str, Any]) -> IntegrationGovernanceInventory:
        """Load an inventory from a YAML/JSON file or a plain dict."""
        if isinstance(source, dict):
            return cls(**source)
        path = Path(source)
        if not path.exists():
            raise ConfigurationError(f"Inventory file not found: {path}")
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(text)
        elif path.suffix == ".json":
            raw = json.loads(text)
        else:
            raise ConfigurationError(f"Unsupported inventory format: {path.suffix}")
        return cls(**(raw or {}))


def _same_request(left: EvolutionRequest, right: EvolutionRequest) -> bool:
    return left.trigger == right.trigger and left.raised_at == right.raised_at


def _blind_spot_severity(application: ApplicationRecord) -> Severity:
    critical = application.risk_classification == RiskClassification.CRITICAL
    if application.regulatory_scope or critical:
        return Severity.BLOCKING
    if application.risk_classification == RiskClassification.HIGH:
        return Severity.HIGH
    return Severity.MEDIUM
