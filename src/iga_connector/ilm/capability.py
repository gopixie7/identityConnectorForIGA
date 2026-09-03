"""Phase 2b — Connector capability specifications.

Connector development produces two deliverables: a functioning connector, and
a formal declaration of which lifecycle operations it supports, at what
coverage level, with what governance dependencies, and with what compensating
controls for its gaps.

The capability specification is the governance contract between an integration
and the IGA platform's policy and certification functions. It is required for
every integration path — auto-compliant, disconnected, OOTB, or custom-built —
and must be validated against Phase 1's requirement specification before the
application is promoted to production governance.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..core.connector import BaseConnector
from ..core.operations import Operation
from .discovery import EntitlementGranularity, IntegrationRequirementSpec
from .models import (
    CoverageLevel,
    Finding,
    FulfillmentChannel,
    GovernanceOperation,
    GovernanceOwnership,
    IntegrationPath,
    Severity,
    utcnow,
)

OP = GovernanceOperation

#: Technical SDK operations that implement each governance operation. An entry
#: maps a governance operation to the groups of SDK operations that satisfy it;
#: a group is satisfied when *any* of its members is supported, and the
#: governance operation is fully covered when *every* group is satisfied.
OPERATION_MAPPING: dict[GovernanceOperation, list[list[Operation]]] = {
    OP.IDENTITY_AGGREGATION: [[Operation.LIST_ACCOUNTS, Operation.FULL_RECONCILIATION]],
    OP.ACCOUNT_PROVISIONING: [[Operation.CREATE_ACCOUNT]],
    OP.ACCOUNT_DEPROVISIONING: [[Operation.DELETE_ACCOUNT, Operation.DISABLE_ACCOUNT]],
    OP.ENTITLEMENT_ENUMERATION: [[Operation.LIST_ENTITLEMENTS]],
    OP.ENTITLEMENT_ASSIGNMENT: [[Operation.GRANT_ENTITLEMENT]],
    OP.ENTITLEMENT_REVOCATION: [[Operation.REVOKE_ENTITLEMENT]],
    OP.CERTIFICATION_FEED: [
        [Operation.LIST_ACCOUNTS, Operation.FULL_RECONCILIATION],
        [Operation.LIST_ENTITLEMENTS],
    ],
    OP.PASSWORD_MANAGEMENT: [[Operation.SET_PASSWORD, Operation.RESET_PASSWORD]],
    # No SDK operation implements these; they are declared by hand or covered
    # by a compensating control such as a secrets manager integration.
    OP.NHI_CREDENTIAL_ROTATION: [],
    OP.RISK_SIGNAL_SHARING: [],
    OP.SESSION_TERMINATION: [],
}


class CapabilityDeclaration(BaseModel):
    """One row of the connector capability specification.

    Mirrors the framework's template: the operation, whether it is supported,
    the coverage scope, the governance functions that depend on it, and the
    compensating control that covers any gap.
    """

    operation: GovernanceOperation
    supported: CoverageLevel = CoverageLevel.NONE
    coverage_scope: str = Field(default="", description="What the coverage does and does not span")
    governance_dependencies: list[str] = Field(
        default_factory=list,
        description="IGA functions that depend on this operation, e.g. certification campaigns",
    )
    gap_control: str = Field(
        default="", description="Compensating control where coverage is partial or absent"
    )
    notes: str = ""

    @property
    def is_gap(self) -> bool:
        return self.supported != CoverageLevel.FULL

    @property
    def is_uncontrolled_gap(self) -> bool:
        """A gap with no documented compensating control is an undeclared exposure."""
        return self.is_gap and not self.gap_control.strip()


class CapabilityValidation(BaseModel):
    """Result of validating a capability specification against Phase 1."""

    application_id: str = ""
    compliant: bool = True
    findings: list[Finding] = Field(default_factory=list)

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKING]

    def promotable(self) -> bool:
        """True when nothing blocks promotion to production governance."""
        return not self.blocking_findings


class ConnectorCapabilityMap(BaseModel):
    """The formal capability declaration for one integration.

    Usage:
        capability_map = ConnectorCapabilityMap(
            integration_id="crm-prod",
            application_id="APP-014",
            path=IntegrationPath.CUSTOM_CONNECTOR,
            ownership=GovernanceOwnership(
                governance_owner="identity.governance@example.com",
                technical_maintainer="iam.engineering@example.com",
            ),
        )
        capability_map.declare(
            GovernanceOperation.IDENTITY_AGGREGATION,
            CoverageLevel.FULL,
            coverage_scope="All account types",
            governance_dependencies=["Certification campaigns", "SoD evaluation"],
        )
        validation = capability_map.validate_against(requirements)
    """

    integration_id: str
    application_id: str
    connector_name: str = ""
    connector_version: str = "1.0.0"
    path: IntegrationPath = IntegrationPath.CUSTOM_CONNECTOR
    fulfillment_channel: FulfillmentChannel = FulfillmentChannel.AUTOMATED_CONNECTOR
    ownership: GovernanceOwnership | None = None
    declarations: list[CapabilityDeclaration] = Field(default_factory=list)
    fulfillment_sla_hours: float | None = Field(
        default=None,
        description="Primary health indicator for ITSM-fulfilled (disconnected) integrations",
    )
    declared_at: datetime = Field(default_factory=utcnow)
    declared_by: str = ""
    revision: int = Field(default=1, ge=1)

    # --- declaration ------------------------------------------------------

    def declare(
        self,
        operation: GovernanceOperation,
        supported: CoverageLevel,
        coverage_scope: str = "",
        governance_dependencies: list[str] | None = None,
        gap_control: str = "",
        notes: str = "",
    ) -> CapabilityDeclaration:
        """Declare (or redeclare) one operation's coverage."""
        declaration = CapabilityDeclaration(
            operation=operation,
            supported=supported,
            coverage_scope=coverage_scope,
            governance_dependencies=governance_dependencies or [],
            gap_control=gap_control,
            notes=notes,
        )
        self.declarations = [d for d in self.declarations if d.operation != operation]
        self.declarations.append(declaration)
        return declaration

    def get(self, operation: GovernanceOperation) -> CapabilityDeclaration | None:
        return next((d for d in self.declarations if d.operation == operation), None)

    def coverage_of(self, operation: GovernanceOperation) -> CoverageLevel:
        declaration = self.get(operation)
        return declaration.supported if declaration else CoverageLevel.NONE

    def gaps(self) -> list[CapabilityDeclaration]:
        return [d for d in self.declarations if d.is_gap]

    def uncontrolled_gaps(self) -> list[CapabilityDeclaration]:
        return [d for d in self.declarations if d.is_uncontrolled_gap]

    # --- validation -------------------------------------------------------

    def validate_against(
        self,
        requirements: IntegrationRequirementSpec,
        allow_partial_with_gap_control: bool = True,
        require_separated_ownership: bool = True,
    ) -> CapabilityValidation:
        """Validate declared capability against the governance baseline.

        A required operation that is neither covered nor compensated is a
        blocking finding: the integration must not be promoted to production
        governance while it exists.
        """
        findings: list[Finding] = []

        for requirement in requirements.required_operations:
            declaration = self.get(requirement.operation)
            if declaration is None:
                findings.append(
                    Finding(
                        code="capability.undeclared",
                        severity=Severity.BLOCKING,
                        operation=requirement.operation,
                        message=(
                            f"Required operation '{requirement.operation.value}' is not declared "
                            f"in the capability specification ({', '.join(requirement.sources)})."
                        ),
                        remediation=(
                            "Declare the operation's coverage, or record a compensating control "
                            "if the integration cannot support it."
                        ),
                    )
                )
                continue

            if declaration.supported.satisfies(requirement.coverage):
                continue

            controlled = bool(declaration.gap_control.strip()) and allow_partial_with_gap_control
            findings.append(
                Finding(
                    code="capability.gap_controlled" if controlled else "capability.gap",
                    severity=Severity.MEDIUM if controlled else Severity.BLOCKING,
                    operation=requirement.operation,
                    message=(
                        f"'{requirement.operation.value}' is declared "
                        f"{declaration.supported.value} but policy requires "
                        f"{requirement.coverage.value}"
                        + (
                            f"; compensating control: {declaration.gap_control}."
                            if controlled
                            else "."
                        )
                    ),
                    remediation=(
                        "Track the compensating control as a governance dependency and "
                        "re-evaluate at the next certification cycle."
                        if controlled
                        else "Extend the connector, or document a compensating control that "
                        "closes the governance obligation."
                    ),
                )
            )

        if (
            requirements.entitlement_granularity == EntitlementGranularity.PERMISSION
            and self.coverage_of(OP.ENTITLEMENT_ENUMERATION) != CoverageLevel.FULL
        ):
            findings.append(
                Finding(
                    code="capability.granularity",
                    severity=Severity.HIGH,
                    operation=OP.ENTITLEMENT_ENUMERATION,
                    message=(
                        "Permission-level certification is required but entitlement enumeration "
                        "is not fully covered; fine-grained permissions become a certification "
                        "blind spot."
                    ),
                    remediation="Extend enumeration to permissions or supplement manually.",
                )
            )

        for declaration in self.uncontrolled_gaps():
            if requirements.requires(declaration.operation):
                continue  # already reported above with its policy driver
            findings.append(
                Finding(
                    code="capability.uncontrolled_gap",
                    severity=Severity.LOW,
                    operation=declaration.operation,
                    message=(
                        f"'{declaration.operation.value}' is declared "
                        f"{declaration.supported.value} with no compensating control."
                    ),
                    remediation="Document a compensating control or record an accepted risk.",
                )
            )

        if self.ownership is None:
            findings.append(
                Finding(
                    code="ownership.missing",
                    severity=Severity.BLOCKING,
                    message="No named governance owner or technical maintainer is recorded.",
                    remediation="Name both parties before production promotion.",
                )
            )
        elif require_separated_ownership and not self.ownership.is_separated():
            findings.append(
                Finding(
                    code="ownership.not_separated",
                    severity=Severity.HIGH,
                    message=(
                        "Governance ownership is not separated from technical maintenance; "
                        "health degradation will be escalated as a technical support issue."
                    ),
                    remediation="Name a governance owner distinct from the technical maintainer.",
                )
            )

        if (
            self.path == IntegrationPath.DISCONNECTED_ITSM
            and self.fulfillment_sla_hours is None
        ):
            findings.append(
                Finding(
                    code="fulfillment.sla_missing",
                    severity=Severity.BLOCKING,
                    message=(
                        "Disconnected (ITSM) integrations must declare the fulfillment SLA: it "
                        "is their primary health indicator."
                    ),
                    remediation="Record the maximum time from governance decision to "
                    "confirmed fulfillment.",
                )
            )

        return CapabilityValidation(
            application_id=requirements.application_id,
            compliant=not findings,
            findings=findings,
        )

    # --- derivation from a live connector ---------------------------------

    @classmethod
    def from_connector(
        cls,
        connector: BaseConnector,
        integration_id: str,
        application_id: str,
        path: IntegrationPath = IntegrationPath.CUSTOM_CONNECTOR,
        ownership: GovernanceOwnership | None = None,
    ) -> ConnectorCapabilityMap:
        """Draft a capability specification from a connector's declared operations.

        This is the mechanical half of retroactive capability declaration: it
        derives coverage from what the connector implements. Coverage scope,
        governance dependencies, and gap controls are governance judgments and
        must still be filled in by the governance owner.
        """
        schema = connector.get_schema()
        supported = {op.value for op in connector.supported_operations()}

        capability_map = cls(
            integration_id=integration_id,
            application_id=application_id,
            connector_name=schema.connector_name,
            connector_version=schema.version,
            path=path,
            ownership=ownership,
            declared_by="derived:from_connector",
        )
        for operation, groups in OPERATION_MAPPING.items():
            capability_map.declare(
                operation,
                _derive_coverage(groups, supported),
                notes="Derived from connector schema; confirm scope and dependencies.",
            )
        return capability_map


def _derive_coverage(groups: list[list[Operation]], supported: set[str]) -> CoverageLevel:
    """Coverage implied by the technical operations a connector supports."""
    if not groups:
        return CoverageLevel.NONE
    satisfied = [any(op.value in supported for op in group) for group in groups]
    if all(satisfied):
        return CoverageLevel.FULL
    if any(satisfied):
        return CoverageLevel.PARTIAL
    return CoverageLevel.NONE
