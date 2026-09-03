"""CLI for Integration Lifecycle Management.

Usage:
    iga-ilm discover        -a app.yaml [--policy policy.yaml] [--charter charter.yaml]
    iga-ilm strategy        -a app.yaml
    iga-ilm requirements    -a app.yaml [--policy policy.yaml]
    iga-ilm validate        -i inventory.yaml --integration crm-prod
    iga-ilm health          -i inventory.yaml --observation obs.yaml
    iga-ilm blind-spots     -i inventory.yaml -p portfolio.yaml
    iga-ilm anti-patterns   -i inventory.yaml [-p portfolio.yaml]
    iga-ilm maturity        -i inventory.yaml [-p portfolio.yaml]
    iga-ilm retirement      -i inventory.yaml --integration crm-prod
    iga-ilm charter-template [-o charter.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ..core.exceptions import ConfigurationError
from ..utils import setup_logging
from .antipatterns import detect_anti_patterns
from .apm import ApplicationPortfolio, ApplicationRecord
from .charter import ConnectorGovernanceCharter
from .discovery import GovernancePolicyProfile, derive_requirements
from .health import HealthObservation
from .inventory import IntegrationGovernanceInventory
from .maturity import assess_maturity
from .strategy import decide_integration_path


def _load(path: str | Path) -> dict[str, Any]:
    """Read a YAML or JSON document into a dict."""
    target = Path(path)
    if not target.exists():
        raise ConfigurationError(f"File not found: {target}")
    text = target.read_text()
    if target.suffix in (".yaml", ".yml"):
        loaded: dict[str, Any] = yaml.safe_load(text) or {}
        return loaded
    if target.suffix == ".json":
        parsed: dict[str, Any] = json.loads(text)
        return parsed
    raise ConfigurationError(f"Unsupported format: {target.suffix}")


def _emit(payload: BaseModel | dict[str, Any] | list[Any]) -> None:
    """Print a result as JSON."""
    if isinstance(payload, BaseModel):
        print(payload.model_dump_json(indent=2))
    else:
        print(json.dumps(payload, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iga-ilm",
        description=(
            "Integration Lifecycle Management — govern IGA connectors as policy-bound assets"
        ),
    )
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    parser.add_argument("--charter", help="Path to a connector governance charter YAML/JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("discover", "Run governance-driven discovery and strategy routing for an application"),
        ("requirements", "Derive the integration requirement specification only"),
        ("strategy", "Route an application to its integration path"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--application", "-a", required=True, help="Application record YAML/JSON")
        cmd.add_argument("--policy", help="IGA governance policy profile YAML/JSON")

    for name, help_text in (
        ("blind-spots", "Map in-scope applications no active integration covers"),
        ("anti-patterns", "Detect the four integration governance anti-patterns"),
        ("maturity", "Score integration governance maturity"),
        ("coverage", "Report portfolio-level governance coverage"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--inventory", "-i", required=True, help="Governance inventory YAML/JSON")
        cmd.add_argument("--portfolio", "-p", help="Application portfolio YAML/JSON")

    validate = sub.add_parser(
        "validate", help="Validate declared capability against the governance baseline"
    )
    validate.add_argument("--inventory", "-i", required=True)
    validate.add_argument("--integration", required=True, help="Integration id")

    health = sub.add_parser("health", help="Assess a health observation")
    health.add_argument("--inventory", "-i", required=True)
    health.add_argument("--observation", required=True, help="Health observation YAML/JSON")
    health.add_argument("--save", action="store_true", help="Persist the updated inventory")

    retirement = sub.add_parser("retirement", help="Show the governed retirement checklist")
    retirement.add_argument("--inventory", "-i", required=True)
    retirement.add_argument("--integration", required=True)

    template = sub.add_parser("charter-template", help="Emit a charter with framework defaults")
    template.add_argument("--out", "-o", help="Write to this path instead of stdout")

    return parser


def run(args: argparse.Namespace) -> int:
    charter = (
        ConnectorGovernanceCharter.load(args.charter)
        if getattr(args, "charter", None)
        else ConnectorGovernanceCharter()
    )

    if args.command == "charter-template":
        if args.out:
            path = charter.save(args.out)
            print(f"Wrote charter template to {path}")
        else:
            _emit(charter)
        return 0

    if args.command in ("discover", "requirements", "strategy"):
        application = ApplicationRecord(**_load(args.application))
        policy = GovernancePolicyProfile(**_load(args.policy)) if args.policy else None
        requirements = derive_requirements(application, policy=policy, charter=charter)
        if args.command == "requirements":
            _emit(requirements)
            return 0
        decision = decide_integration_path(application, requirements=requirements)
        if args.command == "strategy":
            _emit(decision)
            return 0
        _emit({"requirements": requirements.model_dump(), "strategy": decision.model_dump()})
        return 0

    inventory = IntegrationGovernanceInventory.load(args.inventory)
    inventory.charter = charter
    portfolio = (
        ApplicationPortfolio(**_load(args.portfolio))
        if getattr(args, "portfolio", None)
        else None
    )

    if args.command == "validate":
        validation = inventory.validate_capability(args.integration)
        _emit(validation)
        return 0 if validation.promotable() else 1

    if args.command == "health":
        observation = HealthObservation(**_load(args.observation))
        assessment = inventory.record_health(observation)
        if args.save:
            inventory.save(args.inventory)
        _emit(assessment)
        return 0 if assessment.state.value == "healthy" else 1

    if args.command == "retirement":
        record = inventory.require(args.integration)
        if record.retirement is None:
            print(
                f"No governed retirement is open for '{args.integration}'.",
                file=sys.stderr,
            )
            return 1
        _emit(record.retirement)
        return 0 if record.retirement.is_complete() else 1

    if args.command == "blind-spots":
        if portfolio is None:
            print("--portfolio is required to map blind spots", file=sys.stderr)
            return 2
        spots = inventory.blind_spots(portfolio)
        _emit([s.model_dump() for s in spots])
        return 0 if not spots else 1

    if args.command == "coverage":
        if portfolio is None:
            print("--portfolio is required for a coverage report", file=sys.stderr)
            return 2
        _emit(inventory.coverage_report(portfolio))
        return 0

    if args.command == "anti-patterns":
        findings = detect_anti_patterns(inventory, portfolio)
        _emit([f.model_dump() for f in findings])
        return 0 if not findings else 1

    if args.command == "maturity":
        maturity = assess_maturity(inventory, portfolio)
        _emit(
            {
                "level": int(maturity.level),
                "label": maturity.level.label,
                "criteria": [c.model_dump() for c in maturity.criteria],
                "next_actions": maturity.next_actions,
            }
        )
        return 0

    return 2


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)
    try:
        sys.exit(run(args))
    except (ConfigurationError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
