"""CLI entry point for running connector operations.

Usage:
    iga-connector test-connection --config connector.yaml
    iga-connector list-accounts --config connector.yaml
    iga-connector schema --config connector.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_config
from .registry import connector_registry
from .utils import setup_logging

# Import templates so they auto-register
import importlib


def _import_templates() -> None:
    """Import built-in connector templates so they register themselves."""
    template_modules = [
        "templates.rest_connector.connector",
        "templates.scim_connector.connector",
        "templates.database_connector.connector",
        "templates.ldap_connector.connector",
    ]
    for mod in template_modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iga-connector",
        description="IGA Connector SDK – run connector operations from the command line",
    )
    parser.add_argument(
        "--config", "-c", required=True, help="Path to connector YAML/JSON config"
    )
    parser.add_argument(
        "--log-level", default="INFO", help="Logging level (default: INFO)"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("test-connection", help="Test connectivity to the target system")
    sub.add_parser("list-accounts", help="List accounts on the target system")
    sub.add_parser("list-entitlements", help="List entitlements on the target system")
    sub.add_parser("schema", help="Print the connector schema as JSON")
    sub.add_parser("list-types", help="List registered connector types")

    get_acct = sub.add_parser("get-account", help="Get a single account by identity")
    get_acct.add_argument("identity", help="Account identity")

    return parser


async def run(args: argparse.Namespace) -> None:
    if args.command == "list-types":
        _import_templates()
        for name in connector_registry.list_registered():
            print(f"  - {name}")
        return

    config = load_config(Path(args.config))
    _import_templates()
    connector = connector_registry.create(config.connector_type, config.model_dump())

    async with connector:
        if args.command == "test-connection":
            status = await connector.test_connection()
            print(json.dumps(status.model_dump(), indent=2, default=str))

        elif args.command == "list-accounts":
            result = await connector.list_accounts()
            for acct in result.items:
                print(json.dumps(acct.model_dump(), indent=2, default=str))

        elif args.command == "list-entitlements":
            result = await connector.list_entitlements()
            for ent in result.items:
                print(json.dumps(ent.model_dump(), indent=2, default=str))

        elif args.command == "get-account":
            acct = await connector.get_account(args.identity)
            if acct:
                print(json.dumps(acct.model_dump(), indent=2, default=str))
            else:
                print(f"Account '{args.identity}' not found.", file=sys.stderr)
                sys.exit(1)

        elif args.command == "schema":
            schema = connector.get_schema()
            print(json.dumps(schema.model_dump(), indent=2, default=str))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
