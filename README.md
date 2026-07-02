# Mission Control v2

Mission Control v2 is the FastAPI control-plane overlay for the OpenClaw and
Synapse agent system. It provides the operator UI, API proxy surfaces, durable
Mission Control state, and browser entry points for adjacent tools. It replaces
the older `spark-mission-control` codebase.

Mission Control does not own the agent runtime, Project Box task files, Twenty
CRM records, or HECL memory atoms. Those systems remain external and are reached
through configured service URLs.

## Core Responsibilities

- Synapse multi-agent chat and fleet status.
- Agent queue creation, assignment, dispatch, and dispatch history.
- Daily briefing blocks from Mission Control state and external integrations.
- Project Box task proxy and focus timer integration.
- Email triage metadata and decision workflow.
- Auth, health checks, account/context settings, and top-level app navigation.

## Architecture

```text
Browser
  -> Mission Control v2 (FastAPI, Jinja, static JS)
      -> PostgreSQL for Mission Control-owned state
      -> Redis for sessions, caches, focus state, and sweep locks
      -> OpenClaw gateway for Synapse and dispatch
      -> Project Box for canonical human tasks
      -> Twenty CRM for CRM UI/data
      -> Decapoda for calendar runway data
```

## Repository Layout

```text
main.py                 FastAPI app entrypoint and lifespan wiring
config.py               Environment-backed settings
api/routers/            HTTP and WebSocket routes
api/middleware/         Request middleware
services/               Business logic and external clients
repositories/           SQLAlchemy query and mutation helpers
schemas/                Pydantic request and response DTOs
db/                     SQLAlchemy session, base, and ORM models
cache/                  Redis clients and cache helpers
templates/              Jinja templates
static/                 Browser JavaScript, CSS, fonts, and images
alembic/                Database migrations
scripts/                Migration, parity, and operator utilities
tests/                  Pytest suite
e2e/                    Browser-oriented smoke tests
docs/                   Active planning and topology notes
```

The codebase is intentionally flat: feature logic is grouped by role rather than
deep package nesting. Add new files under the existing role directory unless a
new owned subsystem genuinely needs a new top-level package.

## Quick Start

```bash
cp .env.example .env
chmod +x start.sh
./start.sh
```

The app runs on the host and port from `.env`. Docker Compose starts local
PostgreSQL and Redis for development.

Useful commands:

```bash
make dev       # start Docker services, run migrations, boot the app
make test      # start test dependencies and run pytest
make lint      # compile Python modules
make migrate   # run Alembic plus v1 JSON migration
make parity    # compare selected v1/v2 endpoint shapes
```

## Configuration

All secrets, tokens, credentials, and machine-specific URLs belong in `.env`.
`.env.example` is a public template only and should contain placeholders or
localhost defaults.

Important settings:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `DATABASE_URL`, `REDIS_URL`
- `HOST`, `PORT`, `PUBLIC_BASE_URL`
- `AUTH_ENABLED`, `MISSION_CONTROL_USERNAME`,
  `MISSION_CONTROL_PASSWORD_HASH`, `SESSION_SECRET`
- `MOLTBOT_GATEWAY_WS_URL`, `MOLTBOT_TOKEN`
- `PROJECTBOX_URL`, `PROJECTBOX_PUBLIC_URL`
- `TWENTY_CRM_URL`, `TWENTY_CRM_PUBLIC_URL`
- `DECAPODA_BASE_URL`
- `ETHER_VOICE_*` voice appliance settings

Leave external integration URLs blank when the integration is not available.
Startup should remain healthy when the OpenClaw gateway is absent.

## Data Ownership

- Mission Control owns PostgreSQL rows under the `core`, `kanban`, and `agents`
  schemas.
- Project Box owns human task files and the full task UI.
- OpenClaw owns agent runtime state, model execution, sessions, and gateway
  protocol behavior.
- Twenty owns CRM data and CRM UI behavior.
- HECL owns memory atoms and embedding storage.

Do not read or write external owners' files directly from this repo. Use the
existing service clients and configured APIs.

## Testing

```bash
make test
pytest -q
```

Tests expect local PostgreSQL and Redis services from `docker-compose.yml`.
Project Box and OpenClaw network boundaries are mocked or disabled in tests.

## Public Repository Hygiene

Exclude these from any public commit:

- `.env`, `.env.*`, credential backups, tokens, API keys, and session secrets.
- `data/`, logs, queue run logs, local cache files, and generated reports.
- `archive/`, which is intentionally untracked local history.
- Virtual environments, Python caches, coverage output, and editor workspace
  files.
- `AGENTS.md` unless it has been sanitized for public operator-neutral use.
- Machine-specific URLs, private hostnames, LAN IPs, and personal paths unless
  they are intentionally documented examples.

Before publishing:

```bash
git status --short --ignored
rg -n --hidden --glob '!venv/**' --glob '!.git/**' \
  '(TOKEN|SECRET|PASSWORD|API[_-]?KEY|PRIVATE|BEGIN .*KEY|192\.168\.|jwells)'
```

Review every match before committing. Real local values should stay in `.env`;
public defaults should live in `.env.example`.
