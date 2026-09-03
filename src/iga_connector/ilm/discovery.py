"""Phase 1 — Governance-driven discovery.

The first question ILM asks is not "what connectors exist?" or "what
connectors can we build?" but "what governance obligations must this
integration fulfil?". Requirements are derived from the governance policy that
applies to an application, before any development or procurement decision.

The output is an `IntegrationRequirementSpec`: the governance baseline against
which a connector's capability specifications are later validated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .apm import ApplicationRecord
from .charter import ConnectorGovernanceCharter, HealthThresholds
from .models import (
    CoverageLevel,
    GovernanceOperation,
    IdentityPopulation,
    RegulatoryFramework,
    RiskClassification,
    utcnow,
)


class CertificationCadence(str, Enum):
    """How often entitlements must be attested for this application."""

    CONTINUOUS = "continuous"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    NONE = "none"


class EntitlementGranularity(str, Enum):
    """Depth at which entitlements must be enumerated for certification."""

    ROLE = "role"
    PERMISSION = "permission"


class GovernancePolicyProfile(BaseModel):
    """IGA platform policy configuration for a single application.

    This is the second discovery input: joiner/mover/leaver rules, the
    certification cadence, the SoD ruleset scope, and the access request
    workflow that the connector will have to serve.
    """

    joiner_workflow_enabled: bool = True
    mover_workflow_enabled: bool = True
    leaver_workflow_enabled: bool = True
    access_request_enabled: bool = True
    certification_cadence: CertificationCadence = CertificationCadence.ANNUAL
    entitlement_granularity: EntitlementGranularity = EntitlementGranularity.ROLE
    sod_ruleset_in_scope: bool = False
    password_management_in_scope: bool = False
    max_deprovisioning_latency_hours: float | None = Field(
        default=None, description="Policy override of the charter's risk-derived latency budget"
    )


class RequiredOperation(BaseModel):
    """A governance operation the integration must support, and why."""

    operation: GovernanceOperation
    coverage: CoverageLevel = CoverageLevel.FULL
    rationale: str = ""
    sources: list[str] = Field(
        default_factory=list, description="Policy or regulatory drivers that mandate it"
    )


class IntegrationRequirementSpec(BaseModel):
    """Governance-derived contract produced by Phase 1.

    Declares what operations the connector must support, what data it must
    provide, and what compliance obligations it must enable — before any
    development decision is made.
    """

    application_id: str
    application_name: str = ""
    identity_population: IdentityPopulation = IdentityPopulation.WORKFORCE
    risk_classification: RiskClassification = RiskClassification.MODERATE
    regulatory_scope: list[RegulatoryFramework] = Field(default_factory=list)
    required_operations: list[RequiredOperation] = Field(default_factory=list)
    entitlement_granularity: EntitlementGranularity = EntitlementGranularity.ROLE
    certification_cadence: CertificationCadence = CertificationCadence.ANNUAL
    health_thresholds: HealthThresholds = Field(default_factory=HealthThresholds)
    priority: int = Field(default=3, ge=1, le=4, description="1 is the most urgent")
    charter_version: str = ""
    derived_at: datetime = Field(default_factory=utcnow)
    notes: list[str] = Field(default_factory=list)

    def operations(self) -> list[GovernanceOperation]:
        return [r.operation for r in self.required_operations]

    def requirement_for(self, operation: GovernanceOperation) -> RequiredOperation | None:
        return next((r for r in self.required_operations if r.operation == operation), None)

    def requires(self, operation: GovernanceOperation) -> bool:
        return self.requirement_for(operation) is not None


_PRIORITY_BY_RISK: dict[RiskClassification, int] = {
    RiskClassification.CRITICAL: 1,
    RiskClassification.HIGH: 2,
    RiskClassification.MODERATE: 3,
    RiskClassification.LOW: 4,
}


def derive_requirements(
    application: ApplicationRecord,
    policy: GovernancePolicyProfile | None = None,
    charter: ConnectorGovernanceCharter | None = None,
) -> IntegrationRequirementSpec:
    """Derive the integration requirement specification for an application.

    Inputs are those the article names for governance-driven discovery: the
    APM risk classification and data sensitivity, the regulatory scope, and the
    IGA platform policy configuration. Existing connector coverage is handled
    separately, by blind-spot mapping over the governance inventory.
    """
    policy = policy or GovernancePolicyProfile()
    charter = charter or ConnectorGovernanceCharter()

    required: dict[GovernanceOperation, RequiredOperation] = {}

    def demand(op: GovernanceOperation, rationale: str, source: str) -> None:
        existing = required.get(op)
        if existing is None:
            required[op] = RequiredOperation(
                operation=op, coverage=charter.required_coverage(op), rationale=rationale,
                sources=[source],
            )
        elif source not in existing.sources:
            existing.sources.append(source)

    for op in charter.mandatory_operations(
        frameworks=application.regulatory_scope, population=application.identity_population
    ):
        drivers = [
            f.value.upper()
            for f in application.regulatory_scope
            if op in charter.regulatory_operations.get(f, [])
        ]
        source = ", ".join(drivers) if drivers else application.identity_population.value
        demand(op, "Mandated by the governance charter for this application", source)

    if policy.joiner_workflow_enabled or policy.access_request_enabled:
        demand(
            GovernanceOperation.ACCOUNT_PROVISIONING,
            "Joiner workflow and access requests must be fulfilled at the target",
            "iga_policy:joiner",
        )
    if policy.leaver_workflow_enabled:
        demand(
            GovernanceOperation.ACCOUNT_DEPROVISIONING,
            "Leaver workflow must reach confirmed disable or delete at the target",
            "iga_policy:leaver",
        )
    if policy.mover_workflow_enabled:
        demand(
            GovernanceOperation.ENTITLEMENT_REVOCATION,
            "Mover workflow must revoke access that a role change no longer justifies",
            "iga_policy:mover",
        )
    if policy.access_request_enabled:
        demand(
            GovernanceOperation.ENTITLEMENT_ASSIGNMENT,
            "Approved access requests must be fulfilled at the target",
            "iga_policy:access_request",
        )
    if policy.certification_cadence != CertificationCadence.NONE:
        demand(
            GovernanceOperation.CERTIFICATION_FEED,
            f"{policy.certification_cadence.value} certification campaigns consume this feed",
            "iga_policy:certification",
        )
        demand(
            GovernanceOperation.ENTITLEMENT_ENUMERATION,
            "Certification requires the entitlement set to be enumerable",
            "iga_policy:certification",
        )
        demand(
            GovernanceOperation.IDENTITY_AGGREGATION,
            "Certification campaigns attest aggregated account data",
            "iga_policy:certification",
        )
    if policy.sod_ruleset_in_scope and charter.sod_requires_entitlement_enumeration:
        demand(
            GovernanceOperation.ENTITLEMENT_ENUMERATION,
            "SoD evaluation requires every conflicting entitlement to be enumerated",
            "iga_policy:sod",
        )
    if policy.password_management_in_scope:
        demand(
            GovernanceOperation.PASSWORD_MANAGEMENT,
            "Credential policy is enforced through the integration",
            "iga_policy:password",
        )

    thresholds = charter.thresholds_for(application.risk_classification)
    if policy.max_deprovisioning_latency_hours is not None:
        thresholds = thresholds.model_copy(
            update={"max_deprovisioning_latency_hours": policy.max_deprovisioning_latency_hours}
        )

    notes: list[str] = []
    if not application.regulatory_scope:
        notes.append(
            "No regulatory framework in scope; requirements derive from IGA policy only."
        )
    if policy.entitlement_granularity == EntitlementGranularity.PERMISSION:
        notes.append(
            "Permission-level certification: role-only enumeration is a governance gap, "
            "not an acceptable partial coverage."
        )

    return IntegrationRequirementSpec(
        application_id=application.application_id,
        application_name=application.name,
        identity_population=application.identity_population,
        risk_classification=application.risk_classification,
        regulatory_scope=list(application.regulatory_scope),
        required_operations=list(required.values()),
        entitlement_granularity=policy.entitlement_granularity,
        certification_cadence=policy.certification_cadence,
        health_thresholds=thresholds,
        priority=_PRIORITY_BY_RISK.get(application.risk_classification, 3),
        charter_version=charter.version,
        notes=notes,
    )
