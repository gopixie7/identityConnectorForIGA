"""Integration Lifecycle Management (ILM).

A governance-first framework that treats IGA connectors as policy-bound
organizational assets, subject to the same lifecycle rigor applied to the
identities they govern.

The framework's governing principle is that governance policy precedes and
shapes every phase, from the definition of connector requirements through to
the disposition of governance artifacts at retirement:

    Phase 1  discovery    governance obligations derive the requirement spec
    Phase 2  development  strategy routing plus a formal capability declaration
    Phase 3  operation    health governed against compliance thresholds
    Phase 4  evolution    policy change, not just target change, drives updates
    Phase 5  retirement   a governance event with compliance obligations

Usage:
    from iga_connector.ilm import ILMPipeline, ConnectorGovernanceCharter

    pipeline = ILMPipeline(charter=ConnectorGovernanceCharter())
    pipeline.portfolio.add(application)
    outcome = pipeline.on_apm_event(event)
"""

from .antipatterns import (
    ANTI_PATTERN_DESCRIPTIONS,
    AntiPattern,
    AntiPatternFinding,
    detect_anti_patterns,
)
from .apm import (
    APMLifecycleEvent,
    APMLifecycleStage,
    ApplicationPortfolio,
    ApplicationRecord,
    AuthorizationModel,
)
from .capability import (
    OPERATION_MAPPING,
    CapabilityDeclaration,
    CapabilityValidation,
    ConnectorCapabilityMap,
)
from .charter import ConnectorGovernanceCharter, HealthThresholds
from .discovery import (
    CertificationCadence,
    EntitlementGranularity,
    GovernancePolicyProfile,
    IntegrationRequirementSpec,
    RequiredOperation,
    derive_requirements,
)
from .evolution import (
    CapabilityChange,
    EvolutionRequest,
    EvolutionTrigger,
    TraceabilityStage,
    evaluate_evolution,
)
from .health import (
    EscalationTarget,
    HealthAssessment,
    HealthIndicator,
    HealthObservation,
    HealthState,
    IndicatorAssessment,
    assess_health,
)
from .inventory import (
    BlindSpot,
    CoverageReport,
    IntegrationGovernanceInventory,
    IntegrationRecord,
    PromotionBlockedError,
)
from .lifecycle import ILMPipeline, PhaseOutcome
from .maturity import LevelCriterion, MaturityAssessment, MaturityLevel, assess_maturity
from .models import (
    CoverageLevel,
    DataSensitivity,
    Finding,
    FulfillmentChannel,
    GovernanceOperation,
    GovernanceOwnership,
    IdentityPopulation,
    IntegrationPath,
    LifecyclePhase,
    RegulatoryFramework,
    RiskClassification,
    Severity,
)
from .retirement import (
    OBLIGATION_DESCRIPTIONS,
    ChecklistItem,
    GovernedRetirement,
    RetirementBlockedError,
    RetirementDisposition,
    RetirementObligation,
)
from .strategy import StrategyDecision, decide_integration_path

__all__ = [
    # Framework entry points
    "ILMPipeline",
    "PhaseOutcome",
    "ConnectorGovernanceCharter",
    "HealthThresholds",
    "IntegrationGovernanceInventory",
    "IntegrationRecord",
    "PromotionBlockedError",
    # Vocabulary
    "CoverageLevel",
    "DataSensitivity",
    "Finding",
    "FulfillmentChannel",
    "GovernanceOperation",
    "GovernanceOwnership",
    "IdentityPopulation",
    "IntegrationPath",
    "LifecyclePhase",
    "RegulatoryFramework",
    "RiskClassification",
    "Severity",
    # APM control plane
    "APMLifecycleEvent",
    "APMLifecycleStage",
    "ApplicationPortfolio",
    "ApplicationRecord",
    "AuthorizationModel",
    # Phase 1
    "CertificationCadence",
    "EntitlementGranularity",
    "GovernancePolicyProfile",
    "IntegrationRequirementSpec",
    "RequiredOperation",
    "derive_requirements",
    # Phase 2
    "StrategyDecision",
    "decide_integration_path",
    "CapabilityDeclaration",
    "CapabilityValidation",
    "ConnectorCapabilityMap",
    "OPERATION_MAPPING",
    # Phase 3
    "EscalationTarget",
    "HealthAssessment",
    "HealthIndicator",
    "HealthObservation",
    "HealthState",
    "IndicatorAssessment",
    "assess_health",
    # Phase 4
    "CapabilityChange",
    "EvolutionRequest",
    "EvolutionTrigger",
    "TraceabilityStage",
    "evaluate_evolution",
    # Phase 5
    "ChecklistItem",
    "GovernedRetirement",
    "RetirementBlockedError",
    "RetirementDisposition",
    "RetirementObligation",
    "OBLIGATION_DESCRIPTIONS",
    # Governance reporting
    "BlindSpot",
    "CoverageReport",
    "AntiPattern",
    "AntiPatternFinding",
    "ANTI_PATTERN_DESCRIPTIONS",
    "detect_anti_patterns",
    "LevelCriterion",
    "MaturityAssessment",
    "MaturityLevel",
    "assess_maturity",
]
