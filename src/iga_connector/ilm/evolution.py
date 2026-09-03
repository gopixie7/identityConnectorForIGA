"""Phase 4 — Governance-triggered evolution.

Conventional connector evolution is technically triggered: the target
application changes its API and the connector is updated. That is necessary
but insufficient. ILM adds a second, equally important trigger — governance
policy change — and requires it to be traceable from the policy decision
through requirement specification update, capability enhancement, and
capability specification revision.

Without that chain, a policy change that implies new connector capabilities is
an ad hoc request that may or may not reach the integration team before the
next audit cycle.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .capability import ConnectorCapabilityMap
from .discovery import IntegrationRequirementSpec, RequiredOperation
from .models import CoverageLevel, GovernanceOperation, Severity, utcnow


class EvolutionTrigger(str, Enum):
    """What caused an integration to require evolution."""

    SOD_RULE_EXPANSION = "sod_rule_expansion"
    CERTIFICATION_REQUIREMENT_CHANGE = "certification_requirement_change"
    REGULATORY_SCOPE_EXPANSION = "regulatory_scope_expansion"
    RISK_RECLASSIFICATION = "risk_reclassification"
    TARGET_TECHNICAL_CHANGE = "target_technical_change"

    @property
    def is_governance_triggered(self) -> bool:
        """True for the four policy-driven triggers ILM adds to technical change."""
        return self != EvolutionTrigger.TARGET_TECHNICAL_CHANGE


class TraceabilityStage(str, Enum):
    """The chain a policy change must traverse to reach the integration."""

    POLICY_DECISION = "policy_decision"
    REQUIREMENT_SPEC_UPDATE = "requirement_spec_update"
    CAPABILITY_ENHANCEMENT = "capability_enhancement"
    CAPABILITY_MAP_REVISION = "capability_map_revision"


class TraceabilityStep(BaseModel):
    """One completed stage of the evolution chain."""

    stage: TraceabilityStage
    completed_at: datetime = Field(default_factory=utcnow)
    completed_by: str = ""
    reference: str = Field(default="", description="Change record, ticket, or commit reference")
    notes: str = ""


class CapabilityChange(BaseModel):
    """A capability the integration must gain or deepen to stay compliant."""

    operation: GovernanceOperation
    current_coverage: CoverageLevel
    required_coverage: CoverageLevel
    severity: Severity = Severity.HIGH
    rationale: str = ""


class EvolutionRequest(BaseModel):
    """A tracked evolution of one integration, from policy decision to revision.

    Usage:
        request = evaluate_evolution(
            integration_id="crm-prod",
            trigger=EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE,
            updated_requirements=new_spec,
            capability_map=current_map,
            description="Certification moves from annual to quarterly at permission level",
        )
        request.record_stage(TraceabilityStage.REQUIREMENT_SPEC_UPDATE, completed_by="gov.owner")
    """

    integration_id: str
    application_id: str = ""
    trigger: EvolutionTrigger
    description: str = ""
    raised_at: datetime = Field(default_factory=utcnow)
    raised_by: str = ""
    capability_changes: list[CapabilityChange] = Field(default_factory=list)
    trace: list[TraceabilityStep] = Field(default_factory=list)

    @property
    def requires_connector_work(self) -> bool:
        """True when policy now demands capability the integration does not have."""
        return bool(self.capability_changes)

    def record_stage(
        self,
        stage: TraceabilityStage,
        completed_by: str = "",
        reference: str = "",
        notes: str = "",
    ) -> TraceabilityStep:
        """Record completion of one stage of the traceability chain."""
        step = TraceabilityStep(
            stage=stage, completed_by=completed_by, reference=reference, notes=notes
        )
        self.trace = [s for s in self.trace if s.stage != stage]
        self.trace.append(step)
        return step

    def completed_stages(self) -> set[TraceabilityStage]:
        return {s.stage for s in self.trace}

    def required_stages(self) -> list[TraceabilityStage]:
        """Stages this evolution must traverse, in order.

        A technically triggered evolution has no originating policy decision,
        but it still owes a revised capability specification.
        """
        stages = list(TraceabilityStage)
        if not self.trigger.is_governance_triggered:
            stages.remove(TraceabilityStage.POLICY_DECISION)
        return stages

    def outstanding_stages(self) -> list[TraceabilityStage]:
        """Stages still owed, in order — the audit answer to "where did this land?"."""
        done = self.completed_stages()
        return [stage for stage in self.required_stages() if stage not in done]

    def is_closed(self) -> bool:
        """True once the policy change has reached a revised capability specification."""
        return not self.outstanding_stages()


def evaluate_evolution(
    integration_id: str,
    trigger: EvolutionTrigger,
    updated_requirements: IntegrationRequirementSpec,
    capability_map: ConnectorCapabilityMap | None = None,
    description: str = "",
    raised_by: str = "",
) -> EvolutionRequest:
    """Compare a revised governance baseline against declared capability.

    The result is the gap the policy change opened: the operations whose
    coverage now falls short, each carrying the requirement that mandates it.
    """
    changes: list[CapabilityChange] = []
    for requirement in updated_requirements.required_operations:
        current = (
            capability_map.coverage_of(requirement.operation)
            if capability_map
            else CoverageLevel.NONE
        )
        if current.satisfies(requirement.coverage):
            continue
        declaration = capability_map.get(requirement.operation) if capability_map else None
        controlled = bool(declaration and declaration.gap_control.strip())
        changes.append(
            CapabilityChange(
                operation=requirement.operation,
                current_coverage=current,
                required_coverage=requirement.coverage,
                severity=Severity.MEDIUM if controlled else Severity.HIGH,
                rationale=_change_rationale(requirement, trigger),
            )
        )

    request = EvolutionRequest(
        integration_id=integration_id,
        application_id=updated_requirements.application_id,
        trigger=trigger,
        description=description,
        raised_by=raised_by,
        capability_changes=changes,
    )
    if trigger.is_governance_triggered:
        request.record_stage(
            TraceabilityStage.POLICY_DECISION, completed_by=raised_by, notes=description
        )
    return request


def _change_rationale(requirement: RequiredOperation, trigger: EvolutionTrigger) -> str:
    sources = ", ".join(requirement.sources) or "governance policy"
    return f"{trigger.value.replace('_', ' ')} — now mandated by {sources}"
