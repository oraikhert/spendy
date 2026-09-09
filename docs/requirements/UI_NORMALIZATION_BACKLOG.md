# UI Normalization Backlog

This backlog records existing presentation differences from the
[UI Style Guide](../ui/STYLE_GUIDE.md). It is planning material, not an instruction to
change templates as part of the documentation delivery. Preserve feature behavior,
access control, CSRF protection, HTMX targets/swaps, and responsive behavior when
completing any item.

## Remaining intentional exceptions

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
