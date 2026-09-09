# UI Style Guide

This is the canonical visual standard for new and updated Spendy pages. Feature UI
documents define feature behavior; this guide defines reusable presentation patterns.
Examples use the Tailwind CSS 4 and DaisyUI 5 utilities already loaded by
[`base.html`](../../app/templates/base.html).

## Foundations

Use DaisyUI semantic tokens, never hard-coded colors: `base-100` for raised surfaces,
`base-200` for the page background, `base-300` for dividers, `base-content` for text,
and `primary`, `success`, `warning`, and `error` for intent or state. Color must not be
the only way a state is communicated.

Ordinary authenticated feature pages use the Dashboard shell:

```html
<div class="mx-auto my-6 max-w-6xl space-y-8 sm:my-10">
  <!-- page header and sections -->
</div>
```

Use a narrower centered width only for intentionally compact content: `max-w-2xl` for
confirmation/error screens, `max-w-4xl` for entity management, `max-w-xl` for a short
single-purpose page, and `max-w-lg` for invitation-style pages. Complex editing forms
may use the existing `transaction-form-wrap` width (48rem). Do not constrain ordinary
lists or dashboards to a compact width.

Use `space-y-2` / `gap-2` (8 px) for tightly related content, `gap-3` (12 px) for
compact control groups, `gap-4` (16 px) for field grids, `gap-5` (20 px) for form
sections, `gap-6` (24 px) for adjacent cards, and `space-y-8` (32 px) for primary page
sections. Give flex or grid children containing long content `min-w-0`.

## Headers and navigation

Use the Dashboard header for ordinary pages:

```html
<header class="space-y-2">
  <h1 class="text-3xl font-bold tracking-tight">Page title</h1>
  <p class="text-base-content/70">A short explanation of this page.</p>
</header>
```

Place a parent-navigation link above a page header using the transaction create/edit
style. The back link and header have a 12 px separation (`space-y-3`).

```html
<div class="space-y-3">
  <a class="link link-hover" href="/parent">← Back to parent</a>
  <header class="space-y-2">…</header>
</div>
```

Use the persistent navigation and footer provided by `base.html`; do not recreate them
in feature templates. Preserve their compact mobile wrapping and visible keyboard focus.

## Cards, text, and feedback

The normal content card is the transaction pattern: `card bg-base-100 shadow-sm` with
a `card-body` that owns padding and internal layout. Use `p-4` for compact card bodies;
use `p-4 sm:p-6` or `p-5 sm:p-8` only when the content needs it. New reusable cards do
not use direct card padding in place of `card-body`.

```html
<section class="card bg-base-100 shadow-sm">
  <div class="card-body gap-4">
    <h2 class="card-title">Section title</h2>
    <p class="text-base-content/70">Supporting content.</p>
  </div>
</section>
```

The Dashboard current-month card is an emphasis variant, not the default:
`border border-base-300 border-t-4 border-t-primary bg-base-100 shadow-sm`, with
`card-body p-5 sm:p-8`. Reserve it for a page's single primary summary.

Use `font-semibold` for values and local section titles, `font-medium` for labels and
secondary interactive headings, `text-sm text-base-content/65` for hints and metadata,
and `text-xs` only for dense supporting metadata. Apply `tabular-nums` to money and
aligned numeric values.

Use `alert-info`, `alert-success`, `alert-warning`, or `alert-error` according to
meaning. Errors that need action use `role="alert"`; success or loading feedback uses
`role="status"`. The shared `alert` macro is suitable for simple text-only feedback.
Use `badge-ghost` for neutral metadata and semantic badge variants for meaningful state.

## Controls and forms

The transaction create/edit form is the control standard. Every visible control has an
associated label. Required labels include a `text-error` asterisk with
`aria-hidden="true"`; native `required` carries the semantic requirement.

```html
<div class="transaction-field">
  <label for="name" class="label font-medium">
    Name <span class="text-error" aria-hidden="true">*</span>
  </label>
  <input id="name" name="name" class="input w-full" required>
  <p id="name-hint" class="mt-1 text-sm text-base-content/65">Helpful guidance.</p>
  <p id="name-error" class="mt-1 text-sm text-error">Validation message.</p>
</div>
```

Use `input w-full`, `select w-full`, and `textarea w-full` for standard full-width
controls. Use `uppercase` only for codes such as currencies. Group related fields with
`grid grid-cols-1 gap-4 sm:grid-cols-2`; use three columns only when all controls remain
legible at the relevant breakpoint.

Hints use `mt-1 text-sm text-base-content/65`; validation messages use
`mt-1 text-sm text-error`. Invalid fields set `aria-invalid="true"`, describe their
hint/error through `aria-describedby`, retain entered values, and receive focus at the
first invalid field. The transaction stylesheet's focus outline and invalid border are
the required interaction treatment for equivalent forms outside transaction pages.

### Buttons

Buttons communicate action priority before their label is read. Use DaisyUI button
variants and semantic theme tokens only; do not add custom button colors or component
CSS. Tailwind utilities may control layout, spacing, width, and responsive behavior.

The workspace-card actions are the reference composition: `Select` is
`btn btn-primary`, the card's single immediate outcome; `Manage` is
`btn btn-ghost`, available without competing with that outcome.

| Intent | Class recipe | Use for | Examples |
|---|---|---|---|
| Primary | `btn btn-primary` | The one most important positive outcome in a card, form footer, modal, or local action group. | Select, Create, Save, Add transaction, Accept invitation |
| Secondary | `btn btn-outline` | A meaningful alternative, visible navigation, or reversible action. | Edit, Update, Back, View archived workspace |
| Tertiary | `btn btn-ghost` | Quiet contextual navigation, cancellation, reset, or compact navigation. | Manage, Cancel, Reset, Switch workspace |
| Warning | `btn btn-outline btn-warning` | A consequential but reversible action. | Archive workspace |
| Destructive | `btn btn-outline btn-error` | A destructive action before its final confirmation, including dense list actions. | Remove member, Revoke invitation, Leave workspace |
| Critical destructive | `btn btn-error` | The final confirmation of an irreversible action. | Permanently delete, Confirm deletion |

Do not use an unmodified `btn` where the action has an intent. Allow at most one
primary button in a local action group. A secondary choice that must remain readily
discoverable uses `btn btn-outline`; a choice that may recede uses `btn btn-ghost`.
Keep destructive intent semantic: do not simulate it with `text-error` on a neutral
or ghost button.

Use the default button size for page, card, form, and modal actions. Use `btn-sm`
only for compact controls such as pagination, row actions, and navbar controls.
`btn-block` is for intentionally full-width actions, such as authentication form
submission; do not use it merely to fill incidental available space. Reserve
`btn-circle` and icon-only buttons for universally recognizable compact controls;
each needs an accessible name.

Form action rows use `flex flex-wrap items-center gap-3`; separate a long form's
actions with `border-t border-base-300 pt-5`. Preserve native `disabled` state,
visible keyboard focus, and touch-friendly controls. Do not rely on color alone to
communicate an unavailable, warning, or destructive action.

### Form placement

Use a dedicated page for complex create/edit workflows: several fields, cross-field
validation, conditional or expandable sections, or context that needs more than a
short prompt. Follow the transaction create/edit composition: back link, header, one
form card, grouped fields, and a persistent action row.

Use a modal for a focused, small action: renaming a workspace, entering a transaction
ID with a confirmation flag, or a similar short form. Do not create a new page or a
persistent inline block for such an action. Use the transaction `modal` / `modal-box`
pattern and the same labels, controls, hints, validation, and action row as a page form.
The modal must support Cancel and Escape, move focus into the dialog on opening, restore
focus to its trigger on closing, and show validation/errors inside the dialog.

## Data, states, and responsive behavior

Use a `table` inside a standard card for wide repeatable data, with a card-based
responsive alternative where it cannot fit at 360 px. Keep long text readable without
horizontal page scrolling through `min-w-0`, `break-words`, `truncate` only when the
full value remains available, and `[overflow-wrap:anywhere]` where needed.

### Date and time

Use the Transaction local date-time pattern for every timestamp that includes a time.
Render a semantic `<time>` element with an ISO-8601 `datetime` value, the `block` class,
and `data-local-datetime`; give it the server-side `display_date()` output as a fallback.
The shared [`local_datetime.js`](../../app/static/js/local_datetime.js) formatter then
shows the value in the viewer's local timezone as `Tue, 09 Sep 2026 15:44:43`.

```html
<time class="block" datetime="{{ value.isoformat() }}" data-local-datetime>
  {{ display_date(value) }}
</time>
```

Add a visible label only when the surrounding context does not make the timestamp's
meaning clear. Do not hand-format a second date-time style or show an unlabeled
timezone-specific value.

Pagination uses `flex flex-wrap items-center justify-between gap-3`, a compact count,
and `btn btn-outline btn-sm` previous/next controls. Empty states use a centered
standard card with a concise heading, explanation, and one relevant action. Dialogs use
`modal` and `modal-box`, have an accessible title/description, and scroll inside the
dialog when needed. Use `details` only for optional secondary information.

At desktop and 360 px, preserve labels, focus indicators, announced loading and
success/error feedback, and touch-friendly controls. Test ordinary, validation, empty,
loading, and error states. Visual state, JavaScript, and HTMX headers are never an
authorization boundary.

## Authentication pages

Login and registration use a supported public-page composition: a responsive two-column
layout with an elevated form card (`border border-base-300 bg-base-100 shadow-xl`) and
a complementary promotional gradient card. Their controls and buttons follow this
guide. The soft introductory badge and promotional card are authentication-specific and
are not a baseline for ordinary authenticated pages.

## Exceptions and maintenance

Keep a component as implemented when it is unique to one page and is not a general
page or form pattern. When a component becomes shared, add or update a canonical pattern
here before duplicating it. Record known deviations in the
[UI normalization backlog](../requirements/UI_NORMALIZATION_BACKLOG.md).
