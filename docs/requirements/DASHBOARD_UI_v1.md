# Dashboard UI — development task v1

Iteration: **v1** · Status: **Planned** · Baseline: **2026-09-06**

Implement the [Dashboard UI](../ui/DASHBOARD.md): a compact current-month spending
summary with three earlier months for context. That document defines the target
behavior; this task defines delivery work. Follow the
[task versioning convention](../../README.md#documentation).

## Baseline

| Area | Available | Required work |
|---|---|---|
| Web | Protected `/dashboard` with welcome, profile/status cards and quick actions | Replace body content with the four-month summary and documented states |
| Navigation | Global `Transactions` link beside the user control | Preserve it; remove transaction actions only from the Dashboard body |
| Summary service | Single arbitrary-range summary using posting-date priority and potentially mixed currencies | Add a separate typed, multi-month, per-currency HTML aggregate |
| Transactions UI | Calendar-date filters, timezone-aware bounds, money formatting and responsive DaisyUI patterns | Reuse its date semantics, URL validation and applicable presentation primitives |
| Coverage | Dashboard is touched only by session tests | Add minimal focused service and HTML coverage for critical summary behavior |

The current bearer-token [`/api/v1/dashboard/summary`](../../app/api/v1/dashboard.py)
and its [response schemas](../../app/schemas/dashboard.py) are not the data contract
for this page. Its inclusive timestamp parameters, posting-first behavior,
`base_currency` limitation and response shape remain unchanged in v1.

## Work

### 1. Page and navigation

- Replace the current dashboard template with the documented header, prominent
  current-month section and three compact historical cards. Use the shared base
  layout and existing DaisyUI/Tailwind patterns from the transaction screens.
- Remove the welcome/profile data, informational alert, account and user status,
  `Add transaction`, `View transactions`, local logout, and the quick-actions card.
  Do not add replacement actions or placeholder controls.
- Leave the global navbar structure unchanged. Its `Transactions` link beside the
  user control is the only transaction-list action promoted by the Dashboard.
- Render the summary on the ordinary authenticated GET `/dashboard`. No client-side
  interaction is required by the v1 contract, but dashboard-specific CSS, JavaScript
  or a declared dependency may be added if an existing primitive cannot implement a
  documented behavior. Record the reason and preserve server-rendered accessibility.
- Show the complete error state instead of partial totals when the summary query
  fails. Make Retry a normal link to `/dashboard`, and apply private no-store caching
  to the protected financial page.

### 2. Aggregation and presentation model

- Add a separate typed service operation for the HTML page, accepting an injectable
  `today` date for deterministic checks. Return a Dashboard overview containing the
  current period, three previous full months and per-currency entries with period
  bounds, net spending, contributing count, average and optional comparison percent.
  Keep ORM objects out of the template contract.
- Include only `transaction_kind IN ('purchase', 'refund')`. Use
  `coalesce(transaction_datetime, posting_datetime)` and exclude null effective dates.
  Calculate net spending as the Decimal negation of the signed sum; do not infer
  membership from sign or rewrite anomalous signed values.
- Resolve half-open UTC bounds for each effective card timezone while exposing
  inclusive calendar dates in the view. Group and calculate in SQL without loading
  every matching transaction; query count must stay independent of transaction count.
- Group by stored transaction currency. Never combine currencies or use original
  values, account currency, FX fields, live exchange rates, or float arithmetic.
  Keep zero-net groups when their contributing count is nonzero.
- Calculate current-month comparison against the same numbered days of the preceding
  month, capped at that month's final day. Use the UI contract's percentage formula
  and return no percentage for a zero baseline. Order currencies by code and prior
  months newest first.
- Calculate per-currency average as net spending divided by contributing count.
  Extend or relocate the existing transaction money formatter into a shared web
  presentation helper that supports summary sign rules without changing transaction
  list/detail output.

### 3. Links, states and access

- Generate every amount link through the existing validated transaction-filter URL
  behavior. Supply only `period=custom`, `date_from` and `date_to`; do not silently
  add summary membership, currency or pagination filters.
- Render distinct current and historical empty states. A zero-net group remains a
  populated group; a negative group includes a textual net-refund explanation.
- Require the existing active cookie-authenticated user and retain the shared dataset
  defined by the [access model](../ARCHITECTURE.md#access-model). The page introduces
  no mutation, form, CSRF token, account/card selector or per-user ownership rule.
- Use semantic sections and headings, accessible amount-link names, status/error
  announcements and visible keyboard focus. Keep currencies and amounts readable
  at 360 px without horizontal page scrolling.

## Constraints

Use FastAPI, async SQLAlchemy 2, Pydantic 2 and Jinja2 with the existing
[frontend](../../app/templates/base.html): HTMX 1.9.10, Tailwind 4 and DaisyUI 5 via
CDN. Prefer existing code and components before introducing a focused addition;
declare and document any new dependency without incidentally upgrading the stack.
Web handlers call services directly.

Do not change the existing dashboard JSON endpoint or schemas. No database migration
is required. Outside v1: dashboard filters, account/card breakdowns, income or balance
summaries, categories, budgets, forecasts, charts, top merchants, recent transactions,
FX conversion and account/card management. Do not add placeholder controls.

## Minimal acceptance

- Keep checks limited to critical dashboard risks; do not run unrelated full
  regression suites as an acceptance requirement.
- Add one focused service test module with compact scenarios covering the signed
  `Purchase`/`Refund` net calculation, exclusion of other types and undated records,
  currency separation, all four periods and one representative timezone boundary.
- Add one focused web test module covering protected access, representative rendered
  totals, absence of local transaction CTAs, and the exact three-parameter drill-down
  URLs. Reuse isolated SQLite setup and synthetic data.
- Perform one short browser pass at 360 px and one desktop width. Check current-month
  prominence, historical readability, keyboard focus and absence of horizontal scroll.
- Do not require the full API suite, exhaustive date/currency permutations,
  PostgreSQL, or unrelated transaction/source flows. Run the two focused dashboard
  modules and `git diff --check`, then report any untested environment.
- Update the README feature description and affected service/access documentation
  only if implementation changes their current behavior. Keep the UI document free
  of delivery notes. Mark this task Completed only after acceptance and record the
  UI document's Git revision.

