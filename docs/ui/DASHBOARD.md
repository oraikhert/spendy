# Dashboard

The Dashboard is the authenticated landing page for a compact view of spending in
the current month and earlier calendar years. Interface labels are English.

## Summary data

- A transaction contributes to net spending when its type is `Purchase` or `Refund`,
  regardless of its amount sign, and `excluded_from_summary` is false. `Top-up`,
  `Other`, and undated transactions do not contribute.
- The effective date is the transaction date, falling back to the posting date.
  Creation and update timestamps never substitute for a missing financial date.
- Net spending is `-SUM(amount)` for the contributing transactions. A normally
  positive refund reduces spending; refunds exceeding purchases produce negative
  net spending. A zero net result with contributing transactions is not an empty state.
- Turnover is `-SUM(amount)` for every dated `Purchase` and `Refund` in the period,
  including transactions excluded from net spending. It uses the same spending-sign
  convention as net spending. A currency represented only by excluded transactions
  therefore remains visible with zero net spending and its nonzero turnover.
- Amounts are grouped by the transaction currency and are never added across
  currencies. Original amounts, account currencies, saved exchange rates, recorded
  FX fees, and live conversion rates are excluded.
- Summary arithmetic uses `Decimal`. Amounts include their currency and two decimal
  places. Positive net spending has no leading plus; negative net spending uses −.
- Currencies are ordered by their uppercase code. This order avoids implying that
  nominal amounts in different currencies are comparable.

The application server calendar determines today. For every card, calendar-day
boundaries use the card timezone, then its account timezone, then UTC. The current
period runs from the first day of the current month through today, inclusive. The
earlier periods are complete calendar months and appear newest first within a year.

Current-month change compares each currency with the same numbered date range in
the preceding month. If the preceding month is shorter, its range ends on its final
day. Change is `((current - previous) / abs(previous)) × 100`, rounded to the nearest
whole percent. A zero previous value shows `No comparable spending` instead of a
percentage.

## Page layout

`/dashboard` starts with `Dashboard` and a short explanation of the current-year view.
The page body contains no `Add transaction`, `View transactions`, logout, profile,
account-status, administrator-status, or other quick-action control. The persistent
`Transactions` link beside the user control in the global navigation remains the
primary route to the transaction list; the Dashboard does not duplicate it.

### Current month

The first and visually strongest full-width section identifies the current month
and its inclusive date range. Each currency with at least one dated `Purchase` or
`Refund`, including an excluded one, has a compact summary containing:

- net spending;
- included transaction count, labeled `Transactions`;
- average net spending per contributing transaction;
- turnover including excluded transactions, shown as compact supporting text; and
- change from the matching part of the previous month.

For each currency, the current-month section also lists up to three largest expenses.
They are `Purchase` transactions with a negative stored amount, ordered by absolute
spend descending; refunds and anomalous positive purchases are excluded.

The average is net spending divided by the included count in that currency. It is
unavailable when that count is zero. Count and average describe the same non-excluded
`Purchase` and `Refund` records as net spending. Largest expenses also exclude flagged
transactions.

### Earlier months and years

The current-year heading follows the current-month section and contains every earlier
complete month in that calendar year. In January, this otherwise empty group is
omitted: the previous year is shown immediately instead. Each card identifies one
complete month and lists net spending, included transaction count, then turnover for
every currency present in that month. Historical cards do not repeat averages or
month-over-month percentages.

At the bottom, `Show more` appends all twelve months of the immediately preceding
year under its own year heading. Repeating it appends the next preceding year. Empty
months within an available year still render. The button is disabled after the earliest
calendar year that has a dated `Purchase` or `Refund`, including an excluded one; it is
also disabled when there is no such data at all.

The page has no category, merchant, account, card, income, balance, budget, forecast,
chart, or recent-transaction section. Transaction type is not presented as a spending
category.

## Transaction drill-down

Every displayed net-spending amount is a link to the transaction list. Its URL has
only these query parameters:

- `period=custom`;
- `date_from=YYYY-MM-DD`; and
- `date_to=YYYY-MM-DD`.

The current-month link ends on today; a historical link covers the complete month.
No direction, currency, type, account, card, amount, search, or page filter is set.
The destination therefore intentionally shows all transactions in the selected
period rather than reproducing the narrower summary calculation. Accessible link
text identifies the period and currency even when the visible amount is brief.

## States and accessibility

- With no dated current-month `Purchase` or `Refund`, the primary section says
  `No purchase or refund transactions this month`; historical months still render.
- An empty historical month says `No purchase or refund transactions` within its card.
- Several currencies remain separate at every viewport width. Long formatted amounts
  wrap without hiding their currency or causing horizontal page scrolling.
- `Show more` uses the same outline/disabled treatment as transaction pagination and
  announces its loading state; it appends content rather than replacing the summary.
- Negative net spending is explicitly labeled as a net refund rather than relying
  on color or the minus sign alone.
- A read failure replaces the summary with a concise error and a `Retry` link to
  `/dashboard`; partial or stale totals are not shown as current.
- Unauthenticated or inactive users cannot view the page. Authenticated financial
  responses use private, no-store caching and the application's shared-data access model.
- Headings preserve a logical hierarchy, status text is announced, links have clear
  names and visible keyboard focus, and the content remains usable at 360 px.
