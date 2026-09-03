"""Core vocabulary of the Integration Lifecycle Management (ILM) framework.

The terms modelled here follow the ILM article's terminology table: an IGA
connector is treated as a policy-bound organizational asset that moves through
a governed sequence of lifecycle phases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware current time, used as the default stamp on every artifact."""
    return datetime.now(timezone.utc)


class LifecyclePhase(str, Enum):
    """The five governed phases of the integration lifecycle."""

    DISCOVERY = "discovery"
    DEVELOPMENT = "development"
    OPERATION = "operation"
    EVOLUTION = "evolution"
    RETIREMENT = "retirement"
    RETIRED = "retired"


class RegulatoryFramework(str, Enum):
    """Compliance frameworks that place an application in governance scope."""

    SOX = "sox"
    HIPAA = "hipaa"
    GDPR = "gdpr"
    PCI_DSS = "pci_dss"
    SOC2 = "soc2"


class RiskClassification(str, Enum):
    """Application risk tier, sourced from the APM asset registry."""

    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class DataSensitivity(str, Enum):
    """Data sensitivity designation carried on the APM application record."""

    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"
    INTERNAL = "internal"
    PUBLIC = "public"


class IdentityPopulation(str, Enum):
    """Identity population an integration governs (article section 6)."""

    WORKFORCE = "workforce"
    NON_HUMAN = "non_human"
    AI_AGENT = "ai_agent"


class IntegrationPath(str, Enum):
    """Integration paths of the connector strategy decision matrix (Table 4)."""

    AUTO_COMPLIANT = "auto_compliant"
    DISCONNECTED_ITSM = "disconnected_itsm"
    OOTB_CONNECTOR = "ootb_connector"
    CUSTOM_CONNECTOR = "custom_connector"


class FulfillmentChannel(str, Enum):
    """Mechanism through which a governance decision is actually executed."""

    AUTOMATED_CONNECTOR = "automated_connector"
    SEMI_AUTOMATED_WORKFLOW = "semi_automated_workflow"
    ITSM_MANUAL = "itsm_manual"


class CoverageLevel(str, Enum):
    """Degree to which a governance operation is supported by an integration."""

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"

    def satisfies(self, required: CoverageLevel) -> bool:
        """True when this coverage level meets or exceeds the required level."""
        return _COVERAGE_RANK[self] >= _COVERAGE_RANK[required]


_COVERAGE_RANK: dict[CoverageLevel, int] = {
    CoverageLevel.NONE: 0,
    CoverageLevel.PARTIAL: 1,
    CoverageLevel.FULL: 2,
}


class GovernanceOperation(str, Enum):
    """Lifecycle operations declared in a connector capability specification.

    These are governance-level operations, deliberately coarser than the SDK's
    technical `Operation` enum: an IGA policy cares that deprovisioning happens,
    not whether the connector implements it as a disable or a delete.
    """

    IDENTITY_AGGREGATION = "identity_aggregation"
    ACCOUNT_PROVISIONING = "account_provisioning"
    ACCOUNT_DEPROVISIONING = "account_deprovisioning"
    ENTITLEMENT_ENUMERATION = "entitlement_enumeration"
    ENTITLEMENT_ASSIGNMENT = "entitlement_assignment"
    ENTITLEMENT_REVOCATION = "entitlement_revocation"
    CERTIFICATION_FEED = "certification_feed"
    PASSWORD_MANAGEMENT = "password_management"
    NHI_CREDENTIAL_ROTATION = "nhi_credential_rotation"
    RISK_SIGNAL_SHARING = "risk_signal_sharing"
    SESSION_TERMINATION = "session_termination"


class Severity(str, Enum):
    """Severity used by validation findings, health assessments, anti-patterns."""

    BLOCKING = "blocking"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class GovernanceOwnership(BaseModel):
    """Named accountability for an integration.

    ILM requires the governance owner — accountable for policy alignment and
    compliance continuity — to be a named party distinct from the technical
    maintainer accountable for operational execution.
    """

    governance_owner: str = Field(description="Accountable for policy and compliance continuity")
    technical_maintainer: str = Field(description="Accountable for operational execution")
    application_owner: str = ""

    def is_separated(self) -> bool:
        """True when governance and technical accountability rest with different parties."""
        return bool(
            self.governance_owner
            and self.technical_maintainer
            and self.governance_owner.strip().lower() != self.technical_maintainer.strip().lower()
        )


class Finding(BaseModel):
    """A governance finding raised by any phase of the framework."""

    code: str = Field(description="Stable machine-readable finding code")
    severity: Severity = Severity.MEDIUM
    message: str = ""
    operation: GovernanceOperation | None = None
    remediation: str = ""

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"[{self.severity.value}] {self.code}: {self.message}"
