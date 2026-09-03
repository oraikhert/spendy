# Transactions UI — development task v1

Iteration: **v1** · Status: **Ready for implementation** · Baseline: **2026-09-03**

Implement the [Transactions UI](../ui/TRANSACTIONS.md): the transaction list,
detail page, create/edit form, source viewing/downloads, unlink and transaction
deletion. That document defines the target behavior; this task defines delivery
work. Follow the [task versioning convention](../../README.md#documentation).

## Baseline

| Area | Available | Required work |
|---|---|---|
| Web | Login, registration and dashboard | Transaction routes, navigation, forms and partials |
| Transactions | [CRUD and source retrieval](../../app/services/transaction_service.py) | Related card/account data, source counts and server validation |
| Filtering | Account, card, inclusive dates, description, type and signed amount bounds | Currency, direction, absolute amount bounds, literal search wildcards and consistent ordering |
| Sources | [Read, download and unlink](../../app/api/v1/source_events.py) | Cookie-authenticated download, paginated source view and unlink controls |
| Access | Active-user authentication; shared dataset | CSRF validation for new cookie mutations and protected fragments/files |

Use the existing [models](../../app/models/) and [input schemas](../../app/schemas/).
`TransactionUpdate` does not support changing cards. `SourceEvent` has no
`parsed_original_amount` or `parsed_original_currency`. A primary-link update
schema exists without an implemented route. These are not additional UI features.
See [Service contracts](../SERVICE_LAYER.md) for existing write boundaries,
matching behavior and file/reprocessing limitations.

## Work

### 1. Screens and navigation

- Build the documented [list](../ui/TRANSACTIONS.md#transaction-list),
  [details](../ui/TRANSACTIONS.md#transaction-details),
  [form](../ui/TRANSACTIONS.md#create-and-edit) and
  [sources](../ui/TRANSACTIONS.md#sources). Reuse the shared layout and macros.
- Add HTML routes `/transactions`, `/transactions/new`, `/transactions/{id}`
  and `/transactions/{id}/edit`; register `new` before the dynamic route.
  Add Transactions to navigation and connect the dashboard's Add transaction action.
- Keep filters/page in the URL. Use separate results and source partials; full
  GET requests render complete pages. Restore controls and results on Back/Forward.
  Accept return URLs only for the local transaction list and its allowed parameters.
- Forms support ordinary GET/POST. HTMX enhances filtering, pagination and source
  updates. Handle HTML validation errors with 422 explicitly in HTMX 1.9;
  use 303 after ordinary successful POST and HX-Redirect for HTMX navigation/login.
  Preserve focus, input and the documented [states](../ui/TRANSACTIONS.md#states).

### 2. Queries and validation

- Apply all filters before counting and pagination. Extend shared service filters
  for currency, direction and absolute amount bounds; preserve the existing signed
  JSON `min_amount`/`max_amount` semantics using separate absolute-bound parameters.
  Reject invalid account/card combinations, ranges and currency-dependent filters.
- Use `coalesce(posting_datetime, transaction_datetime) DESC NULLS LAST, id DESC`.
  This deliberately changes the shared service/API ordering. Preserve inclusive
  API date bounds; convert UI calendar dates to full-day bounds on the server.
  Do not add a creation-date fallback or change timezone/matching semantics.
- Load relationships explicitly; aggregate counts without N+1 queries. Bound and
  order result, source and reference lists; make every selector option reachable.
- Implement the form's validation in input schemas/services: required values,
  trimmed nonempty descriptions, normalized three-letter currencies, location
  length and consistent changed FX groups. Reject `null` for required fields and
  attempts to change an existing transaction's card.
- Use finite Decimal values fitting SQL `Numeric(15,2)` for amounts and
  `Numeric(15,6)` for rates. Reject excess precision/overflow without silent rounding.
  Keep zero valid and sign independent of type; never calculate money with float.
- Distinguish omitted values from explicit clearing. Preserve unchanged date
  seconds, microseconds and timezone offsets, incomplete legacy FX groups and
  `fx_fee`; validate a legacy FX group when it is changed. No FX fetching,
  matching, source creation or source-field rewriting during direct CRUD.

### 3. Sources, mutations and access

- Order sources by `created_at DESC, id DESC`, paginate, render known/unknown states and
  escape raw text/errors. Present transaction FX values separately from extracted
  source amounts. Hide technical hashes, paths and matching metadata.
- Add a cookie-authenticated download handler using source ID; the existing JSON
  download expects a Bearer token. Restrict resolved paths to the upload directory.
- Implement confirmed unlink/delete with the preservation rules in the UI document.
  Handle missing records/links and refresh counts/page positions after success.
  Block duplicate submissions; never automatically replay an uncertain write.
- Require an active user for pages, fragments, downloads and mutations. Validate
  CSRF tokens server-side for every new cookie mutation. Keep the current
  [shared access model](../ARCHITECTURE.md#access-model); do not invent ownership.
  Exclude bank data from shared caches and HTMX/localStorage history persistence.

## Constraints

Use FastAPI, async SQLAlchemy 2, Pydantic 2 and Jinja2 with the existing
[frontend](../../app/templates/base.html): HTMX 1.9.10, Tailwind 4 and DaisyUI 5
via CDN. Follow [project rules](../../AGENTS.md); no stack upgrade, SPA or npm build.
Web handlers call services directly. Reuse explicit transaction boundaries;
schema changes, if needed, require [Alembic migrations](../MIGRATIONS.md#changing-the-schema).

Outside v1: import, account/card management, linking new sources, reprocessing,
primary-source selection, fee editing, automatic FX, bulk actions, reports,
categories, reconciliation status and family ownership. Do not add placeholder controls.

## Acceptance

- List/filter tests cover signed and zero amounts, multiple currencies, absolute
  ranges, literal `%`/`_`, date boundaries, undated records, matching totals and
  stable pagination with more than 50 records.
- CRUD tests cover invalid input/card changes, numeric precision/overflow,
  nullable-field clearing, unchanged dates/FX, and absence of ingestion/FX side effects.
- Source tests cover all parse states, escaped content, missing files, more than
  20 links, and unlink/delete preserving files, sources and other transaction links.
- Access tests cover unauthenticated/inactive users, missing/invalid CSRF, expired
  HTMX sessions, invalid IDs, download traversal and external return URLs.
- Browser checks at 360, 768 and 1280 px cover keyboard/focus, dialogs, ordinary
  and HTMX navigation, history, empty/error states, unsaved changes and failed writes.
- Add executable `tests/test_*.py` regression checks using production code and
  isolated DB/network fixtures; enable SQLite foreign keys. Run focused tests,
  affected integrations and [repository checks](../../README.md#development-checks).
  Report untested backends/scenarios; do not assume pytest is configured.
- Update README feature availability and affected service/access contracts.
  Keep the UI document current without delivery notes. Mark this task Completed
  only after acceptance; record checks, limitations and the UI document's Git revision.
