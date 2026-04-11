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

## Project Structure

```
src/iga_connector/
├── core/               # Base connector, models, schema, operations, exceptions
├── auth/               # Authentication strategies (Basic, OAuth2, API Key)
├── transport/          # HTTP transport with retries and auth injection
├── handlers/           # Reusable account & entitlement CRUD handlers
├── config/             # YAML/JSON config loading with env-var resolution
├── utils/              # Logging setup
├── registry.py         # Connector type registry / factory
└── cli.py              # Command-line interface

templates/
├── rest_connector/     # Generic REST API connector
├── scim_connector/     # SCIM 2.0 connector
├── database_connector/ # SQL database connector (PostgreSQL, MySQL, etc.)
└── ldap_connector/     # LDAP / Active Directory connector

examples/
└── sample_rest_connector.py   # Full working example
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

## Running Tests

```bash
pip install -e ".[dev]"
pytest -v
```

## Configuration

All configs support `${ENV_VAR}` placeholders that resolve to environment variables at load time — keep secrets out of config files.

## License

MIT
