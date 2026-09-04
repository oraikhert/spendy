# Service contracts

Read this when changing business behavior. This document describes current
contracts and important limitations, rather than repeating function signatures.
See [Architecture](ARCHITECTURE.md) for boundaries and the
[README](../README.md#development-checks) for supported checks.

- [Transactions and errors](#transactions-and-errors)
- [Accounts, cards and transactions](#accounts-cards-and-transactions)
- [Text ingestion](#text-ingestion)
- [Matching and dates](#matching-and-dates)
- [Money and exchange rates](#money-and-exchange-rates)
- [Linking and reprocessing](#linking-and-reprocessing)
- [Files and canonicalization](#files-and-canonicalization)
- [Authentication and summaries](#authentication-and-summaries)

## Transactions and errors

Pass a separate `AsyncSession` to each request/task. Existing write services commit
their changes and usually refresh returned objects. Read services do not commit.
`get_db()` closes the session; it has no explicit commit/rollback workflow.
Closing a session releases an uncommitted transaction, but a caller that catches
a database failure and continues using that session must roll it back first.

| Operation | Commit boundary |
|-----------|-----------------|
| User/account/card/transaction writes | Commit inside the service |
| Text ingestion | Flush source and optional transaction IDs, then commit source/transaction/link together |
| Create transaction and link | Flush the transaction ID, then commit transaction/link together |
| Reprocess | May call create-and-link, which commits internally, before its own final commit |
| File ingestion | Write file before committing its source row; filesystem and DB are not atomic |
| Canonicalization helper | Changes an ORM object without committing |

Do not assume wrapping existing service calls creates an atomic multi-step workflow.
For new workflows, choose one transaction owner and account for nested commits.
The reprocessing and file paths above are existing limitations.

Expected business failures commonly use `ValueError`; routes map them to HTTP.
CRUD lookups/updates may return `None`, and deletes/unlink return `False` when absent.
Database integrity failures are not uniformly translated into domain errors, so
prechecks alone do not guarantee race-safe handling of duplicate requests.
The exchange-rate service currently raises `HTTPException(502)` directly, an
exception to the intended separation of HTTP and business logic.

## Accounts, cards and transactions

[Account](../app/services/account_service.py), [card](../app/services/card_service.py)
and [transaction](../app/services/transaction_service.py) services provide CRUD.
Updates apply only fields present in the input schema; deletes are hard deletes.
Direct transaction creation validates card existence. Transaction filters reject
unknown accounts/cards and incompatible account/card combinations. Other services
have different reference checks; see the [access model](ARCHITECTURE.md#access-model)
for shared access and route authentication.

Transaction creation/update derives `merchant_norm` and `fingerprint`. Direct CRUD
does not perform source matching or automatic FX conversion. Fingerprints are indexed,
not unique: generating one does not itself reject a duplicate transaction.

Direct CRUD uses strict input schemas separately from legacy response schemas.
Required values cannot be cleared; descriptions and locations are trimmed, empty
locations become absent, and currencies accept three Latin letters normalized to
uppercase. Finite Decimal amounts/rates must fit their model precision without
rounding. Zero and either sign remain valid independently of transaction type.
An update cannot include `card_id`. Validation failures map to JSON HTTP 422 and
HTML field errors; schema/model definitions remain the source for field constraints.

Omitted update values remain untouched. Changes to amount, currency or original FX
fields validate the merged monetary group: original amount/currency form a pair,
and an optional positive rate requires both currencies and the original amount.
Explicitly clearing both original fields clears the rate. Unrelated edits preserve
incomplete legacy FX groups and the saved fee; the UI does not edit fees. Unchanged
timestamps retain the precision and offset returned by the database. This does not
change timestamp storage: SQLite may return naive values, and PostgreSQL may
normalize the original input offset. Direct edits do not rewrite source fields/links.
Transaction deletion removes its links in the same commit and preserves sources,
files, cards, accounts, and links belonging to other transactions.

Transaction filters combine before counting and pagination. Description search is
a trimmed, case-insensitive literal substring, including `%`, `_`, and backslashes.
Currency and direction filters are independent; zero is excluded from both signed
directions. Existing `min_amount`/`max_amount` remain signed bounds. Separate
nonnegative absolute bounds require a currency. Reversed ranges are rejected.
Dates use `coalesce(posting_datetime, transaction_datetime)` with inclusive bounds;
the UI expands calendar dates to full days. Results order by that effective date
descending, nulls last, then ID descending, with no creation-date fallback.

Transaction and source lists return `(items, total)` with limit/offset pagination.
Transaction reads eagerly load card/account data. Link counts use grouped queries.
Transaction source pages order by source `created_at DESC, id DESC`; the UI requests
20 links. The existing JSON source endpoint retains its list response with bounded
`limit`/`offset` (default 100, maximum 1000). Transaction selector references read
all options in deterministic batches of 500, so later cards/accounts remain
reachable. Existing account/card CRUD list methods remain unbounded. Standalone
source filters continue to use contextual `transaction_datetime`; these changes do
not alter ingestion or same-calendar-day matching below.

## Text ingestion

[create_source_event_from_text](../app/services/source_event_service.py) does the following:

1. Hash exact input text with SHA-256. Existing content raises `ValueError`; it is
   not returned as a successful replay. The unique hash is global, independent of
   source type, account and card.
2. Parse with [parse_text](../app/utils/parsing.py). Amount, currency, merchant,
   last four card digits, kind and location may be extracted. Known non-transaction
   messages are `skipped`; `parsed` does not guarantee every field is available.
3. Use the supplied card, or select the first card whose normalized last four digits
   match; `account_id`, when supplied, narrows that lookup. Ambiguous card suffixes
   are not rejected by this helper.
4. Flush the source. A nonzero parsed amount, currency and resolved card trigger
   FX resolution and matching. Missing data or a zero amount leaves it unlinked.
5. One match: link and fill missing transaction details. No matches: create a
   transaction and primary link. Multiple matches: save the source without an
   automatic link. Commit the result.

Enrichment fills missing location, description and dates, and may replace kind
`other`. It does not replace existing monetary fields or recalculate the fingerprint.
FX failures propagate; this path does not fall back silently to an unconverted amount.

## Matching and dates

[find_matching_transactions](../app/utils/matching.py) uses card ID, amount/currency
and optionally normalized merchant. With FX originals, either the canonical pair
or the original amount/currency pair can match.

The source day comes from posting time, then transaction time, then creation time.
Candidates match when **any** of their posting, transaction or creation timestamps
falls within that same day (`[midnight, next midnight)`). Creation time is an OR
condition even when other timestamps exist; this differs from list/summary filters.
There is no adjacent-day tolerance. The code takes `.date()` and constructs day
bounds without explicit timezone normalization; do not silently change this behavior.

Fingerprint inputs are card, day, amount/currency and normalized merchant. The day
prefers posting time, then transaction time, otherwise `unknown`; original monetary
values take precedence when both exist. Fingerprint generation and candidate matching
are separate operations.

## Money and exchange rates

Amounts use `Decimal` and SQL `Numeric`. Current schemas accept two decimal places
for amounts/fees and six for FX rates. The parser uses negative purchases/payments
and positive refunds/card top-ups; direct CRUD does not enforce sign by kind.

During source ingestion, differing source/account currencies trigger conversion
before matching. Canonical amount is `(source_amount * rate).quantize(Decimal("0.01"))`
using the active Decimal context; original amount/currency and rate are preserved.
No currency-specific precision table is implemented.

[ExchangeRateService](../app/services/exchange_rate_service.py) fetches latest rates
from the configured provider, not historical transaction-date rates. It returns
`Decimal`, caches per base currency in memory for the configured TTL, and reuses an
async HTTP client with a 10-second timeout. Equal currencies return 1 without a request.
Provider/network failures or unsupported target currency can produce HTTP 502.
Configuration keys are in [app/config.py](../app/config.py).

## Linking and reprocessing

All operations below live in [source_event_service.py](../app/services/source_event_service.py).

| Operation | Behavior |
|-----------|----------|
| Manual link | Adds a non-primary link; duplicate pair raises `ValueError`. Does not merge transaction fields. |
| Create-and-link | Requires a source and effective card, amount and currency. Uses overrides, then parsed/contextual values; creates a new transaction and primary link without deduplicating it. |
| Unlink | Removes only the link; keeps both source and transaction. Returns `False` if absent. |
| Reprocess | Re-parses text, resolves FX and reruns matching with the stored card. When amount/currency/card are available, replaces existing links: one match links, zero creates, multiple leaves unlinked. Missing prerequisites leave old links in place. |

Create-and-link currently uses truthiness for several overrides: a zero amount
falls back to the parsed amount. Supplying `original_amount` or `fx_rate` disables
auto-FX; supplying only `original_currency` or `fx_fee` does not. Reprocess does not
repeat card suffix discovery, can replace manual links, and does not delete old
transactions when replacing links. It is not a read-only preview or a guaranteed
idempotent operation. Its nested commit boundary is described above.

## Files and canonicalization

File ingestion hashes raw bytes, rejects existing hashes, writes under `data/uploads/`
and stores a source with status `new`. PDF/image parsing is not implemented.
A failed DB commit can leave a file behind; there is no compensating cleanup.

[canonicalize_transaction](../app/utils/canonicalization.py) can prioritize parsed
PDF monetary/posting fields, SMS transaction dates and source descriptions. It does
not commit and is not currently called by the ingestion/link routes. Do not document
its priority rules as automatic behavior of those routes.

## Authentication and summaries

[User services](../app/services/user_service.py) validate email/username uniqueness,
hash passwords and commit writes. [Auth services](../app/services/auth_service.py)
accept username or email, check password and active status, and create JWTs without
DB writes. Registration policy belongs to routes; CLI creation bypasses it.

[Dashboard summaries](../app/services/dashboard_service.py) use posting time with
transaction-time fallback and inclusive date bounds. Spending sums absolute negative
amounts, income sums nonnegative amounts, and per-kind totals retain their sign.
`base_currency` does not perform conversion: totals can mix currencies unless the
selected data is already in one currency.

When changing these contracts, use synthetic fixtures and isolate DB/network work.
Cover duplicate content, ambiguous matches, reprocessing links, FX failure, zero
amounts and date boundaries as relevant. Existing runnable checks are listed in
the [README](../README.md#development-checks); pytest fixtures are not configured.
