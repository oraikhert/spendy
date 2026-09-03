# Spendy: agent guide

## Working context

- These are Codex project rules; do not import Cursor-specific restrictions.
- Start with `git status --short` and a targeted `rg` search. Read the affected
  modules, callers, tests, and relevant docs, not the entire repository.
- Preserve unrelated edits. Check dependency versions before using new APIs;
  do not upgrade the stack incidentally.
- Keep multi-step plans/progress in the conversation. At handoff record decisions,
  changed paths, checks, blockers, and next steps, not tool logs.

## Orientation

Spendy is a family budget app: FastAPI, async SQLAlchemy 2.0, Pydantic v2,
Alembic, SQLite/PostgreSQL, Jinja2, HTMX, Tailwind CSS, and DaisyUI.

Use the [README task index](README.md#documentation) to select relevant docs.
The canonical folder map is in [Architecture](docs/ARCHITECTURE.md#code-map).
Service behavior and known limitations are in
[Service contracts](docs/SERVICE_LAYER.md); do not infer guarantees from layer names.

## Environment and checks

Run from the repository root. Create `venv` with `python3 -m venv venv` if missing;
this environment is git-ignored. Activate it before project Python commands:

```bash
source venv/bin/activate
python -m pip install -r requirements-dev.txt   # setup only
python run.py                                # local server, port 8000
python tests/test_parsing.py
python tests/test_parsing_kind_location.py
python tests/test_api.py                      # isolated server required
git diff --check
```

Settings load `.env` through Pydantic Settings. Override `DATABASE_URL` for
tests before importing the app; never test against a personal/production DB.
API tests create users on localhost:8000 and need registration enabled; follow the
[isolated setup](README.md#development-checks) and inspect output, not just exit codes.
For schema operations, first select the matching [migration scenario](docs/MIGRATIONS.md).
There is no configured pytest suite, linter, type checker, or frontend build.
Declare dependencies and commands when adding tooling.

## Engineering rules

- **Boundaries:** routes handle HTTP, dependencies, and error mapping; services
  own business rules. Keep DB access out of templates and Pydantic validators.
  Use typed FastAPI response models, separate input/public schemas, Pydantic v2
  methods, and `from_attributes` for ORM objects; never expose private fields.
- **Async:** use awaitable DB/HTTP clients; do not block the event loop with sync
  I/O or heavy work. Reuse lifespan-managed clients with timeouts and cleanup.
  Use one `AsyncSession` per request/task, never shared across concurrent tasks.
  Load required relationships explicitly (e.g. `selectinload`) before rendering
  or serialization; avoid implicit lazy I/O and N+1 queries.
- **Transactions:** make commit/rollback ownership explicit. For new multi-write
  workflows, use one atomic transaction; inspect existing service commits before
  composing them. Back uniqueness/integrity rules with DB constraints and handle
  conflicts. Bound and deterministically order lists.
- **Money/ingestion:** use `Decimal`/SQL `Numeric`, not float arithmetic. Preserve
  currency precision, rounding, FX originals, and purchase-negative/refund-positive
  conventions. Cover deduplication, linking/reprocessing, and date boundaries;
  do not silently change timezone or same-calendar-day matching semantics.
- **Migrations:** add a revision for schema changes; do not rewrite deployed ones.
  Review autogeneration, especially renames, constraints, and data backfills.
  Use SQLite batch operations where needed. Test upgrades/reversible rollbacks
  on disposable SQLite/PostgreSQL DBs; report untested backends. `create_all`
  is bootstrap, not migration. Never reset, stamp, or downgrade a user's DB
  without explicit authorization.
- **HTML/UI:** reuse Jinja layouts, partials, and macros with autoescaping;
  never mark untrusted content `safe`. HTMX endpoints return appropriate fragments;
  verify targets/swaps, redirects, and validation/error states. Enforce auth and
  CSRF protection server-side for cookie-authenticated mutations; HX headers are
  not authorization. Preserve labels, keyboard focus, and mobile layout. Reuse
  DaisyUI components/theme colors and complete Tailwind class names.
  Check `app/templates/base.html`: HTMX 1.9, Tailwind 4, DaisyUI 5 use CDNs; do not
  assume an npm build or copy incompatible version examples.
- **Privacy:** never commit/log secrets, tokens, raw bank messages, databases, or
  uploads. Use synthetic/redacted fixtures and enforce access rules server-side.

## Definition of done and documentation

- Add regression tests in `tests/test_*.py`, importing production code. Cover
  changed behavior, validation, denied access, and failures by risk, not token
  savings. Isolate DB/network; enable SQLite foreign keys for constraint tests.
- Run focused checks, then affected integrations; verify UI browser flows and
  responsive/error states. Review the diff and report checks/limitations.
  Docs-only edits need content, relative-link/anchor, referenced-path and size checks,
  not unrelated application tests.
- Update affected docs in the same change when behavior, setup, API, schema, or
  architecture changes. Follow the README task index and read only relevant sections.
  Keep one canonical explanation per topic; link to it elsewhere. Describe current
  behavior separately from intended rules and known limitations. Keep field lists
  in schemas/models, endpoint details in OpenAPI, and revision history in Alembic.
- No automatic summary files or duplicate folder trees. Keep this guide under
  6,000 characters (a project budget, not an official Codex limit). Add only durable,
  actionable rules; move detail to linked docs or scoped instructions when needed.
