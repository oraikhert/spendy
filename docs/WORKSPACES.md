# Workspaces

Workspaces are Spendy's ownership and authorization boundary. Every account, card,
transaction and source belongs to exactly one workspace, and users see that data only
through an active membership. A user may belong to several workspaces and has an
independent role in each one.

This document defines the database, service, JSON API and server-rendered UI contract.
For implementation scope and delivery order, see the
[Workspace development task](requirements/WORKSPACES_v1.md). General service and
migration rules remain in [Service contracts](SERVICE_LAYER.md) and
[Database migrations](MIGRATIONS.md).

- [Identity and data model](#identity-and-data-model)
- [Workspace context and isolation](#workspace-context-and-isolation)
- [Roles and membership](#roles-and-membership)
- [Registration and onboarding](#registration-and-onboarding)
- [JSON API](#json-api)
- [Invitations and email](#invitations-and-email)
- [Web interface](#web-interface)
- [Archive and permanent deletion](#archive-and-permanent-deletion)
- [Security and failure handling](#security-and-failure-handling)

## Identity and data model

Spendy has no global administrator or superuser. The user model contains no
`is_superuser` field, and no authenticated identity can bypass workspace membership.
Administrative authority comes only from the user's role in a particular workspace.

The workspace domain contains these records:

| Record | Purpose and important fields |
|---|---|
| `Workspace` | Stable ID, trimmed display name of 1–100 characters, active/archived status, creator, archive timestamp and ordinary timestamps. Names are not globally unique. |
| `WorkspaceMember` | Unique `(workspace_id, user_id)` membership, role, joining time and ordinary timestamps. |
| `WorkspaceInvitation` | Workspace, normalized recipient email, invited role, token hash, expiry, inviter, delivery state and accepted/revoked timestamps. Raw tokens are never persisted. |

The role values are `owner`, `editor` and `viewer`. Workspace and membership records
do not replace the existing active-user check: an inactive user cannot authenticate or
use any membership.

Every tenant-owned database record stores a non-null `workspace_id`: accounts, cards,
transactions, source payloads, transaction observations, bank-statement details and
transaction-source links. Child records inherit the workspace of their parent, and
same-workspace foreign keys prevent a card from referencing an account in another
workspace, an observation from referencing foreign account/card hints, or a link from
joining a foreign observation to a transaction. Integer record IDs remain globally
unique and retain their existing URL shapes.

Payload idempotency is unique within `(workspace_id, ingestion_method,
idempotency_key)`. Content-hash duplicate detection, matching candidates,
canonicalization, dashboard aggregation and reference selectors operate only inside
the same workspace. Two workspaces may independently ingest the same message, use the
same idempotency key, or contain otherwise identical transactions.

## Workspace context and isolation

Every financial service operation receives an explicit immutable context containing
the current user, workspace and membership role. Routes resolve this context; services
do not infer it from global state. Creation services assign `workspace_id` from the
context and never accept it from ordinary account, card, transaction or source input.

All record lookup, list, count, update, delete, matching, linking, reprocessing and
summary queries include the current workspace. References supplied by a client are
validated in that workspace before use. An ID that exists only in another workspace
is indistinguishable from a missing ID and produces `404 Not Found`. A valid member
without the required role receives `403 Forbidden`.

JSON financial endpoints accept an optional `X-Workspace-ID` request header:

| Available active memberships | Header behavior |
|---|---|
| None | Financial endpoints return `409 Workspace required`. |
| One | An omitted header selects that workspace; a supplied header must select that membership. |
| More than one | An omitted header returns `409 Workspace selection required`; a valid supplied header selects its workspace. |

Malformed, unknown, archived and non-member workspace selections never fall back to a
different workspace. Workspace-management endpoints identify their target in the URL
and do not require `X-Workspace-ID`, but still require membership and the appropriate
role. Health, authentication, transaction-kind metadata and exchange-rate lookup do
not use workspace context.

The web interface keeps the selected workspace as a signed claim in the existing
authentication cookie. Selection is revalidated against current membership on every
request. Switching reissues the cookie with the same login-bound session ID, so the
existing inactivity timeout and CSRF identity remain valid. An invalid or removed
selection returns the user to workspace selection and never silently exposes another
workspace.

## Roles and membership

Permissions are deliberately small and workspace-local:

| Capability | Owner | Editor | Viewer |
|---|:---:|:---:|:---:|
| Read workspace financial data | Yes | Yes | Yes |
| Create, edit and delete financial data | Yes | Yes | No |
| Upload/reprocess sources and manage observation links | Yes | Yes | No |
| View the workspace member list | Yes | Yes | Yes |
| Rename the workspace | Yes | No | No |
| Invite, resend or revoke invitations | Yes | No | No |
| Change roles or remove members | Yes | No | No |
| Archive, restore or permanently delete | Yes | No | No |

An owner may promote an existing editor or viewer to owner. Invitations may grant only
`editor` or `viewer`; owner promotion is a separate authenticated action after the
recipient joins. The final owner cannot be demoted, removed or leave. These checks and
their write occur in one transaction and are protected against concurrent owner
changes. Any member may leave when doing so does not remove the final owner.

Archiving does not remove memberships. Archived workspaces remain visible to their
members in workspace management, but cannot become the financial request context.

## Registration and onboarding

Normal API registration, web registration and `scripts/create_user.py` create only a
user. They do not create a workspace or membership. An authenticated user with no
active workspace membership can access authentication, invitation and workspace
onboarding routes, but financial JSON endpoints return `409 Workspace required` and
financial web routes redirect to onboarding.

Onboarding offers two paths: create a new workspace explicitly, or open an invitation
received by email. Any active user may create any number of workspaces. The creator
becomes its owner in the same transaction, and web creation immediately selects it.

Registration through a valid invitation is available even when public registration is
disabled. It fixes the account email to the invited address, creates the user and
target membership atomically, and does not create a personal workspace. A registered
recipient signs in before accepting; an authenticated user whose email does not match
the invitation cannot accept it.

The ownership migration assigns all pre-workspace financial records to one `Legacy
Workspace`. The existing user with the smallest ID becomes its owner and every other
existing user becomes an editor. Inactive users keep their membership but remain unable
to authenticate. If retained financial data exists without any user, the migration
creates an ownerless Legacy Workspace; an operator must use the dedicated membership
assignment script to add an owner before that data is accessible. No Legacy Workspace
is created for an empty installation.

## JSON API

Workspace responses expose the workspace ID, name, status, current user's role and
timestamps. Financial create/update schemas do not expose writable workspace fields.
User responses do not contain `is_superuser`.

### Workspace lifecycle

| Method and path | Behavior |
|---|---|
| `GET /api/v1/workspaces` | List every active and archived membership for the current user. |
| `POST /api/v1/workspaces` | Create a workspace and owner membership explicitly. |
| `GET /api/v1/workspaces/{workspace_id}` | Read workspace details as a member. |
| `PATCH /api/v1/workspaces/{workspace_id}` | Rename an active workspace as owner. |
| `POST /api/v1/workspaces/{workspace_id}/archive` | Archive an active workspace as owner. |
| `POST /api/v1/workspaces/{workspace_id}/restore` | Restore an archived workspace as owner. |
| `DELETE /api/v1/workspaces/{workspace_id}` | Permanently delete an archived workspace after exact-name confirmation. |

Create and rename accept a trimmed `name` of 1–100 characters. Permanent deletion
accepts `confirmation_name`; it must exactly equal the stored workspace name after
form transport, including case. The path ID distinguishes workspaces with equal names.

### Memberships

| Method and path | Behavior |
|---|---|
| `GET /api/v1/workspaces/{workspace_id}/members` | List members for any member. |
| `PATCH /api/v1/workspaces/{workspace_id}/members/{user_id}` | Change a member's role as owner. |
| `DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}` | Remove a member as owner. |
| `POST /api/v1/workspaces/{workspace_id}/leave` | Leave the workspace subject to the final-owner rule. |

Removing a membership immediately invalidates that user's selected web workspace and
future JSON requests for it. It does not delete the user's global identity or any
workspace data.

### Invitations

| Method and path | Behavior |
|---|---|
| `GET /api/v1/workspaces/{workspace_id}/invitations` | List invitation state as owner. |
| `POST /api/v1/workspaces/{workspace_id}/invitations` | Create and send an editor/viewer invitation. |
| `POST /api/v1/workspaces/{workspace_id}/invitations/{invitation_id}/resend` | Rotate the token and retry delivery. |
| `DELETE /api/v1/workspaces/{workspace_id}/invitations/{invitation_id}` | Revoke a pending invitation. |
| `GET /api/v1/workspace-invitations/{token}` | Read a safe invitation summary needed for login or registration. |
| `POST /api/v1/workspace-invitations/{token}/accept` | Accept as the authenticated matching user. |
| `POST /api/v1/workspace-invitations/{token}/register` | Register the invited email and accept atomically. |

Invitation registration returns the same public user representation as normal
registration; API clients then log in normally. Acceptance returns the created
membership. The public summary exposes only the workspace name, proposed role, masked
recipient email and expiry, and all invitation responses use private, no-store caching.

## Invitations and email

Invitation email uses an async SMTP client. Configuration supplies the host, port,
optional username/password, sender address, STARTTLS policy, public application base
URL, network timeout and invite lifetime. The default lifetime is seven days. Secrets
are loaded through settings and are never returned or logged.

A newly created invitation is committed before delivery and records `pending`, `sent`
or `failed` delivery state. A safe delivery failure is returned to the owner while the
failed invitation remains available for retry. Resend creates a new random token,
stores its hash and invalidates the earlier link before sending. Only one unexpired,
unrevoked invitation for the same normalized email and workspace may remain actionable.

Token lookup compares hashes in constant time. Acceptance locks and revalidates the
invitation, normalized email, workspace state and existing membership, then creates the
membership and marks the invitation accepted in one transaction. Expired, revoked,
accepted and superseded links cannot be replayed. Email messages contain no financial
data or member list.

## Web interface

The authenticated navigation identifies the selected workspace and offers a keyboard-
accessible selector when the user has more than one active membership. Archived
workspaces appear only in workspace management. Selecting a workspace is a CSRF-
protected POST; successful selection returns to a validated local destination or the
Dashboard.

The workspace interface provides:

- an onboarding page for users without a membership;
- workspace list, create and rename forms;
- member list, role changes, removal and leave actions;
- invitation creation, delivery status, resend and revoke controls;
- archive and restore confirmations; and
- a separate permanent-deletion confirmation requiring the exact workspace name.

Invitation links open a no-store landing page. Existing users are directed through
login and returned to the invitation. New recipients use a registration form whose
email is fixed from the token. Web registration signs the user in, accepts the
invitation and selects the target workspace without creating another workspace.

Viewer pages omit financial mutation controls, but authorization never relies on
hidden UI. All workspace forms work as ordinary POSTs; HTMX may enhance targeted
updates without becoming required. Forms preserve validation input, announce status
and errors, restore useful keyboard focus and remain usable without horizontal page
scrolling at 360 px.

## Archive and permanent deletion

Archive is reversible and does not remove data. It invalidates active selections,
blocks financial reads and writes for that workspace with `409 Workspace archived`,
and disables new invitations and membership changes other than the owner's restore or
permanent-delete operation.

Permanent deletion is irreversible and has no recovery window. It is allowed only
when all of the following remain true at commit time:

- the caller is an owner of the target workspace;
- the workspace is archived;
- `confirmation_name` exactly matches the stored name; and
- the request still refers to the current workspace state rather than a stale form.

The deletion service locks the workspace, resolves every private upload path inside the
configured upload directory, and moves those files to an operation-specific quarantine
before deleting database records. Database deletion removes all workspace memberships,
invitations, accounts, cards, transactions, payloads, observations, statement details
and links in one transaction. A database failure rolls back and restores staged files.
After commit, quarantined files are unlinked. A cleanup failure cannot restore deleted
database data; it leaves only inaccessible quarantined files and records a safe
operator-facing diagnostic without exposing paths or financial metadata to the client.

## Security and failure handling

Workspace checks happen in route dependencies and services; database constraints are a
last line of defense against inconsistent relationships. Role checks are repeated at
the mutation boundary, including HTMX and ordinary form fallbacks. Cookie-authenticated
workspace mutations require the existing login-bound CSRF protection and reject an
explicit foreign `Origin`.

Authenticated workspace and financial responses use `Cache-Control: private,
no-store`; HTMX history does not persist them. Invitation pages additionally prevent
referrer leakage. Logs may contain internal workspace, user and invitation IDs, but
never raw invitation tokens, SMTP credentials, source contents, private file paths or
unredacted delivery-provider errors.

Expected concurrency and integrity conflicts are translated into stable `403`, `404`
or `409` responses. SMTP and filesystem failures use safe messages and preserve the
documented retry or compensation behavior. All money, timezone, matching,
canonicalization and source-preservation contracts remain unchanged inside the selected
workspace.
