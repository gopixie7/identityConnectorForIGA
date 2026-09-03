"""The ILM pipeline — the five phases wired to the APM control plane.

This is the framework as one object. An APM lifecycle event enters at the top;
governance-driven discovery, strategy routing, capability validation, health
governance, evolution tracking, and governed retirement follow from it.

The alignment it implements is the article's central claim: integration
governance is triggered by application registration rather than by audit
findings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.connector import BaseConnector
from .apm import APMLifecycleEvent, ApplicationPortfolio, ApplicationRecord
from .capability import ConnectorCapabilityMap
from .charter import ConnectorGovernanceCharter
from .discovery import (
    GovernancePolicyProfile,
    IntegrationRequirementSpec,
    derive_requirements,
)
from .evolution import EvolutionRequest, EvolutionTrigger, evaluate_evolution
from .health import HealthAssessment, HealthObservation
from .inventory import CoverageReport, IntegrationGovernanceInventory, IntegrationRecord
from .maturity import MaturityAssessment, assess_maturity
from .models import GovernanceOwnership, IdentityPopulation, IntegrationPath, LifecyclePhase
from .retirement import GovernedRetirement
from .strategy import StrategyDecision, decide_integration_path


class PhaseOutcome(BaseModel):
    """What an APM lifecycle event caused the pipeline to do."""

    event_stage: str
    phase: LifecyclePhase | None = None
    integration_id: str | None = None
    actions: list[str] = Field(default_factory=list)
    requirements: IntegrationRequirementSpec | None = None
    strategy: StrategyDecision | None = None
    retirement: GovernedRetirement | None = None


class ILMPipeline:
    """Drives an integration through the five ILM phases.

    Usage:
        pipeline = ILMPipeline(charter=ConnectorGovernanceCharter())
        pipeline.portfolio.add(application)

        event = pipeline.portfolio.emit_transition("APP-014", APMLifecycleStage.PRODUCTION)
        outcome = pipeline.on_apm_event(event)          # phases 1 and 2 open

        pipeline.declare_capability("APP-014-integration", capability_map)
        pipeline.promote("APP-014-integration")          # validated at the gate
        pipeline.observe(observation)                    # phase 3
    """

    def __init__(
        self,
        charter: ConnectorGovernanceCharter | None = None,
        portfolio: ApplicationPortfolio | None = None,
        inventory: IntegrationGovernanceInventory | None = None,
    ) -> None:
        self.charter = charter or ConnectorGovernanceCharter()
        self.portfolio = portfolio or ApplicationPortfolio()
        self.inventory = inventory or IntegrationGovernanceInventory(charter=self.charter)
        self._policies: dict[str, GovernancePolicyProfile] = {}

    # --- policy -----------------------------------------------------------

    def set_policy(self, application_id: str, policy: GovernancePolicyProfile) -> None:
        """Record the IGA platform policy configuration for an application."""
        self._policies[application_id] = policy

    def policy_for(self, application_id: str) -> GovernancePolicyProfile:
        return self._policies.get(application_id, GovernancePolicyProfile())

    # --- phase 1 & 2 ------------------------------------------------------

    def discover(
        self,
        application: ApplicationRecord,
        integration_id: str | None = None,
        ownership: GovernanceOwnership | None = None,
        ootb_capability_gaps_acceptable: bool = True,
    ) -> IntegrationRecord:
        """Run governance-driven discovery and strategy routing for an application."""
        requirements = derive_requirements(
            application, policy=self.policy_for(application.application_id), charter=self.charter
        )
        strategy = decide_integration_path(
            application,
            requirements=requirements,
            ootb_capability_gaps_acceptable=ootb_capability_gaps_acceptable,
        )
        return self.inventory.register(
            integration_id or default_integration_id(application),
            requirements=requirements,
            strategy=strategy,
            ownership=ownership,
        )

    def declare_capability(
        self, integration_id: str, capability_map: ConnectorCapabilityMap
    ) -> IntegrationRecord:
        """Attach the Phase 2 capability specification to a registered integration."""
        return self.inventory.attach_capability_map(integration_id, capability_map)

    def declare_capability_from_connector(
        self,
        integration_id: str,
        connector: BaseConnector,
        ownership: GovernanceOwnership | None = None,
    ) -> IntegrationRecord:
        """Draft and attach a capability specification from a live connector.

        The mechanical half of retroactive capability declaration: coverage is
        derived from what the connector implements, and the governance owner
        still supplies scope, dependencies, and gap controls.
        """
        record = self.inventory.require(integration_id)
        capability_map = ConnectorCapabilityMap.from_connector(
            connector,
            integration_id=integration_id,
            application_id=record.application_id,
            path=record.path or IntegrationPath.CUSTOM_CONNECTOR,
            ownership=ownership or record.ownership,
        )
        return self.declare_capability(integration_id, capability_map)

    def promote(self, integration_id: str) -> IntegrationRecord:
        """Promote into production governance, enforcing the charter's gate."""
        return self.inventory.promote(integration_id)

    # --- phase 3 ----------------------------------------------------------

    def observe(self, observation: HealthObservation) -> HealthAssessment:
        """Record a health observation and assess it against governance thresholds."""
        return self.inventory.record_health(observation)

    # --- phase 4 ----------------------------------------------------------

    def evolve(
        self,
        integration_id: str,
        trigger: EvolutionTrigger,
        policy: GovernancePolicyProfile | None = None,
        application: ApplicationRecord | None = None,
        description: str = "",
        raised_by: str = "",
    ) -> EvolutionRequest:
        """Re-derive requirements after a change and record the resulting gap.

        Supplying the updated policy or application record is what makes this
        governance-triggered: the new baseline is derived from policy, then
        compared against what the integration actually declares.
        """
        record = self.inventory.require(integration_id)
        application = application or self.portfolio.get(record.application_id)
        if application is None:
            raise KeyError(
                f"Application '{record.application_id}' is not in the portfolio; "
                "evolution cannot be re-derived from policy."
            )
        if policy is not None:
            self.set_policy(application.application_id, policy)

        updated = derive_requirements(
            application, policy=self.policy_for(application.application_id), charter=self.charter
        )
        request = evaluate_evolution(
            integration_id=integration_id,
            trigger=trigger,
            updated_requirements=updated,
            capability_map=record.capability_map,
            description=description,
            raised_by=raised_by,
        )
        record.requirements = updated
        self.inventory.record_evolution(request)
        return request

    # --- phase 5 ----------------------------------------------------------

    def open_retirement(
        self, integration_id: str, trigger: str = "apm_sunset_event"
    ) -> GovernedRetirement:
        """Open the governed retirement window for an integration."""
        record = self.inventory.require(integration_id)
        application = self.portfolio.get(record.application_id)
        retirement = GovernedRetirement.open(
            integration_id=integration_id,
            application_id=record.application_id,
            regulatory_scope=(
                application.regulatory_scope
                if application
                else (record.requirements.regulatory_scope if record.requirements else [])
            ),
            identity_population=(
                application.identity_population
                if application
                else (
                    record.requirements.identity_population
                    if record.requirements
                    else IdentityPopulation.WORKFORCE
                )
            ),
            planned_decommission_date=(
                application.planned_decommission_date if application else None
            ),
            trigger=trigger,
            charter=self.charter,
        )
        self.inventory.open_retirement(retirement)
        return retirement

    def retire(self, integration_id: str, authorized_by: str, notes: str = "") -> IntegrationRecord:
        """Authorize disposition and retire the integration."""
        return self.inventory.retire(integration_id, authorized_by=authorized_by, notes=notes)

    # --- APM control plane ------------------------------------------------

    def on_apm_event(
        self, event: APMLifecycleEvent, ownership: GovernanceOwnership | None = None
    ) -> PhaseOutcome:
        """Route an APM lifecycle event into the phase it activates."""
        self.portfolio.apply(event)
        application = self.portfolio.get(event.application.application_id) or event.application
        phase = event.triggered_phase()
        outcome = PhaseOutcome(event_stage=event.new_stage.value, phase=phase)

        if phase is None:
            outcome.actions.append(
                f"No integration governance obligation for transition to "
                f"{event.new_stage.value}."
            )
            return outcome

        existing = self.inventory.for_application(application.application_id)

        if phase in (LifecyclePhase.DISCOVERY, LifecyclePhase.DEVELOPMENT):
            if existing:
                record = existing[0]
                outcome.integration_id = record.integration_id
                outcome.requirements = record.requirements
                outcome.strategy = record.strategy
                outcome.actions.append(
                    f"Integration '{record.integration_id}' is already registered in phase "
                    f"{record.phase.value}."
                )
                return outcome
            record = self.discover(application, ownership=ownership)
            outcome.integration_id = record.integration_id
            outcome.requirements = record.requirements
            outcome.strategy = record.strategy
            outcome.actions.append(
                "Governance-driven discovery derived the integration requirement specification."
            )
            if record.strategy is not None:
                outcome.actions.append(
                    f"Strategy routed the application to {record.strategy.path.value}: "
                    f"{record.strategy.capability_obligation}"
                )
            return outcome

        if phase == LifecyclePhase.OPERATION:
            if not existing:
                record = self.discover(application, ownership=ownership)
                outcome.integration_id = record.integration_id
                outcome.actions.append(
                    "Application reached production with no registered integration; discovery "
                    "opened retroactively."
                )
                return outcome
            record = existing[0]
            outcome.integration_id = record.integration_id
            validation = self.inventory.validate_capability(record.integration_id)
            if validation.promotable():
                self.inventory.promote(record.integration_id)
                outcome.actions.append("Promoted into production governance.")
            else:
                outcome.actions.extend(
                    f"Promotion blocked: {f.message}" for f in validation.blocking_findings
                )
            return outcome

        if phase == LifecyclePhase.RETIREMENT:
            if not existing:
                outcome.actions.append(
                    "Application is retiring with no registered integration; nothing to retire, "
                    "but confirm no ungoverned coverage exists."
                )
                return outcome
            record = existing[0]
            outcome.integration_id = record.integration_id
            if record.retirement is not None:
                outcome.retirement = record.retirement
                outcome.actions.append("Governed retirement is already open.")
                return outcome
            retirement = self.open_retirement(
                record.integration_id, trigger=f"apm_{event.new_stage.value}_event"
            )
            outcome.retirement = retirement
            outcome.actions.append(
                f"Opened governed retirement with {len(retirement.items)} obligation(s)."
            )
            return outcome

        return outcome

    # --- reporting --------------------------------------------------------

    def coverage_report(self) -> CoverageReport:
        """Portfolio-level governance coverage, including blind spots."""
        return self.inventory.coverage_report(self.portfolio)

    def maturity(self) -> MaturityAssessment:
        """Measured integration governance maturity."""
        return assess_maturity(self.inventory, self.portfolio)


def default_integration_id(application: ApplicationRecord) -> str:
    """Derive a stable integration id from an application record."""
    return f"{application.application_id.lower()}-integration"
