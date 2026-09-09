# UI Normalization Backlog

This backlog records existing presentation differences from the
[UI Style Guide](../ui/STYLE_GUIDE.md). It is planning material, not an instruction to
change templates as part of the documentation delivery. Preserve feature behavior,
access control, CSRF protection, HTMX targets/swaps, and responsive behavior when
completing any item.

## Priority 1 — shared page structure

| Area | Current divergence | Target standard | Candidate paths |
|---|---|---|---|
| Transaction list | The shell uses `my-6 space-y-6`; its header uses an ungrouped title and a `/65` description. | Use the ordinary Dashboard shell and `space-y-2` Dashboard header with a `/70` description. | `app/templates/transactions/layout.html`, `app/templates/transactions/_browser.html` |
| Transaction create/edit | The back link and header use `space-y-5`. | Keep the compact form width, but use `space-y-3` between the back link and Dashboard-style header. | `app/templates/transactions/form.html` |
| Workspace selection | The compact shell has direct `p-4`, `space-y-6`, an ungrouped header, and direct-padded cards. | Use the ordinary shell/header unless the compact purpose remains justified; convert reusable cards to the standard `card-body` pattern. | `app/templates/workspaces.html` |
| Workspace detail | The entity title is smaller than the standard page title and the back-link/title gap is 8 px. | Retain a justified entity-management width, but use standard back-link spacing and header typography/description treatment. | `app/templates/workspace_detail.html` |
| Invitation states | Invitation pages are card-first and use individual heading patterns. | Retain compact invitation width, but use the guide's card, header, and control conventions where the page is an ordinary authenticated flow. | `app/templates/workspace_invitation.html`, `app/templates/workspace_invitation_unavailable.html` |

## Priority 2 — forms and small actions

| Area | Current divergence | Target standard | Candidate paths |
|---|---|---|---|
| Workspace creation | The form uses an unstyled label and lacks a standard field wrapper, hint/error placement, and `card-body`. | Adopt the transaction field pattern and standard content card without changing server-side validation behavior. | `app/templates/workspaces.html` |
| Workspace rename | A short one-field action occupies a persistent inline card. | Replace it with a modal form: standard label/control/error treatment, Cancel/Escape, focus transfer and restoration, and an in-dialog result. | `app/templates/workspace_detail.html`, associated workspace web route/HTMX handling |
| Invitation account form | Fields are nested in plain labels and do not consistently use the standard label, field wrapper, or validation layout. | Adopt the transaction control pattern while preserving invitation-token and authentication behavior. | `app/templates/workspace_invitation.html` |
| Member role and invitation forms | Compact inline controls use bespoke label/control composition. | Keep them inline only when their management context requires it; otherwise use a short modal for a focused mutation. All controls follow shared field rules. | `app/templates/workspace_detail.html` |

## Priority 3 — reusable feedback and surfaces

| Area | Current divergence | Target standard | Candidate paths |
|---|---|---|---|
| Workspace and invitation cards | Cards use `shadow` and direct `p-4`/`p-6`/`p-7` padding rather than the transaction-card baseline. | Use `card bg-base-100 shadow-sm` and `card-body`; reserve stronger shadow/gradient treatment for the authentication pattern. | Workspace and invitation templates |
| Feedback placement | Alerts are rendered in several local forms and positions. | Keep semantic DaisyUI variants and roles, but align reusable form feedback with the guide's alert, validation, and focus rules. | Workspace and invitation templates; shared alert macro where applicable |
| Empty and recovery pages | Transaction confirmation/error pages use compact specialized action cards. | Preserve them as intentional compact confirmation/recovery variants; align only shared controls, focus behavior, and typography when touched. | `app/templates/transactions/error.html`, `app/templates/transactions/confirmation.html` |

## Reference implementations and exceptions

- `app/templates/transactions/_form.html` is the reference for complex page-form
  controls, validation, grouped fields, and action rows.
- The `Move observation` dialog in `app/templates/transactions/_sources.html` is the
  reference for a short transactional modal, including modal structure, field
  hints/errors, action row, and focus behavior supplied by the transaction script.
- `app/templates/dashboard.html` is the reference for ordinary authenticated page width,
  header, description, and the primary-summary card variant.
- Login and registration are a shared authentication pattern, not a divergence: retain
  their two-column layout, elevated form card, and promotional gradient card.
- Preserve unique domain-specific views as exceptions until they are reused. Examples
  include transaction source-evidence cards, the current-month spending summary, and
  transaction detail data rows. Promote a component into the Style Guide before
  duplicating it on another page.

## Completion criteria

- Apply the documented target without changing feature behavior or security.
- Verify desktop and 360 px layouts, keyboard focus, validation, error, success, and
  loading states relevant to the changed action.
- Add or update focused regression coverage when markup, HTMX, or interaction behavior
  changes; run `git diff --check` and directly affected checks.
- Remove or update the completed row and keep the Style Guide canonical.
