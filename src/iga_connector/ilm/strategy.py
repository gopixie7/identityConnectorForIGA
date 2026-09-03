"""Phase 2a — The connector strategy decision matrix.

Before anything is built, each application is routed to one of the framework's
integration paths based on its technical characteristics and its governance
requirements. Every path — including the paths where no connector is written —
carries a capability specification obligation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .apm import ApplicationRecord, AuthorizationModel
from .discovery import IntegrationRequirementSpec
from .models import FulfillmentChannel, IntegrationPath, Severity


class StrategyDecision(BaseModel):
    """The routing decision for one application, with its rationale."""

    application_id: str
    path: IntegrationPath
    fulfillment_channel: FulfillmentChannel
    mechanism: str = Field(description="How governance coverage is actually delivered")
    capability_obligation: str = Field(description="What the capability specification must record")
    rationale: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def requires_dedicated_connector(self) -> bool:
        return self.path in (IntegrationPath.OOTB_CONNECTOR, IntegrationPath.CUSTOM_CONNECTOR)


def decide_integration_path(
    application: ApplicationRecord,
    requirements: IntegrationRequirementSpec | None = None,
    ootb_capability_gaps_acceptable: bool = True,
) -> StrategyDecision:
    """Route an application to its integration path (Table 4 of the framework).

    `ootb_capability_gaps_acceptable` expresses the governance judgment that
    Phase 1's requirement specification cannot make on its own: whether the
    known gaps in a vendor connector are tolerable with compensating controls,
    or whether they create unacceptable governance risk.
    """
    rationale: list[str] = []
    warnings: list[str] = []

    directory_only = (
        application.authorization_model == AuthorizationModel.DIRECTORY_GROUPS
        and not application.has_local_user_store
    )
    if directory_only:
        rationale.append(
            "Authorization is carried exclusively by enterprise directory group membership."
        )
        if requirements is not None and requirements.entitlement_granularity.value == "permission":
            warnings.append(
                "Permission-level certification is required: verify no permission tier falls "
                "outside directory-managed groups before accepting auto-compliance."
            )
        return StrategyDecision(
            application_id=application.application_id,
            path=IntegrationPath.AUTO_COMPLIANT,
            fulfillment_channel=FulfillmentChannel.AUTOMATED_CONNECTOR,
            mechanism=(
                "No dedicated connector. The existing directory connector provides coverage "
                "through group aggregation, provisioning, and deprovisioning."
            ),
            capability_obligation=(
                "Complete the capability specification against the directory connector and "
                "verify that no governance scope falls outside LDAP group coverage."
            ),
            rationale=rationale,
            warnings=warnings,
        )

    if application.authorization_model == AuthorizationModel.HYBRID:
        warnings.append(
            "Hybrid authorization: directory groups cover part of the entitlement model, so "
            "a dedicated integration is still required for the local permission tier."
        )

    programmatic = (
        application.has_api_or_sdk
        and not application.vendor_restriction
        and not application.integration_cost_prohibitive
    )
    if not programmatic:
        reasons = []
        if not application.has_api_or_sdk:
            reasons.append("no API or SDK is available")
        if application.vendor_restriction:
            reasons.append("vendor restriction prohibits programmatic integration")
        if application.integration_cost_prohibitive:
            reasons.append("integration is cost-prohibitive")
        rationale.append("Programmatic connectivity is not feasible: " + "; ".join(reasons) + ".")
        return StrategyDecision(
            application_id=application.application_id,
            path=IntegrationPath.DISCONNECTED_ITSM,
            fulfillment_channel=FulfillmentChannel.ITSM_MANUAL,
            mechanism=(
                "ITSM disconnected integration pattern. IGA manages the governance lifecycle; "
                "an ITSM ticket workflow fulfils provisioning and deprovisioning through a "
                "human operator."
            ),
            capability_obligation=(
                "Record ITSM as the fulfillment channel and declare the SLA between governance "
                "decision and confirmed fulfillment as the primary health indicator."
            ),
            rationale=rationale,
            warnings=warnings,
        )

    rationale.append("API or SDK is available, so programmatic governance coverage is feasible.")
    if application.ootb_connector_available and ootb_capability_gaps_acceptable:
        rationale.append(
            "A vendor out-of-the-box connector exists and its capability gaps are acceptable "
            "with documented compensating controls."
        )
        return StrategyDecision(
            application_id=application.application_id,
            path=IntegrationPath.OOTB_CONNECTOR,
            fulfillment_channel=FulfillmentChannel.AUTOMATED_CONNECTOR,
            mechanism="Deploy the IGA vendor-provided out-of-the-box connector.",
            capability_obligation=(
                "Document all OOTB operations supported and any gaps; validate capability "
                "coverage against the integration requirement specification before promotion. "
                "Known gaps require documented compensating controls."
            ),
            rationale=rationale,
            warnings=warnings,
        )

    if application.ootb_connector_available:
        rationale.append(
            "An OOTB connector exists but its capability gaps create unacceptable governance "
            "risk against the integration requirement specification."
        )
    else:
        rationale.append("No OOTB connector exists for this target application.")

    return StrategyDecision(
        application_id=application.application_id,
        path=IntegrationPath.CUSTOM_CONNECTOR,
        fulfillment_channel=FulfillmentChannel.AUTOMATED_CONNECTOR,
        mechanism=(
            "Build a custom connector against the application's REST API or vendor SDK, "
            "applying a low-code / metadata-driven methodology."
        ),
        capability_obligation=(
            "Two deliverables are required: a functioning connector and a capability "
            "specification declaring the full operation set implemented, with remaining gaps "
            "and their compensating controls. Register in the governance inventory before "
            "production."
        ),
        rationale=rationale,
        warnings=warnings,
    )


def strategy_severity(decision: StrategyDecision) -> Severity:
    """Governance attention a routing decision warrants once it is recorded."""
    if decision.warnings:
        return Severity.HIGH
    if decision.path == IntegrationPath.DISCONNECTED_ITSM:
        return Severity.MEDIUM
    return Severity.INFO
