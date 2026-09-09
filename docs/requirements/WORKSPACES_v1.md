# Workspaces — development task v1

Iteration: **v1** · Status: **Completed — all three iterations** · Baseline: **2026-09-08**

Implement the [Workspace contract](../WORKSPACES.md) in three independently
acceptable delivery stages. That document defines the target behavior; this task
records the current baseline, implementation boundaries, intermediate results and
minimal acceptance gates. Follow the [task versioning convention](../../README.md#documentation).

## Baseline

The baseline revision is `5679f3054444aa9483696c208ca7de173e45594c`.

| Area | Available | Required work |
|---|---|---|
| Identity | Active users, bearer/cookie authentication and a global privilege flag with no authorization use | Remove the global privilege flag; make authority workspace-specific |
| Access | Every authenticated active user can reach the same accounts, cards, transactions and sources | Add mandatory workspace context and isolate every financial operation |
| Registration | API, web and CLI user creation create a global user | Keep user-only creation and add explicit workspace onboarding |
| Database | Financial tables have global IDs and cross-record foreign keys but no ownership key | Add workspace tables, tenant keys, same-workspace constraints and a legacy-data backfill |
| API | Financial URLs are stable and ignore the authenticated user after the active-user check | Resolve `X-Workspace-ID`, preserve URLs and apply scoped services |
| Web | Login goes directly to the shared Dashboard; the navbar has no workspace selector | Add onboarding, selection and workspace management |
| Email | No SMTP settings, client or background worker | Add bounded async SMTP delivery for invitations without introducing a worker |
| Lifecycle | Accounts/cards/transactions use hard deletion; no aggregate archive/delete workflow exists | Add reversible workspace archive and guarded aggregate deletion |

At the baseline revision, the current-user route parameter did not imply ownership:
services omitted it from their queries. Source payloads also require direct ownership
because they may exist without an account, card, observation or transaction.

## Iteration 1 — ownership foundation

### Work

- Add `Workspace` and `WorkspaceMember`, the three workspace-local roles, relationships
  and response/input schemas. Add a dedicated context dependency for bearer and cookie
  routes. There is no global administrator or membership bypass.
- Add a migration that drops the legacy global privilege column without rewriting the deployed
  initial revision. Add `workspace_id` to every tenant-owned financial table, backfill
  retained records into one Legacy Workspace, then enforce non-null and same-workspace
  relationships. The lowest existing user ID is owner; other users are editors.
- Handle the retained-data/no-user case by creating an ownerless Legacy Workspace and
  adding an explicit membership-assignment administration script. Do not silently let
  the first public registrant claim retained data. Add a guarded downgrade that aborts
  when multiple workspace scopes cannot safely collapse.
- Scope account, card, transaction, source payload, observation, link, matching,
  canonicalization, reference and dashboard services. Scope payload idempotency and
  duplicate detection. Make every create derive workspace from context and every
  cross-workspace ID look absent.
- Add `X-Workspace-ID` resolution to existing JSON financial routes. Return `409` for
  no membership or ambiguous omitted selection and preserve current endpoint URLs,
  pagination, response shapes, money rules and HTTP authentication behavior.
- Remove the global privilege flag from ORM models, Pydantic schemas, responses, exports, scripts
  and documentation. Normal API/web registration and `scripts/create_user.py` continue
  to create only a user and never create or select a workspace.
- Add workspace list/create/read endpoints and minimal web onboarding, creation and
  selection. Users without membership can reach these routes but are redirected from
  financial pages. Creating through the web makes the creator owner and selects the
  new workspace in the signed session.

### Intermediate result

Every financial operation is tenant-isolated. A new user can authenticate, explicitly
create a workspace and then use the existing application. Multi-workspace records and
roles exist, but invitation and member-management workflows are not yet exposed.

### Minimal acceptance gate

- Verify registration and manual creation produce no workspace, onboarding can create
  one, and the creator becomes owner.
- With two users and two workspaces, cover one representative list, detail, mutation,
  dashboard and source operation; neither direct IDs nor filters expose foreign data.
- Cover the zero/one/multiple membership header outcomes and a cross-workspace source
  link attempt.
- Upgrade a disposable SQLite database containing legacy users and financial records;
  verify the first-user owner rule, removal of the global privilege flag, backfill and foreign-key
  enforcement. Exercise the guarded downgrade on a safe single-workspace fixture.
- Run the directly affected transaction, source-processing, dashboard and auth scripts
  with isolated databases. PostgreSQL migration execution may remain unverified but
  generated constraints and SQL must be reviewed and reported.

### Known limitations after iteration 1

Users cannot invite or manage collaborators. Additional workspaces can be created and
selected by their creator, but membership roles cannot yet be changed through the API
or UI. Workspace archive and deletion are unavailable.

### Completion record

Completed **2026-09-08**, against the Workspace contract at Git revision
`4c4b3a9ca8ce214bd1555f53c49be1da12ca98a6` (this change removes the obsolete
privilege-field name from that document without changing its target semantics).
Migration: `workspace_ownership_001`, following `txn_summary_excl_001`.

Implemented the seven-table ownership boundary, immutable service context, local
roles with server-side write checks, explicit workspace JSON/web creation and
selection, and the operator-only ownerless Legacy Workspace recovery script.
API, web and CLI registration remain user-only. Existing financial URLs and public
response shapes are preserved; unavailable reference IDs now consistently return
404. Account/card inputs reject ownership fields, matching existing strict
transaction/source inputs.

Verification on disposable SQLite with foreign keys enabled:

- `tests/test_workspaces.py`: registration through all three entry points,
  atomic creation/rollback, zero/one/multiple membership resolution, invalid and
  archived selections, workspace reads, cross-workspace financial/reference/source
  isolation, independent idempotency, viewer denial, unscoped metadata, immutable
  context, signed-session selection and explicit Legacy owner recovery.
- `tests/test_workspace_migration.py`: empty, users-only, retained-data/users and
  ownerless backfills; minimum-ID ownership; removed privilege column; non-null,
  role, membership and same-workspace constraints; guarded downgrade and retained
  SQLite observation AUTOINCREMENT high-water marks.
- Affected regressions: `tests/test_transaction_service.py`,
  `tests/test_source_processing.py`, `tests/test_transactions_web.py` (including
  authentication, CSRF and sliding sessions), `tests/test_dashboard_service.py`,
  `tests/test_dashboard_api.py`, `tests/test_dashboard_web.py`, and
  `tests/test_source_migration.py`. Existing financial fixtures now explicitly
  create a synthetic workspace and memberships. The dashboard HTML check was
  corrected to match the existing lowercase “in turnover” label.
- `tests/test_api.py`: authentication checks passed on a separate disposable
  server at port 8137; port 8000 was already occupied and was left untouched.
- Browser: actual registration → onboarding, blank-name validation with focus,
  explicit creation → Dashboard, second-workspace creation and switching back.
  Desktop and 360 × 800 layouts checked; mobile document width was 360 px with no
  horizontal overflow. The temporary viewport override was reset.
- Parser regressions: `tests/test_parsing.py` and
  `tests/test_parsing_kind_location.py` passed after the matching-helper import changes.
- `git diff --check` and `alembic check` (no ORM/schema drift); full diff and
  PostgreSQL schema SQL/constraints reviewed.
  PostgreSQL migration execution remains untested; no retained database was migrated.

Remaining limitations are the iteration boundary above: no invitations, membership
management, rename/archive/restore/delete workflows, or collaborator onboarding.
Viewer mutation controls are still presented by existing financial templates;
services deny those writes, with role-aware presentation deferred to Iteration 2.
The existing account/card list services retain their unbounded response contract;
workspace lists are bounded and ordered. No blockers remain for Iteration 1.
This Iteration 1 record remains historical; Iterations 2 and 3 are now also complete.

## Iteration 2 — collaboration

### Work

- Enforce the owner/editor/viewer permission matrix in services and both route layers.
  Add member listing, role change, removal and leave operations. Lock membership state
  so concurrent requests cannot demote, remove or leave the final owner.
- Add invitation persistence with normalized email, hashed token, invited role,
  expiration, inviter, acceptance/revocation state and delivery status. Permit only
  editor/viewer invitations; owner promotion uses membership role change.
- Add async SMTP settings and a compatible declared dependency after checking the
  current stack. Commit invitation state before delivery, retain safe failed state,
  rotate tokens on resend and keep network I/O bounded by a timeout.
- Add owner-only invitation list/create/resend/revoke endpoints plus safe public token
  inspection, authenticated acceptance and invite-only registration. Invite
  registration bypasses disabled public registration, fixes the recipient email,
  creates membership atomically and creates no personal workspace.
- Complete multi-workspace switching in the navbar and signed web session. Add member
  and invitation pages, login return-to-invitation behavior, role-aware controls and
  ordinary form fallbacks. Extend shared CSRF/origin/no-store helpers instead of
  leaving workspace protection inside transaction-specific code.

### Intermediate result

Owners can collaborate through email invitations. Editors can mutate only financial
data, viewers remain read-only, and members can switch between fully isolated
workspaces through API and web interfaces.

### Minimal acceptance gate

- Exercise one representative financial read/write for each role and all final-owner
  protections; do not repeat the permission matrix for every financial endpoint.
- With mocked SMTP, cover successful delivery, retained failure, token rotation,
  expiration/revocation/replay and email mismatch.
- Verify existing-user acceptance and invite-only registration while public
  registration is disabled. Confirm neither path creates another workspace.
- Verify switching changes Dashboard and transaction results, a removed member loses
  access immediately, workspace forms require CSRF, and foreign `Origin` is rejected.
- Run the focused workspace API/web checks and the affected auth/session regressions;
  no live SMTP or external network check is required.

### Known limitations after iteration 2

Workspaces cannot be archived or deleted. Invitation delivery is request-driven and
has no background worker, automatic retry schedule or provider-specific delivery
telemetry.

### Completion record

Completed **2026-09-09**, against the Workspace contract at Git revision
`7907e54d4ae428880000c0dd336b0c8d59f3bf39`. Migration:
`workspace_collaboration_002`, following `workspace_ownership_001`.

Implemented the owner/editor/viewer financial role matrix in services and both route
layers; owner-only rename, membership and invitation administration; member leave;
and serialized final-owner protection. Added request-driven invitation creation,
safe inspection, acceptance and invite-only registration. Only SHA-256 token hashes
are persisted. Creation/resend commits the pending token before delivery; delivery
records `sent` or retained `failed`, and resend rotates the token. Workspace switching
retains the signed session ID and refreshes the complete scoped dataset. Shared
session-bound CSRF, same-origin and private/no-store helpers now cover transaction,
workspace and invitation forms; all collaboration forms have ordinary POST behavior.

Declared `aiosmtplib>=5.1.2,<6.0.0` without changing other dependency constraints;
5.1.3 was used locally. Added `SMTP_HOST`, `SMTP_PORT`, optional
`SMTP_USERNAME`/`SMTP_PASSWORD`, `SMTP_SENDER`, `SMTP_STARTTLS`,
`PUBLIC_BASE_URL`, bounded `SMTP_TIMEOUT_SECONDS`, and bounded
`WORKSPACE_INVITATION_LIFETIME_DAYS` (seven days by default).

Verification used disposable SQLite databases, synthetic users and mocked SMTP:

- `tests/test_workspaces.py`: representative financial read/write behavior for all
  roles; owner-only administration; all final-owner cases including concurrent
  demotion; normalization/one-actionable constraint; send success, retained failure,
  resend rotation, expiry, revocation, replay and email mismatch; existing-user
  acceptance and invite registration with public registration disabled.
- `tests/test_workspaces_web.py`: selected-workspace dataset replacement with stable
  session ID, role-aware controls, immediate removal, invitation landing/login return
  and acceptance, invite registration while public registration is disabled, CSRF
  rejection, and explicit foreign-Origin rejection.
- `tests/test_workspace_migration.py`: invitation schema constraints plus reversible
  SQLite upgrade/downgrade. Focused and affected auth/session, transaction, dashboard
  and workspace-isolation regressions passed as listed in the implementation handoff.
- Browser checks covered the collaboration/onboarding pages at desktop and 360 × 800,
  including keyboard-reachable controls and no horizontal document overflow. Actual
  Chrome selection of both local workspaces redirected to the Dashboard, updated the
  selected-workspace navigation and showed different scoped financial totals.
- `git diff --check`, Python compilation and `alembic check` passed; the complete
  implementation and migration diff was reviewed.

No real SMTP server, provider account, external network, personal email/database or
PostgreSQL migration execution was used. Consequently provider authentication,
STARTTLS/certificate behavior, outbound firewall/DNS, throttling, reputation and
production PostgreSQL execution remain untested. Delivery remains synchronous to the
request with bounded timeout and manual resend only; there is no worker, schedule or
provider telemetry. Workspace archive, restore and permanent deletion remain Iteration
3. No blockers remain for Iteration 2. This Iteration 2 record remains historical;
Iteration 3 is now complete.

## Iteration 3 — lifecycle and hardening

### Work

- Add owner-only archive and restore. Archived workspaces remain listed in management
  but are invalid financial contexts and cannot accept invitations or member changes.
  Invalidate an archived selection without silently choosing another workspace.
- Add permanent deletion only for archived workspaces. Require exact, case-sensitive
  workspace-name confirmation in JSON and web forms; do not require a password. Lock
  and revalidate archived state, ownership and confirmation at commit time.
- Coordinate deletion of all workspace database records and private uploads. Resolve
  paths inside `UPLOAD_DIR`, stage files in an operation-specific quarantine, restore
  them on database rollback, and unlink them after commit. Report post-commit cleanup
  failure safely without implying that deleted database data can be recovered.
- Complete archive/restore/delete UI states, stale confirmation handling, HTMX and
  ordinary form behavior, accessible focus/status messages, private no-store caching
  and 360 px layout. Update the README current-feature summary, Architecture access
  model, Service contracts, migration instructions, deployment SMTP settings and
  troubleshooting only when the corresponding behavior is delivered.

### Final result

The complete [Workspace contract](../WORKSPACES.md) is available through JSON API and
the server-rendered UI. An archived workspace can be restored or deliberately and
irreversibly deleted; an active workspace cannot be deleted.

### Minimal acceptance gate

- Cover active-delete rejection, owner-only archive/restore, exact-name mismatch and
  one successful deletion containing accounts, transactions, a source graph and one
  synthetic private upload.
- Inject one pre-commit database failure and verify staged files return; inject one
  post-commit cleanup failure and verify the workspace remains deleted while a safe
  diagnostic is produced.
- Browser-check onboarding/selection and owner management at 360 px and one desktop
  width, including keyboard focus, viewer controls, archive/restore and both cancelled
  and confirmed deletion.
- Run focused workspace modules, directly affected financial regressions and
  `git diff --check`. Do not require parser-only scripts, unrelated full API checks,
  real email delivery or personal data.

### Known limitations after iteration 3

Permanent deletion has no recovery window. SMTP delivery has no background queue.
Categories, budgets, audit logs, SSO and provider-specific email integrations remain
future work.

### Completion record

Completed **2026-09-09** against the final Workspace contract at Git revision
`7907e54d4ae428880000c0dd336b0c8d59f3bf39`. No schema change was required, so
`workspace_collaboration_002` remains the migration head.

Implemented owner-only archive and restore; archived-selection invalidation without
fallback; archived management state; financial, membership and invitation blocking;
and exact-name permanent deletion. Deletion locks and revalidates ownership, state and
confirmation, stages every private payload file inside an opaque per-operation
`UPLOAD_DIR` quarantine, deletes the complete tenant graph in one transaction,
restores files after rollback, and safely logs only IDs/counts if post-commit cleanup
fails. The web UI has role-aware lifecycle controls, separate confirmations, ordinary
POST and HTMX redirects, private/no-store responses, status announcements and dialog
focus restoration.

Verification used disposable SQLite databases with foreign keys enabled and synthetic
users, financial records, source data and private files:

- `tests/test_workspaces.py` covered owner-only archive/restore, active deletion,
  exact case-sensitive confirmation, archived financial/collaboration blocking, full
  graph deletion, strict upload-root containment and private file cleanup. An injected
  commit failure restored the staged file and retained the workspace. An injected
  post-commit unlink failure left the workspace deleted and produced a path-free
  operator diagnostic.
- `tests/test_workspaces_web.py` covered role presentation, archive selection clearing,
  archived management, confirmation/cancel markup, stale archive/restore submissions,
  exact-name errors, confirmed deletion, CSRF/origin rejection and HTMX redirects.
- `tests/test_workspace_migration.py` passed; `alembic check` reported no model/schema
  drift and confirmed that no Iteration 3 revision is needed.
- Affected transaction, source-processing, dashboard, authentication, CSRF and sliding
  web-session regression scripts passed. Python compilation, documentation link/path
  checks, `git diff --check` and complete diff review also passed.

Browser checks used the isolated synthetic SQLite environment at a desktop viewport
and at 360 × 800. Workspace management, the archived state and the mobile dashboard
had no horizontal overflow. Keyboard activation moved focus into the archive, restore
and permanent-delete dialogs; Escape/cancel returned focus to the invoking control.
The archive and restore flows completed through ordinary browser POSTs, archived
workspaces stayed out of the selector, and archiving the selected workspace redirected
subsequent dashboard access to workspace management without selecting another tenant.
PostgreSQL migration/runtime execution, real SMTP and provider/network behavior remain
untested. No dependencies or configuration keys changed in Iteration 3; the existing
SMTP settings and `UPLOAD_DIR` contract are now documented for lifecycle operations.
Permanent deletion has no recovery window, and SMTP remains request-driven with manual
resend. No implementation blockers remain.

## Implementation constraints

- Use FastAPI, async SQLAlchemy 2, Pydantic 2, Alembic, Jinja2 and the existing
  HTMX/Tailwind/DaisyUI versions. Do not add a SPA, npm build, background worker or
  unrelated dependency upgrade.
- Keep routes responsible for authentication, workspace-context resolution and HTTP
  mapping; keep ownership, role, invitation and deletion rules in services. Make
  multi-write workflows atomic and translate integrity races into stable errors.
- Use one `AsyncSession` per request/task. Use async SMTP and existing asynchronous
  file-offloading patterns so network, filesystem and heavy work do not block the event
  loop. Never combine database and filesystem behavior without documented compensation.
- Preserve Decimal money behavior, timezone/date boundaries, matching rules, source
  canonicalization priorities and private-file restrictions inside each workspace.
- Never log raw invitation tokens, credentials, financial source content or private
  paths. Use synthetic fixtures and enable SQLite foreign keys for focused tests.

## Focused verification set

Keep new coverage intentionally compact:

- `tests/test_workspaces.py` covers user-only registration, context selection,
  isolation, representative role behavior, last-owner protection, mocked invitations
  and archive/delete rules.
- `tests/test_workspace_migration.py` covers the global privilege flag removal, legacy backfill,
  first-user ownership, tenant constraints and guarded SQLite downgrade.
- `tests/test_workspaces_web.py` covers onboarding, creation, switching, invite
  acceptance, viewer restrictions, CSRF, archive and exact-name deletion.

Each rule needs one representative scenario rather than repetition across every route.
Use disposable SQLite databases, mocked SMTP, synthetic source data and a synthetic
private file. Run only affected existing transaction, source-processing, dashboard,
auth and session scripts. Report PostgreSQL, real SMTP and browser limitations rather
than expanding the acceptance suite.
