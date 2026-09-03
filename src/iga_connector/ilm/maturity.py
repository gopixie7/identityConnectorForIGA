"""The ILM maturity model.

The article names the maturity model as the structured path "from reactive
integration management to adaptive, APM-integrated governance" and leaves its
levels for practitioners to define. The five levels here operationalize that
stated path: each level is scored from evidence already present in the
governance inventory and the application portfolio, so an organization's level
is measured rather than self-declared.

Practitioners seeking an entry point are advised to begin with governance blind
spot mapping and retroactive capability declaration — which is exactly what
Levels 1 and 2 measure.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field

from .antipatterns import AntiPattern, detect_anti_patterns
from .apm import ApplicationPortfolio
from .inventory import IntegrationGovernanceInventory
from .models import LifecyclePhase, Severity


class MaturityLevel(IntEnum):
    """Levels on the path from reactive to adaptive integration governance."""

    REACTIVE = 1
    DECLARED = 2
    MONITORED = 3
    GOVERNED = 4
    ADAPTIVE = 5

    @property
    def label(self) -> str:
        return {
            MaturityLevel.REACTIVE: "Reactive — integrations built on escalation, undeclared",
            MaturityLevel.DECLARED: "Declared — capability specifications registered and validated",
            MaturityLevel.MONITORED: "Monitored — health governed against compliance thresholds",
            MaturityLevel.GOVERNED: "Governed — policy-triggered evolution and governed retirement",
            MaturityLevel.ADAPTIVE: "Adaptive — APM-integrated, blind spots systematically closed",
        }[self]


class LevelCriterion(BaseModel):
    """One measurable criterion contributing to a maturity level."""

    level: MaturityLevel
    name: str
    met: bool = False
    detail: str = ""


class MaturityAssessment(BaseModel):
    """Measured maturity of an organization's integration governance."""

    level: MaturityLevel = MaturityLevel.REACTIVE
    criteria: list[LevelCriterion] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    def criteria_for(self, level: MaturityLevel) -> list[LevelCriterion]:
        return [c for c in self.criteria if c.level == level]

    def level_met(self, level: MaturityLevel) -> bool:
        criteria = self.criteria_for(level)
        return bool(criteria) and all(c.met for c in criteria)


def assess_maturity(
    inventory: IntegrationGovernanceInventory,
    portfolio: ApplicationPortfolio | None = None,
) -> MaturityAssessment:
    """Score integration governance maturity from inventory and portfolio evidence."""
    criteria: list[LevelCriterion] = []
    records = inventory.records
    # Criteria over active integrations are vacuously met when none are active:
    # an inventory of fully retired integrations is not evidence of immaturity.
    active = [r for r in records if r.is_active]
    findings = detect_anti_patterns(inventory, portfolio)

    # Level 1 — something is registered at all.
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.REACTIVE,
            name="Integrations are inventoried",
            met=bool(records),
            detail=f"{len(records)} integration(s) in the governance inventory.",
        )
    )

    # Level 2 — capability is declared and validated against a governance baseline.
    declared = [r for r in active if r.capability_map is not None]
    with_requirements = [r for r in active if r.requirements is not None]
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.DECLARED,
            name="Active integrations declare capability",
            met=len(declared) == len(active),
            detail=f"{len(declared)}/{len(active)} active integration(s) declare capability.",
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.DECLARED,
            name="Requirements derived before development",
            met=len(with_requirements) == len(active),
            detail=(
                f"{len(with_requirements)}/{len(active)} active integration(s) carry an "
                "integration requirement specification."
            ),
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.DECLARED,
            name="Named governance ownership",
            met=all(r.ownership is not None and r.ownership.is_separated() for r in active),
            detail="Governance owner is named and distinct from the technical maintainer.",
        )
    )

    # Level 3 — health is governed, not merely monitored.
    observed = [r for r in active if r.health_history]
    assessed = [r for r in active if r.last_assessment is not None]
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.MONITORED,
            name="Health indicators collected",
            met=len(observed) == len(active),
            detail=f"{len(observed)}/{len(active)} active integration(s) report health.",
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.MONITORED,
            name="Health assessed against governance thresholds",
            met=len(assessed) == len(active),
            detail=f"{len(assessed)}/{len(active)} active integration(s) have been assessed.",
        )
    )
    build_and_forget = [
        f for f in findings if f.anti_pattern == AntiPattern.BUILD_AND_FORGET
    ]
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.MONITORED,
            name="No build-and-forget integrations",
            met=not build_and_forget,
            detail=f"{len(build_and_forget)} build-and-forget finding(s).",
        )
    )

    # Level 4 — evolution and retirement are governance events.
    governance_evolutions = [
        r for r in records if any(e.trigger.is_governance_triggered for e in r.evolution_requests)
    ]
    retired = [r for r in records if r.phase == LifecyclePhase.RETIRED]
    governed_retirements = [
        r for r in retired if r.retirement is not None and r.retirement.disposition.authorized
    ]
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.GOVERNED,
            name="Policy change reaches integrations",
            met=bool(governance_evolutions),
            detail=(
                f"{len(governance_evolutions)} integration(s) have a governance-triggered "
                "evolution on record."
            ),
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.GOVERNED,
            name="Retirement is governed",
            met=len(governed_retirements) == len(retired),
            detail=f"{len(governed_retirements)}/{len(retired)} retirement(s) carry a disposition.",
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.GOVERNED,
            name="No blocking anti-patterns",
            met=not [f for f in findings if f.severity == Severity.BLOCKING],
            detail=(
                f"{len([f for f in findings if f.severity == Severity.BLOCKING])} blocking "
                "anti-pattern finding(s)."
            ),
        )
    )

    # Level 5 — APM-integrated, with blind spots systematically closed.
    disconnection = [f for f in findings if f.anti_pattern == AntiPattern.APM_IGA_DISCONNECTION]
    report = inventory.coverage_report(portfolio) if portfolio else None
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.ADAPTIVE,
            name="APM is the integration governance control plane",
            met=portfolio is not None and not disconnection,
            detail=f"{len(disconnection)} APM/IGA disconnection finding(s).",
        )
    )
    criteria.append(
        LevelCriterion(
            level=MaturityLevel.ADAPTIVE,
            name="No governance blind spots",
            met=report is not None and not report.blind_spots,
            detail=(
                f"{len(report.blind_spots)} blind spot(s); coverage "
                f"{report.coverage_rate:.0%}."
                if report
                else "No application portfolio available to map blind spots."
            ),
        )
    )

    level = MaturityLevel.REACTIVE
    assessment = MaturityAssessment(criteria=criteria)
    for candidate in MaturityLevel:
        if assessment.level_met(candidate):
            level = candidate
        else:
            break
    assessment.level = level
    horizon = MaturityLevel(min(int(level) + 1, int(MaturityLevel.ADAPTIVE)))
    assessment.next_actions = [
        f"{c.name}: {c.detail}" for c in criteria if not c.met and c.level <= horizon
    ]
    return assessment
