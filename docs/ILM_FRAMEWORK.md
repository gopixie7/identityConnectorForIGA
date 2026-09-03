# Integration Lifecycle Management (ILM)

A governance-first framework that treats IGA connectors as **policy-bound organizational
assets**, subject to the same lifecycle rigor applied to the identities they govern.

This document describes the framework as implemented in `src/iga_connector/ilm/`. It is the
executable counterpart to *Integration Lifecycle Management: A Governance Framework for IGA
Integrations* (Anant Wairagade, IDPro Body of Knowledge draft).

---

## The problem

IGA platforms have mature processes for the identity lifecycle — joiner, mover, leaver;
certification; segregation of duties. The *integrations* that make those processes
operationally effective have no lifecycle discipline of their own. Connectors are built in
response to an audit finding, deployed, and left to degrade.

When one fails silently — a target API changed, a service account credential expired, a schema
update introduced unmapped attributes — the governance platform keeps operating on stale data:

- Certification campaigns certify entitlements that no longer reflect real access.
- Deprovisioning succeeds in the IGA platform and fails at the target.
- Access that should have been removed persists because the connector lost its write capability.

These blind spots are, by definition, invisible until an audit or an incident makes them
apparent. **The identities are governed; the governance infrastructure itself is not.**

## The governing principle

> Governance policy precedes and shapes every phase of the integration lifecycle.

Everything below follows from that. Requirements are derived from policy before any development
or procurement decision. Capability is declared as a contract, not discovered after the fact.
Health thresholds come from the policy the connector serves. Evolution is triggered by policy
change as well as technical change. Retirement is a governance event with compliance
obligations.

---

## The five phases

| Phase | Module | Produces |
|---|---|---|
| 1. Discovery | `discovery.py` | `IntegrationRequirementSpec` — the governance baseline |
| 2. Development | `strategy.py`, `capability.py` | `StrategyDecision` + `ConnectorCapabilityMap` |
| 3. Operation | `health.py` | `HealthAssessment` against governance thresholds |
| 4. Evolution | `evolution.py` | `EvolutionRequest` with a traceability chain |
| 5. Retirement | `retirement.py` | `GovernedRetirement` + authorized `RetirementDisposition` |

Cross-cutting:

| Concern | Module |
|---|---|
| Policy obligations across the lifecycle | `charter.py` — `ConnectorGovernanceCharter` |
| APM as the application governance control plane | `apm.py` |
| Registry of record, blind-spot mapping | `inventory.py` |
| The four anti-patterns, as detectors | `antipatterns.py` |
| Maturity scoring | `maturity.py` |
| The phases wired together | `lifecycle.py` — `ILMPipeline` |

---

### Phase 1 — Governance-driven discovery

The first question is not *"what connectors exist?"* or *"what connectors can we build?"* but
**"what governance obligations must this integration fulfil?"**

Inputs — the same ones the article names:

- Application risk classification and data sensitivity, from the APM asset registry
- Regulatory scope (SOX, HIPAA, GDPR, PCI DSS, SOC 2), which determines mandatory operations
- IGA platform policy: JML rules, certification cadence, SoD ruleset scope, access request workflow
- Existing connector coverage across the portfolio, which surfaces blind spots

```python
requirements = derive_requirements(application, policy=policy, charter=charter)
```

The output is a governance-derived contract: which operations the connector must support, at
what coverage, driven by which policy or regulation. Every requirement carries its `sources`, so
an auditor can trace an obligation back to the rule that created it.

Health thresholds are set here too — calibrated to the application's risk tier, not chosen by
whoever built the connector.

### Phase 2 — Strategy routing and capability specifications

Before anything is built, the application is routed to one of four integration paths:

| Condition | Path | Mechanism |
|---|---|---|
| Authorization exclusively via directory groups, no local user store | **Auto-compliant** | No dedicated connector; the directory connector already covers it |
| No API/SDK, vendor restriction, or cost-prohibitive | **Disconnected (ITSM)** | IGA governs; ITSM tickets fulfil provisioning through a human operator |
| API/SDK available, OOTB connector with satisfactory coverage | **OOTB connector** | Deploy the vendor connector; validate coverage before promotion |
| API/SDK available, no OOTB or unacceptable gaps | **Custom connector** | Build against REST/SDK, low-code and metadata-driven |

```python
decision = decide_integration_path(application, requirements=requirements)
```

**Every path carries a capability specification obligation** — including the two where no
connector is written. Auto-compliant applications declare against the directory connector;
disconnected applications declare ITSM as the fulfillment channel and its SLA as the primary
health indicator.

The capability specification is the governance contract between the integration and the IGA
platform's policy and certification functions:

```python
capability_map.declare(
    GovernanceOperation.ENTITLEMENT_ENUMERATION,
    CoverageLevel.PARTIAL,
    coverage_scope="Roles only; fine-grained permissions excluded",
    governance_dependencies=["Access certification"],
    gap_control="Manual entitlement supplement for permissions, reviewed quarterly",
)
validation = capability_map.validate_against(requirements)
```

**The promotion gate.** A required operation that is neither covered nor compensated is a
*blocking* finding, and `inventory.promote()` refuses to move the integration into production
governance while one exists. A documented compensating control converts a blocking gap into a
tracked one — which is the difference between a known risk and an invisible one.

`ConnectorCapabilityMap.from_connector()` derives a draft declaration from a live
`BaseConnector`'s supported operations. That is the mechanical half of the **retroactive
capability declaration** the article recommends as an entry point; coverage scope, governance
dependencies, and gap controls remain governance judgments.

### Phase 3 — Operational health governance

Five indicators, with thresholds and escalation paths set by policy rather than by engineering:

| Indicator | Governance consequence when it slips |
|---|---|
| Aggregation completeness | Accounts missing from the platform's view of the target |
| Provisioning success rate | Failures that aren't retried or escalated create access gaps |
| Deprovisioning latency | Access exposure windows that may violate revocation requirements |
| Entitlement schema validation | Entitlements the connector doesn't enumerate are certification blind spots |
| Credential validity | The most common cause of silent connector failure |

**Silent failure is the concern.** A connector that fails noisily is detectable and remediable.
One that degrades quietly — aggregating a diminishing proportion of accounts, failing
deprovisioning without error propagation — accumulates blind spots across certification cycles.
`assess_health()` compares each observation against recent history and flags
`silent_degradation` when coverage declines *while the connector reports no errors at all*.

Escalation follows the accountability split ILM requires: a breach or silent degradation goes to
the **governance owner**, ordinary degradation to the **technical maintainer**. Health
degradation escalated to a technical support queue is how compliance exposure goes unowned.

### Phase 4 — Governance-triggered evolution

Conventional evolution is technically triggered. ILM adds four policy triggers:

- SoD rule expansion
- Certification requirement change (annual → quarterly, role → permission level)
- Regulatory scope expansion
- Application risk reclassification

```python
request = pipeline.evolve(integration_id, EvolutionTrigger.CERTIFICATION_REQUIREMENT_CHANGE,
                          policy=updated_policy)
```

Requirements are **re-derived from policy**, then compared against what the integration actually
declares. The resulting gap is tracked through a four-stage chain — policy decision → requirement
spec update → capability enhancement → capability map revision — so a policy change cannot
quietly fail to reach the integration team. `outstanding_stages()` answers the audit question
*"where did this land?"*.

### Phase 5 — Governed retirement

Retirement is a governance event, not a technical decommission. Four obligations (five for
non-human identity connectors):

1. **Active certification resolution** — pending campaigns completed, transitioned, or closed with justification
2. **Entitlement data disposition** — maintained from an alternative source, archived, or retired
3. **Orphaned account remediation** — accounts provisioned through the connector reviewed and dispositioned
4. **Audit trail preservation** — retained for the period the regulatory scope requires
5. **Credential invalidation** (NHI/AI agent) — credentials rotated or invalidated, dependents updated

```python
retirement.resolve(obligation, resolved_by="gov.owner", evidence="ORPHAN-4471")
disposition = retirement.authorize("gov.owner")   # raises RetirementBlockedError otherwise
```

Resolution requires evidence — this is an audit record, not a checkbox. Authorization is refused
while any obligation stands, and the retention horizon is derived from the regulatory scope
(SOX 7 years, HIPAA 6, and so on).

---

## Cross-cutting machinery

### The Connector Governance Charter

Every policy decision the framework makes is charter-driven, not hard-coded: which operations
each regulatory framework mandates, how thresholds are calibrated to risk, retention periods,
whether compensating controls may substitute for coverage, whether ownership must be separated.

```bash
iga-ilm charter-template -o charter.yaml    # start from framework defaults, then edit
```

### APM as the application governance control plane

Integration governance should be triggered by application registration, not by audit findings.
An APM stage transition emits a lifecycle event, and the pipeline routes it to the phase it
activates:

| APM transition | ILM phase |
|---|---|
| → testing | Discovery |
| → production | Development (first time) or Operation (promotion) |
| → sunset / decommissioned | Retirement |
| planned → development | *(no integration governance obligation)* |

```python
event = pipeline.portfolio.emit_transition("APP-014", APMLifecycleStage.PRODUCTION)
outcome = pipeline.on_apm_event(event)
```

### Blind-spot mapping

A blind spot is invisible by construction, so it is *derived* rather than reported: what remains
when active, effective coverage is subtracted from the portfolio that policy places in scope. An
integration whose health has breached its thresholds counts as nominal coverage, not effective
coverage — it still surfaces as a blind spot.

### Anti-patterns

| Anti-pattern | Detected from |
|---|---|
| **Build-and-forget** | Production integrations with no capability map, no named governance owner, or no (or stale) health observations |
| **Ungoverned retirement** | Retired with no authorized disposition, or an application at sunset with no retirement opened |
| **Technical evolution only** | An evolution history with no governance trigger, or a policy change stalled mid-chain |
| **APM–IGA disconnection** | No portfolio, stale sync, integrations unknown to the APM, or in-scope applications that never triggered onboarding |

### Maturity model

The article names the maturity model as the path "from reactive integration management to
adaptive, APM-integrated governance" and leaves its levels to practitioners. The five levels
here **operationalize that stated path** and are an extension beyond the draft; each is scored
from evidence already in the inventory, so a level is measured rather than self-declared.

1. **Reactive** — integrations built on escalation, undeclared
2. **Declared** — capability specifications registered and validated, ownership named
3. **Monitored** — health governed against compliance thresholds
4. **Governed** — policy-triggered evolution and governed retirement
5. **Adaptive** — APM-integrated, blind spots systematically closed

---

## CLI

```bash
iga-ilm charter-template -o charter.yaml
iga-ilm requirements  -a application.yaml --policy policy.yaml
iga-ilm strategy      -a application.yaml
iga-ilm discover      -a application.yaml --policy policy.yaml
iga-ilm validate      -i inventory.yaml --integration app-014-integration
iga-ilm health        -i inventory.yaml --observation observation.yaml --save
iga-ilm blind-spots   -i inventory.yaml -p portfolio.yaml
iga-ilm coverage      -i inventory.yaml -p portfolio.yaml
iga-ilm anti-patterns -i inventory.yaml -p portfolio.yaml
iga-ilm maturity      -i inventory.yaml -p portfolio.yaml
iga-ilm retirement    -i inventory.yaml --integration app-014-integration
```

Commands exit non-zero when they find a governance problem (a blocking validation finding, an
unhealthy connector, a blind spot, an anti-pattern), so they drop straight into CI.

Sample inputs are in `config/ilm/`. A full worked lifecycle is in
`examples/ilm_governance_lifecycle.py`.

## Where to start

The article's advice for practitioners, and what this implementation supports directly:

1. **Map governance blind spots** — load the portfolio and inventory, run `blind-spots`.
2. **Declare capability retroactively** — `ConnectorCapabilityMap.from_connector()` for every
   connector already in production, then fill in scope, dependencies, and gap controls.
3. **Audit APM metadata quality** for the IGA-relevant fields — risk classification, regulatory
   scope, authorization model, lifecycle stage, planned decommission date.

## Scope note

Sections 1–6 of the article map onto code as described above. Two things go beyond the draft and
are marked as such in the source: the **maturity model levels** (the article names the model and
its endpoints but does not enumerate levels), and the **AI agent obligations** in the default
charter (section 6.3 identifies the domain as emerging rather than settled). Both are charter- or
policy-configurable, so an organization can replace them without touching the framework.
