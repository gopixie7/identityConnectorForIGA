"""The Connector Governance Charter.

The charter is the policy object that ILM's phases read from. It defines the
obligations that apply across the connector lifecycle — which governance
operations each regulatory framework mandates, how health thresholds are
calibrated to application risk, and how long audit trails must be preserved
after retirement.

Every default in this module is *policy*, not a law of the framework: an
organization supplies its own charter (from YAML/JSON) and the five phases
behave accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..core.exceptions import ConfigurationError
from .models import (
    CoverageLevel,
    GovernanceOperation,
    IdentityPopulation,
    RegulatoryFramework,
    RiskClassification,
)

OP = GovernanceOperation
RF = RegulatoryFramework
RC = RiskClassification


class HealthThresholds(BaseModel):
    """Governance-calibrated thresholds for the five ILM health indicators.

    Thresholds are a governance artifact, not a technical one: they are derived
    from the risk classification of the application the connector governs.
    """

    min_aggregation_completeness: float = Field(
        default=0.97, ge=0.0, le=1.0, description="Minimum acceptable aggregation completeness rate"
    )
    min_provisioning_success_rate: float = Field(
        default=0.95, ge=0.0, le=1.0, description="Minimum acceptable provisioning success rate"
    )
    max_deprovisioning_latency_hours: float = Field(
        default=72.0, gt=0, description="Maximum elapsed time to confirmed disable/delete"
    )
    max_unmapped_entitlements: int = Field(
        default=5, ge=0, description="Tolerated entitlement schema drift, in unmapped entitlements"
    )
    min_credential_days_remaining: int = Field(
        default=14, ge=0, description="Escalate when credentials expire within this many days"
    )
    max_observation_age_hours: float = Field(
        default=168.0, gt=0, description="A connector unobserved for longer is not health-governed"
    )
    silent_drift_tolerance: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Completeness decline across windows that counts as silent degradation",
    )


def _default_regulatory_matrix() -> dict[RegulatoryFramework, list[GovernanceOperation]]:
    """Governance operations each framework makes mandatory for a connector."""
    return {
        RF.SOX: [
            OP.IDENTITY_AGGREGATION,
            OP.ACCOUNT_PROVISIONING,
            OP.ACCOUNT_DEPROVISIONING,
            OP.ENTITLEMENT_ENUMERATION,
            OP.ENTITLEMENT_REVOCATION,
            OP.CERTIFICATION_FEED,
        ],
        RF.HIPAA: [
            OP.IDENTITY_AGGREGATION,
            OP.ACCOUNT_DEPROVISIONING,
            OP.ENTITLEMENT_ENUMERATION,
            OP.CERTIFICATION_FEED,
        ],
        RF.GDPR: [
            OP.IDENTITY_AGGREGATION,
            OP.ACCOUNT_DEPROVISIONING,
            OP.ENTITLEMENT_ENUMERATION,
        ],
        RF.PCI_DSS: [
            OP.IDENTITY_AGGREGATION,
            OP.ACCOUNT_PROVISIONING,
            OP.ACCOUNT_DEPROVISIONING,
            OP.ENTITLEMENT_ENUMERATION,
            OP.CERTIFICATION_FEED,
        ],
        RF.SOC2: [
            OP.IDENTITY_AGGREGATION,
            OP.ACCOUNT_DEPROVISIONING,
            OP.CERTIFICATION_FEED,
        ],
    }


def _default_population_matrix() -> dict[IdentityPopulation, list[GovernanceOperation]]:
    """Additional operations mandated by the identity population being governed.

    Non-human and AI agent populations carry obligations that the workforce
    lifecycle does not: there is no HR system as an authoritative source, and
    credential rotation and containment take the place of joiner/leaver events.
    """
    return {
        IdentityPopulation.WORKFORCE: [],
        IdentityPopulation.NON_HUMAN: [OP.NHI_CREDENTIAL_ROTATION],
        IdentityPopulation.AI_AGENT: [
            OP.NHI_CREDENTIAL_ROTATION,
            OP.RISK_SIGNAL_SHARING,
            OP.SESSION_TERMINATION,
        ],
    }


def _default_threshold_matrix() -> dict[RiskClassification, HealthThresholds]:
    """Health thresholds calibrated per application risk classification."""
    return {
        RC.CRITICAL: HealthThresholds(
            min_aggregation_completeness=0.995,
            min_provisioning_success_rate=0.99,
            max_deprovisioning_latency_hours=4.0,
            max_unmapped_entitlements=0,
            min_credential_days_remaining=30,
            max_observation_age_hours=24.0,
            silent_drift_tolerance=0.005,
        ),
        RC.HIGH: HealthThresholds(
            min_aggregation_completeness=0.99,
            min_provisioning_success_rate=0.98,
            max_deprovisioning_latency_hours=24.0,
            max_unmapped_entitlements=2,
            min_credential_days_remaining=21,
            max_observation_age_hours=72.0,
            silent_drift_tolerance=0.01,
        ),
        RC.MODERATE: HealthThresholds(),
        RC.LOW: HealthThresholds(
            min_aggregation_completeness=0.95,
            min_provisioning_success_rate=0.90,
            max_deprovisioning_latency_hours=168.0,
            max_unmapped_entitlements=10,
            min_credential_days_remaining=7,
            max_observation_age_hours=720.0,
            silent_drift_tolerance=0.05,
        ),
    }


def _default_retention_matrix() -> dict[RegulatoryFramework, int]:
    """Audit trail retention, in years, that survives connector retirement."""
    return {RF.SOX: 7, RF.HIPAA: 6, RF.PCI_DSS: 1, RF.GDPR: 3, RF.SOC2: 3}


class ConnectorGovernanceCharter(BaseModel):
    """Policy obligations that apply across the connector lifecycle.

    Usage:
        charter = ConnectorGovernanceCharter()             # framework defaults
        charter = ConnectorGovernanceCharter.load("charter.yaml")

        ops = charter.mandatory_operations(
            frameworks=[RegulatoryFramework.SOX],
            population=IdentityPopulation.WORKFORCE,
        )
    """

    name: str = "Default Connector Governance Charter"
    version: str = "1.0.0"

    regulatory_operations: dict[RegulatoryFramework, list[GovernanceOperation]] = Field(
        default_factory=_default_regulatory_matrix
    )
    population_operations: dict[IdentityPopulation, list[GovernanceOperation]] = Field(
        default_factory=_default_population_matrix
    )
    risk_thresholds: dict[RiskClassification, HealthThresholds] = Field(
        default_factory=_default_threshold_matrix
    )
    audit_retention_years: dict[RegulatoryFramework, int] = Field(
        default_factory=_default_retention_matrix
    )

    default_retention_years: int = Field(
        default=3, description="Retention applied when no regulatory framework is in scope"
    )
    require_separated_ownership: bool = Field(
        default=True, description="Governance owner must differ from technical maintainer"
    )
    require_capability_map_before_production: bool = Field(
        default=True, description="No integration reaches production governance undeclared"
    )
    allow_partial_coverage_with_gap_control: bool = Field(
        default=True,
        description="A documented compensating control may substitute for missing coverage",
    )
    sod_requires_entitlement_enumeration: bool = Field(
        default=True, description="An in-scope SoD ruleset mandates entitlement enumeration"
    )
    itsm_fulfillment_sla_hours: float = Field(
        default=24.0,
        gt=0,
        description="Max time from governance decision to confirmed ITSM fulfillment",
    )

    # --- policy lookups ---------------------------------------------------

    def mandatory_operations(
        self,
        frameworks: list[RegulatoryFramework] | None = None,
        population: IdentityPopulation = IdentityPopulation.WORKFORCE,
    ) -> list[GovernanceOperation]:
        """Union of operations mandated by regulatory scope and identity population."""
        required: list[GovernanceOperation] = []
        for framework in frameworks or []:
            for op in self.regulatory_operations.get(framework, []):
                if op not in required:
                    required.append(op)
        for op in self.population_operations.get(population, []):
            if op not in required:
                required.append(op)
        return required

    def thresholds_for(self, risk: RiskClassification) -> HealthThresholds:
        """Health thresholds that policy assigns to an application of this risk tier."""
        return self.risk_thresholds.get(risk, HealthThresholds())

    def retention_years(self, frameworks: list[RegulatoryFramework] | None = None) -> int:
        """Longest retention obligation across the frameworks in scope."""
        periods = [
            self.audit_retention_years[f]
            for f in frameworks or []
            if f in self.audit_retention_years
        ]
        return max(periods) if periods else self.default_retention_years

    def required_coverage(self, operation: GovernanceOperation) -> CoverageLevel:
        """Coverage level a mandatory operation must reach to satisfy the charter."""
        return CoverageLevel.FULL

    # --- persistence ------------------------------------------------------

    @classmethod
    def load(cls, source: str | Path | dict[str, Any]) -> ConnectorGovernanceCharter:
        """Load a charter from a YAML/JSON file or a plain dict."""
        if isinstance(source, dict):
            return cls(**source)

        path = Path(source)
        if not path.exists():
            raise ConfigurationError(f"Charter file not found: {path}")

        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(text)
        elif path.suffix == ".json":
            raw = json.loads(text)
        else:
            raise ConfigurationError(f"Unsupported charter format: {path.suffix}")
        return cls(**(raw or {}))

    def save(self, path: str | Path) -> Path:
        """Write the charter to YAML or JSON, inferred from the file suffix."""
        target = Path(path)
        payload = json.loads(self.model_dump_json())
        if target.suffix in (".yaml", ".yml"):
            target.write_text(yaml.safe_dump(payload, sort_keys=False))
        elif target.suffix == ".json":
            target.write_text(json.dumps(payload, indent=2))
        else:
            raise ConfigurationError(f"Unsupported charter format: {target.suffix}")
        return target
