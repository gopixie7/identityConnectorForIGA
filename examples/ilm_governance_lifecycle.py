"""Worked example: one integration through all five ILM phases.

Runs the framework end to end for a SOX-scoped application — from the APM
lifecycle event that triggers discovery, through capability declaration and the
production promotion gate, silent degradation in operation, a policy-triggered
evolution, and governed retirement.

    python examples/ilm_governance_lifecycle.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from iga_connector.ilm import (
    APMLifecycleStage,
    ApplicationRecord,
    AuthorizationModel,
    CertificationCadence,
    ConnectorCapabilityMap,
    ConnectorGovernanceCharter,
    CoverageLevel,
    EntitlementGranularity,
    EvolutionTrigger,
    GovernanceOperation,
    GovernanceOwnership,
    GovernancePolicyProfile,
    HealthObservation,
    ILMPipeline,
    IntegrationPath,
    PromotionBlockedError,
    RegulatoryFramework,
    RetirementBlockedError,
    RiskClassification,
    TraceabilityStage,
    detect_anti_patterns,
)

OP = GovernanceOperation


def banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    pipeline = ILMPipeline(charter=ConnectorGovernanceCharter())

    application = ApplicationRecord(
        application_id="APP-014",
        name="Loan Origination Platform",
        stage=APMLifecycleStage.TESTING,
        risk_classification=RiskClassification.CRITICAL,
        regulatory_scope=[RegulatoryFramework.SOX],
        authorization_model=AuthorizationModel.LOCAL_USER_STORE,
        has_api_or_sdk=True,
        application_owner="lending.platform@example.com",
    )
    pipeline.portfolio.add(application)
    pipeline.portfolio.last_synced_at = datetime.now(timezone.utc)
    pipeline.set_policy(
        "APP-014",
        GovernancePolicyProfile(
            certification_cadence=CertificationCadence.QUARTERLY, sod_ruleset_in_scope=True
        ),
    )

    # --- Phases 1 & 2: the APM event drives discovery, not an audit finding ---
    banner("Phase 1 & 2 — APM lifecycle event triggers governance-driven discovery")
    event = pipeline.portfolio.emit_transition("APP-014", APMLifecycleStage.PRODUCTION)
    outcome = pipeline.on_apm_event(event)
    integration_id = outcome.integration_id or ""
    for action in outcome.actions:
        print(f"  · {action}")
    assert outcome.requirements is not None
    print("\n  Operations the governance baseline requires:")
    for requirement in outcome.requirements.required_operations:
        print(f"    - {requirement.operation.value:<26} ({', '.join(requirement.sources)})")

    # --- Phase 2: capability declaration and the promotion gate ---------------
    banner("Phase 2 — Capability specification and the production promotion gate")
    ownership = GovernanceOwnership(
        governance_owner="identity.governance@example.com",
        technical_maintainer="iam.engineering@example.com",
    )
    capability_map = ConnectorCapabilityMap(
        integration_id=integration_id,
        application_id="APP-014",
        connector_name="loan_origination_rest",
        path=IntegrationPath.CUSTOM_CONNECTOR,
        ownership=ownership,
    )
    capability_map.declare(
        OP.IDENTITY_AGGREGATION, CoverageLevel.FULL, "All account types",
        ["Certification campaigns", "SoD evaluation"],
    )
    capability_map.declare(OP.ACCOUNT_PROVISIONING, CoverageLevel.FULL, "Standard attributes")
    capability_map.declare(
        OP.ACCOUNT_DEPROVISIONING, CoverageLevel.FULL, "Immediate disable + 30-day delete"
    )
    capability_map.declare(OP.ENTITLEMENT_ASSIGNMENT, CoverageLevel.FULL, "Roles only")
    capability_map.declare(OP.ENTITLEMENT_REVOCATION, CoverageLevel.FULL, "Roles only")
    capability_map.declare(OP.CERTIFICATION_FEED, CoverageLevel.FULL, "Roles and accounts")
    pipeline.declare_capability(integration_id, capability_map)

    try:
        pipeline.promote(integration_id)
    except PromotionBlockedError as exc:
        print("  Promotion blocked — the gate does its job:")
        for finding in exc.findings:
            print(f"    ✗ {finding.message}")

    capability_map.declare(
        OP.ENTITLEMENT_ENUMERATION,
        CoverageLevel.PARTIAL,
        coverage_scope="Roles only; fine-grained permissions excluded",
        governance_dependencies=["Access certification"],
        gap_control="Manual entitlement supplement for permissions, reviewed quarterly",
    )
    record = pipeline.promote(integration_id)
    print(f"\n  Promoted with a documented compensating control → {record.phase.value}")

    # --- Phase 3: silent degradation ----------------------------------------
    banner("Phase 3 — Operational health governance detects silent degradation")
    now = datetime.now(timezone.utc)
    for offset, completeness in ((3, 1.0), (2, 0.999), (1, 0.984)):
        assessment = pipeline.observe(
            HealthObservation(
                integration_id=integration_id,
                observed_at=now - timedelta(hours=offset),
                accounts_in_target=1000,
                accounts_aggregated=int(1000 * completeness),
                provisioning_attempted=120,
                provisioning_succeeded=120,
                deprovisioning_latency_hours=2.5,
                entitlements_in_target=48,
                entitlements_enumerated=48,
                credential_expires_at=now + timedelta(days=45),
                errors_reported=0,  # the connector is not complaining
            )
        )
        print(
            f"  completeness {completeness:.3f} → state={assessment.state.value:<9} "
            f"silent={assessment.silent_degradation}"
        )
    print(f"\n  Escalated to {assessment.escalate_to.value}: {assessment.escalation_contact}")
    for finding in assessment.findings:
        print(f"    ! {finding.code}: {finding.message}")

    # --- Phase 4: policy change, not target change ---------------------------
    banner("Phase 4 — Governance-triggered evolution")
    request = pipeline.evolve(
        integration_id,
        trigger=EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE,
        policy=GovernancePolicyProfile(
            certification_cadence=CertificationCadence.QUARTERLY,
            sod_ruleset_in_scope=True,
            entitlement_granularity=EntitlementGranularity.PERMISSION,
        ),
        description="Certification moves to permission level for SOX-scoped applications",
        raised_by="identity.governance@example.com",
    )
    for change in request.capability_changes:
        print(
            f"  {change.operation.value}: {change.current_coverage.value} → "
            f"{change.required_coverage.value} ({change.rationale})"
        )
    print(f"  Outstanding stages: {[s.value for s in request.outstanding_stages()]}")
    request.record_stage(TraceabilityStage.REQUIREMENT_SPEC_UPDATE, "identity.governance")
    request.record_stage(TraceabilityStage.CAPABILITY_ENHANCEMENT, "iam.engineering", "CHG-4471")
    capability_map.declare(
        OP.ENTITLEMENT_ENUMERATION,
        CoverageLevel.FULL,
        coverage_scope="Roles and fine-grained permissions",
        governance_dependencies=["Access certification"],
    )
    capability_map.revision += 1
    request.record_stage(TraceabilityStage.CAPABILITY_MAP_REVISION, "identity.governance")
    pipeline.inventory.close_evolution(integration_id, request)
    print(f"  Traced to closure: {request.is_closed()}")

    # --- Phase 5: retirement is a governance event ---------------------------
    banner("Phase 5 — Governed retirement")
    pipeline.portfolio.emit_transition("APP-014", APMLifecycleStage.SUNSET)
    retirement = pipeline.open_retirement(integration_id)
    print(f"  Audit trail retained for {retirement.disposition.audit_retention_years} years (SOX)")
    try:
        pipeline.retire(integration_id, authorized_by="identity.governance@example.com")
    except RetirementBlockedError as exc:
        print(f"  Removal refused with {len(exc.obligations)} obligation(s) outstanding:")
        for obligation in exc.obligations:
            print(f"    ✗ {obligation.value}")

    evidence = {
        "active_certification_resolution": "CERT-Q3-CLOSED-1182",
        "entitlement_data_disposition": "ARCHIVE-APP014-2026",
        "orphaned_account_remediation": "ORPHAN-REVIEW-4471",
        "audit_trail_preservation": "VAULT-APP014-LOGS",
    }
    for item in list(retirement.items):
        retirement.resolve(item.obligation, "identity.governance", evidence[item.obligation.value])
    pipeline.retire(integration_id, authorized_by="identity.governance@example.com")
    retain_until = retirement.disposition.retain_until
    print(f"\n  Disposition authorized; records retained until {retain_until}")

    # --- Governance reporting ------------------------------------------------
    banner("Governance reporting")
    findings = detect_anti_patterns(pipeline.inventory, pipeline.portfolio)
    if findings:
        for finding in findings:
            print(f"  [{finding.severity.value}] {finding.anti_pattern.value} — {finding.evidence}")
    else:
        print("  No anti-patterns detected.")
    maturity = pipeline.maturity()
    print(f"\n  Maturity: level {int(maturity.level)} — {maturity.level.label}")
    for action in maturity.next_actions:
        print(f"    → {action}")


if __name__ == "__main__":
    main()
