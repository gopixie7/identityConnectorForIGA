"""The Application Governance Control Plane.

ILM positions Application Portfolio Management as the authoritative source of
application lifecycle events. An application moving to production in the APM
emits an event that activates IGA onboarding; an application moving to sunset
emits the event that opens the governed retirement window. Integration
governance is therefore triggered by application registration rather than by
audit findings.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from .models import (
    DataSensitivity,
    IdentityPopulation,
    LifecyclePhase,
    RegulatoryFramework,
    RiskClassification,
    utcnow,
)


class APMLifecycleStage(str, Enum):
    """Application lifecycle stages recorded in the APM system."""

    PLANNED = "planned"
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"
    SUNSET = "sunset"
    DECOMMISSIONED = "decommissioned"


class AuthorizationModel(str, Enum):
    """How the application decides what an authenticated principal may do.

    This is the discriminating input of the connector strategy decision matrix:
    an application whose authorization is entirely carried by enterprise
    directory groups needs no connector of its own.
    """

    DIRECTORY_GROUPS = "directory_groups"
    LOCAL_USER_STORE = "local_user_store"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class ApplicationRecord(BaseModel):
    """An application as catalogued by the APM system.

    The fields ILM depends on — risk, sensitivity, regulatory scope, ownership,
    stage, and integration capability — are exactly the APM metadata whose
    quality practitioners are advised to audit before adopting the framework.
    """

    application_id: str = Field(description="Authoritative APM identifier")
    name: str = ""
    stage: APMLifecycleStage = APMLifecycleStage.PLANNED
    risk_classification: RiskClassification = RiskClassification.MODERATE
    data_sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    regulatory_scope: list[RegulatoryFramework] = Field(default_factory=list)
    identity_population: IdentityPopulation = IdentityPopulation.WORKFORCE
    application_owner: str = ""
    hosting_model: str = Field(default="", description="e.g. on-premises, saas, cloud-native")

    authorization_model: AuthorizationModel = AuthorizationModel.UNKNOWN
    has_local_user_store: bool = True
    has_api_or_sdk: bool = False
    ootb_connector_available: bool = False
    vendor_restriction: bool = Field(
        default=False, description="Vendor contractually or technically forbids integration"
    )
    integration_cost_prohibitive: bool = False

    planned_decommission_date: date | None = None
    in_governance_scope: bool = Field(
        default=True, description="Policy places this application under IGA governance"
    )

    def is_governed_stage(self) -> bool:
        """True while the application is live enough to require governance coverage."""
        return self.stage == APMLifecycleStage.PRODUCTION

    def requires_integration(self) -> bool:
        """True when policy demands active governance coverage for this application."""
        return self.in_governance_scope and self.is_governed_stage()


class APMLifecycleEvent(BaseModel):
    """A stage transition emitted by the APM system."""

    application: ApplicationRecord
    previous_stage: APMLifecycleStage | None = None
    new_stage: APMLifecycleStage
    occurred_at: datetime = Field(default_factory=utcnow)
    source: str = Field(default="apm", description="Emitting system")

    def triggered_phase(self) -> LifecyclePhase | None:
        """The ILM phase this application lifecycle event activates.

        Returns None for transitions that carry no integration governance
        obligation (for example planned -> development).
        """
        if self.new_stage in (APMLifecycleStage.PLANNED, APMLifecycleStage.DEVELOPMENT):
            return None
        if self.new_stage == APMLifecycleStage.TESTING:
            return LifecyclePhase.DISCOVERY
        if self.new_stage == APMLifecycleStage.PRODUCTION:
            # Reaching production without prior discovery starts the pipeline;
            # otherwise the integration is promoted into operational governance.
            if self.previous_stage in (None, APMLifecycleStage.TESTING):
                return LifecyclePhase.DEVELOPMENT
            return LifecyclePhase.OPERATION
        if self.new_stage in (APMLifecycleStage.SUNSET, APMLifecycleStage.DECOMMISSIONED):
            return LifecyclePhase.RETIREMENT
        return None


class ApplicationPortfolio(BaseModel):
    """A read model over the APM catalog.

    ILM consumes the portfolio to derive discovery inputs and — by comparing it
    against the governance inventory — to map governance blind spots.
    """

    applications: list[ApplicationRecord] = Field(default_factory=list)
    last_synced_at: datetime | None = Field(
        default=None, description="When APM metadata was last exchanged with the IGA platform"
    )

    def get(self, application_id: str) -> ApplicationRecord | None:
        return next((a for a in self.applications if a.application_id == application_id), None)

    def add(self, application: ApplicationRecord) -> ApplicationRecord:
        """Insert or replace an application record, keyed by application_id."""
        self.applications = [
            a for a in self.applications if a.application_id != application.application_id
        ]
        self.applications.append(application)
        return application

    def in_scope(self) -> list[ApplicationRecord]:
        """Applications that policy requires an active integration to cover."""
        return [a for a in self.applications if a.requires_integration()]

    def apply(self, event: APMLifecycleEvent) -> ApplicationRecord:
        """Record a lifecycle event against the portfolio and return the new record."""
        record = event.application.model_copy(update={"stage": event.new_stage})
        return self.add(record)

    def emit_transition(
        self, application_id: str, new_stage: APMLifecycleStage
    ) -> APMLifecycleEvent:
        """Build the lifecycle event for a stage transition and apply it.

        Raises KeyError when the application is not in the portfolio — an
        unknown application is an APM data quality problem, not an ILM one.
        """
        current = self.get(application_id)
        if current is None:
            raise KeyError(f"Application '{application_id}' is not in the portfolio")
        event = APMLifecycleEvent(
            application=current, previous_stage=current.stage, new_stage=new_stage
        )
        self.apply(event)
        return event
