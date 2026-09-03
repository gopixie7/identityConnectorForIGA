"""Phase 5 — Governed retirement.

Connector retirement is a governance event with compliance obligations, not a
technical decommission. Governed retirement resolves every outstanding
obligation attached to an integration before it is removed from operation.

Without it, decommissioned connectors leave governance blind spots that can
persist through multiple audit cycles before anyone detects them.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from .charter import ConnectorGovernanceCharter
from .models import (
    IdentityPopulation,
    RegulatoryFramework,
    Severity,
    utcnow,
)


def _add_years(start: date, years: int) -> date:
    """Add whole years to a date, clamping 29 February onto 28 February."""
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return start.replace(year=start.year + years, day=28)


class RetirementObligation(str, Enum):
    """The categories of obligation a governed retirement must resolve."""

    ACTIVE_CERTIFICATION_RESOLUTION = "active_certification_resolution"
    ENTITLEMENT_DATA_DISPOSITION = "entitlement_data_disposition"
    ORPHANED_ACCOUNT_REMEDIATION = "orphaned_account_remediation"
    AUDIT_TRAIL_PRESERVATION = "audit_trail_preservation"
    CREDENTIAL_INVALIDATION = "credential_invalidation"


#: The obligation text as the framework states it, used to render checklists.
OBLIGATION_DESCRIPTIONS: dict[RetirementObligation, str] = {
    RetirementObligation.ACTIVE_CERTIFICATION_RESOLUTION: (
        "Pending or in-progress certification campaigns that rely on this connector's "
        "aggregation or entitlement feed are completed, transitioned to an alternative data "
        "source, or formally closed with documented justification."
    ),
    RetirementObligation.ENTITLEMENT_DATA_DISPOSITION: (
        "The governance disposition of all entitlement data aggregated through the connector "
        "is documented — maintained from an alternative source, archived, or retired."
    ),
    RetirementObligation.ORPHANED_ACCOUNT_REMEDIATION: (
        "Accounts provisioned through the connector are reviewed and dispositioned — either "
        "confirmed as actively managed through an alternative mechanism, or deprovisioned."
    ),
    RetirementObligation.AUDIT_TRAIL_PRESERVATION: (
        "Aggregation logs, provisioning and deprovisioning records, and health monitoring data "
        "are retained for the period required by applicable regulatory frameworks."
    ),
    RetirementObligation.CREDENTIAL_INVALIDATION: (
        "Credentials managed by the connector are rotated or invalidated and dependent services "
        "are updated to successor credentials."
    ),
}


class ChecklistItem(BaseModel):
    """One obligation on the governed retirement checklist."""

    obligation: RetirementObligation
    description: str = ""
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str = ""
    evidence: str = Field(default="", description="Reference to the record that discharges it")
    severity: Severity = Severity.BLOCKING

    def resolve(self, resolved_by: str, evidence: str) -> ChecklistItem:
        """Discharge the obligation. Evidence is mandatory — this is an audit record."""
        if not evidence.strip():
            raise ValueError(
                f"Obligation '{self.obligation.value}' cannot be resolved without evidence"
            )
        self.resolved = True
        self.resolved_by = resolved_by
        self.evidence = evidence
        self.resolved_at = utcnow()
        return self


class RetirementDisposition(BaseModel):
    """The governance disposition that authorizes technical removal.

    An integration is only removed once every blocking obligation is discharged
    and the disposition is signed by the governance owner.
    """

    authorized: bool = False
    authorized_by: str = ""
    authorized_at: datetime | None = None
    audit_retention_years: int = 3
    retain_until: date | None = None
    notes: str = ""


class GovernedRetirement(BaseModel):
    """The retirement workflow for one integration.

    Usage:
        retirement = GovernedRetirement.open(
            integration_id="crm-prod",
            application_id="APP-014",
            regulatory_scope=[RegulatoryFramework.SOX],
            charter=charter,
        )
        retirement.resolve(
            RetirementObligation.ORPHANED_ACCOUNT_REMEDIATION,
            resolved_by="gov.owner", evidence="ORPHAN-2411",
        )
        disposition = retirement.authorize("gov.owner")   # raises while items remain
    """

    integration_id: str
    application_id: str = ""
    opened_at: datetime = Field(default_factory=utcnow)
    trigger: str = Field(default="apm_sunset_event", description="What opened the window")
    planned_decommission_date: date | None = None
    regulatory_scope: list[RegulatoryFramework] = Field(default_factory=list)
    items: list[ChecklistItem] = Field(default_factory=list)
    disposition: RetirementDisposition = Field(default_factory=RetirementDisposition)

    @classmethod
    def open(
        cls,
        integration_id: str,
        application_id: str = "",
        regulatory_scope: list[RegulatoryFramework] | None = None,
        identity_population: IdentityPopulation = IdentityPopulation.WORKFORCE,
        planned_decommission_date: date | None = None,
        trigger: str = "apm_sunset_event",
        charter: ConnectorGovernanceCharter | None = None,
    ) -> GovernedRetirement:
        """Open the retirement window with the checklist this integration owes.

        The charter sets the audit retention period from the regulatory scope
        in effect; framework defaults apply when none is supplied.
        """
        obligations = [
            RetirementObligation.ACTIVE_CERTIFICATION_RESOLUTION,
            RetirementObligation.ENTITLEMENT_DATA_DISPOSITION,
            RetirementObligation.ORPHANED_ACCOUNT_REMEDIATION,
            RetirementObligation.AUDIT_TRAIL_PRESERVATION,
        ]
        if identity_population in (IdentityPopulation.NON_HUMAN, IdentityPopulation.AI_AGENT):
            # Retiring a non-human identity connector must verify that every
            # credential it managed is rotated or invalidated.
            obligations.append(RetirementObligation.CREDENTIAL_INVALIDATION)

        charter = charter or ConnectorGovernanceCharter()
        retention = charter.retention_years(regulatory_scope or [])

        return cls(
            integration_id=integration_id,
            application_id=application_id,
            trigger=trigger,
            planned_decommission_date=planned_decommission_date,
            regulatory_scope=list(regulatory_scope or []),
            items=[
                ChecklistItem(obligation=o, description=OBLIGATION_DESCRIPTIONS[o])
                for o in obligations
            ],
            disposition=RetirementDisposition(audit_retention_years=retention),
        )

    # --- checklist --------------------------------------------------------

    def item(self, obligation: RetirementObligation) -> ChecklistItem | None:
        return next((i for i in self.items if i.obligation == obligation), None)

    def resolve(
        self, obligation: RetirementObligation, resolved_by: str, evidence: str
    ) -> ChecklistItem:
        """Discharge one obligation on the checklist."""
        item = self.item(obligation)
        if item is None:
            raise KeyError(f"'{obligation.value}' is not on this retirement checklist")
        return item.resolve(resolved_by=resolved_by, evidence=evidence)

    def outstanding(self) -> list[ChecklistItem]:
        return [i for i in self.items if not i.resolved]

    def blocking(self) -> list[ChecklistItem]:
        return [i for i in self.outstanding() if i.severity == Severity.BLOCKING]

    def is_complete(self) -> bool:
        return not self.blocking()

    # --- disposition ------------------------------------------------------

    def authorize(self, authorized_by: str, notes: str = "") -> RetirementDisposition:
        """Authorize technical removal once all blocking obligations are discharged.

        Raises `RetirementBlockedError` while any remain: an ungoverned retirement is
        the anti-pattern this phase exists to prevent.
        """
        outstanding = self.blocking()
        if outstanding:
            raise RetirementBlockedError(
                f"{len(outstanding)} obligation(s) outstanding for '{self.integration_id}': "
                + ", ".join(i.obligation.value for i in outstanding),
                obligations=[i.obligation for i in outstanding],
            )
        now = utcnow()
        self.disposition.authorized = True
        self.disposition.authorized_by = authorized_by
        self.disposition.authorized_at = now
        self.disposition.notes = notes
        self.disposition.retain_until = _add_years(
            now.date(), self.disposition.audit_retention_years
        )
        return self.disposition


class RetirementBlockedError(Exception):
    """Raised when retirement is authorized with obligations still outstanding."""

    def __init__(self, message: str, obligations: list[RetirementObligation] | None = None) -> None:
        super().__init__(message)
        self.obligations = obligations or []
