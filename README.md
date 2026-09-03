# IGA Connector SDK

A low-code SDK template for building **Identity Governance & Administration (IGA)** connectors that integrate with any target system.

## What It Does

IGA platforms (SailPoint, Saviynt, One Identity, etc.) need connectors to provision and reconcile user accounts on target systems — Active Directory, HR apps, SaaS tools, databases. This SDK provides:

- **Base connector interface** with standard IGA operations (create/update/delete accounts, manage entitlements, reconciliation)
- **Pluggable authentication** (Basic Auth, OAuth 2.0 Client Credentials, API Key)
- **Spec-driven handlers** — define your target system's API endpoints in a config file instead of writing code
- **4 ready-to-use connector templates** (REST, SCIM 2.0, Database, LDAP/AD)
- **Connector registry** for dynamic instantiation from configuration
- **CLI tool** for testing connectors from the command line
- **Integration Lifecycle Management (ILM)** — a governance framework that treats connectors as
  policy-bound assets: governance-derived requirements, capability specifications, health
  governance, policy-triggered evolution, and governed retirement

## Project Structure

```
src/iga_connector/
├── core/               # Base connector, models, schema, operations, exceptions
├── auth/               # Authentication strategies (Basic, OAuth2, API Key)
├── transport/          # HTTP transport with retries and auth injection
├── handlers/           # Reusable account & entitlement CRUD handlers
├── config/             # YAML/JSON config loading with env-var resolution
├── utils/              # Logging setup
├── ilm/                # Integration Lifecycle Management (governance framework)
├── registry.py         # Connector type registry / factory
└── cli.py              # Command-line interface

src/iga_connector/ilm/
├── charter.py          # Connector Governance Charter — the policy object
├── apm.py              # Application Portfolio Management control plane
├── discovery.py        # Phase 1: governance-driven discovery
├── strategy.py         # Phase 2a: connector strategy decision matrix
├── capability.py       # Phase 2b: connector capability specifications
├── health.py           # Phase 3: health governance + silent failure detection
├── evolution.py        # Phase 4: governance-triggered evolution
├── retirement.py       # Phase 5: governed retirement
├── inventory.py        # Governance inventory + blind-spot mapping
├── antipatterns.py     # The four integration governance anti-patterns
├── maturity.py         # ILM maturity model
├── lifecycle.py        # ILMPipeline — the five phases wired together
└── cli.py              # iga-ilm command-line interface

templates/
├── rest_connector/     # Generic REST API connector
├── scim_connector/     # SCIM 2.0 connector
├── database_connector/ # SQL database connector (PostgreSQL, MySQL, etc.)
└── ldap_connector/     # LDAP / Active Directory connector

examples/
├── sample_rest_connector.py       # Full working connector example
└── ilm_governance_lifecycle.py    # One integration through all five ILM phases

config/ilm/                        # Sample application, policy, and capability specification
docs/ILM_FRAMEWORK.md              # Full ILM framework documentation
```

## Quick Start

### 1. Install

```bash
pip install -e .           # core
pip install -e ".[dev]"    # with test tooling
pip install -e ".[database]"  # with database support
```

### 2. Write a Connector Config

Create a `my_app.yaml`:

```yaml
connector_type: rest
name: My Application

connection:
  base_url: "https://api.myapp.com/v1"
  timeout: 30

auth:
  auth_type: oauth2
  params:
    token_url: "https://api.myapp.com/oauth/token"
    client_id: "${CLIENT_ID}"
    client_secret: "${CLIENT_SECRET}"

options:
  account_endpoint:
    list_path: "/users"
    get_path: "/users/{identity}"
    create_path: "/users"
    update_path: "/users/{identity}"
    delete_path: "/users/{identity}"
    identity_field: "id"
    display_name_field: "name"
    list_results_key: "data"
```

### 3. Test from CLI

```bash
iga-connector test-connection -c my_app.yaml
iga-connector list-accounts -c my_app.yaml
iga-connector schema -c my_app.yaml
```

### 4. Use in Code

```python
import asyncio
from iga_connector.config import load_config
from iga_connector.registry import connector_registry

# Import the template to register it
from templates.rest_connector.connector import RestConnector

async def main():
    config = load_config("my_app.yaml")
    connector = connector_registry.create(config.connector_type, config.model_dump())

    async with connector:
        status = await connector.test_connection()
        print(f"Connected: {status.connected}")

        accounts = await connector.list_accounts(page_size=10)
        for acct in accounts.items:
            print(f"  {acct.identity}: {acct.display_name}")

asyncio.run(main())
```

## Building a Custom Connector

Subclass `BaseConnector` and implement only the operations your target system supports:

```python
from iga_connector.core import BaseConnector, ConnectorStatus, Account, OperationResult
from iga_connector.core.schema import ConnectorSchema
from iga_connector.registry import connector_registry

@connector_registry.register("my_custom_app")
class MyCustomConnector(BaseConnector):

    def get_schema(self) -> ConnectorSchema:
        return ConnectorSchema(connector_name="my_custom_app", ...)

    async def test_connection(self) -> ConnectorStatus:
        # Check connectivity to your target system
        ...

    async def create_account(self, account: Account) -> OperationResult:
        # Provision a user on the target system
        ...

    async def list_accounts(self, page_size=50, cursor=None):
        # Reconcile accounts from the target system
        ...
```

## Supported Operations

| Operation | Description |
|---|---|
| `test_connection` | Verify connectivity and credentials |
| `create_account` | Provision a new account |
| `update_account` | Modify account attributes |
| `delete_account` | Remove / deprovision an account |
| `disable_account` | Disable an account |
| `enable_account` | Re-enable a disabled account |
| `get_account` | Retrieve a single account |
| `list_accounts` | List all accounts (paginated) |
| `get_entitlement` | Retrieve a single entitlement |
| `list_entitlements` | List all entitlements (paginated) |
| `grant_entitlement` | Assign an entitlement to an account |
| `revoke_entitlement` | Remove an entitlement from an account |
| `set_password` | Set account password |
| `reset_password` | Trigger password reset |
| `full_reconciliation` | Fetch all accounts for reconciliation |
| `incremental_reconciliation` | Fetch accounts changed since a checkpoint |

## Authentication Strategies

| Strategy | Config `auth_type` | Parameters |
|---|---|---|
| HTTP Basic | `basic` | `username`, `password` |
| OAuth 2.0 Client Credentials | `oauth2` | `token_url`, `client_id`, `client_secret`, `scope` |
| API Key | `api_key` | `api_key`, `header_name`, `location` (`header`/`query`) |

## Connector Templates

| Template | Use Case |
|---|---|
| **REST** | Any target system with a REST API |
| **SCIM 2.0** | SCIM-compliant identity providers (Azure AD, Okta, etc.) |
| **Database** | Accounts stored in SQL tables (PostgreSQL, MySQL, SQLite) |
| **LDAP** | Active Directory, OpenLDAP, 389 DS |

## Integration Lifecycle Management

Building a connector is half the job. The other half is governing it for the rest of its
operational life — which is what the `ilm` package provides.

IGA platforms govern identity lifecycles rigorously, but the connectors that make that
governance possible usually have no lifecycle discipline of their own. They are built in
response to an audit finding, deployed, and left to degrade silently while certification
campaigns attest to stale data. ILM closes that gap by treating every integration as a
policy-bound asset with five governed phases:

| Phase | What it enforces |
|---|---|
| **1. Discovery** | Requirements derive from governance policy *before* any build or buy decision |
| **2. Development** | Every integration path declares a formal capability specification, validated at a promotion gate |
| **3. Operation** | Five health indicators assessed against risk-calibrated thresholds, with silent-degradation detection |
| **4. Evolution** | Policy change — not just target API change — triggers connector updates, traced end to end |
| **5. Retirement** | Certification resolution, orphan remediation, and audit trail preservation before removal |

```python
from iga_connector.ilm import ILMPipeline, ApplicationRecord, APMLifecycleStage

pipeline = ILMPipeline()
pipeline.portfolio.add(application)

# An APM lifecycle event drives governance — not an audit finding
event = pipeline.portfolio.emit_transition("APP-014", APMLifecycleStage.PRODUCTION)
outcome = pipeline.on_apm_event(event)      # phases 1 and 2 open automatically

pipeline.declare_capability(outcome.integration_id, capability_map)
pipeline.promote(outcome.integration_id)     # refused if a required operation is uncovered
assessment = pipeline.observe(observation)   # phase 3 health governance
```

Governance reporting works over the whole portfolio:

```bash
iga-ilm blind-spots   -i inventory.yaml -p portfolio.yaml   # in-scope apps nothing covers
iga-ilm anti-patterns -i inventory.yaml -p portfolio.yaml   # build-and-forget, ungoverned retirement, …
iga-ilm maturity      -i inventory.yaml -p portfolio.yaml   # reactive → adaptive
```

These commands exit non-zero when they find a governance problem, so they drop straight into CI.

Full documentation: **[docs/ILM_FRAMEWORK.md](docs/ILM_FRAMEWORK.md)**. Worked example:
`examples/ilm_governance_lifecycle.py`. Sample inputs: `config/ilm/`.

## Running Tests

```bash
pip install -e ".[dev]"
pytest -v
```

## Configuration

Connector configs support `${ENV_VAR}` placeholders that resolve to environment variables at load time — keep secrets out of config files.

## License

MIT
