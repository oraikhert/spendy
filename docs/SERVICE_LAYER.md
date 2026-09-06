# Service contracts

Read this when changing business behavior. This document describes current
contracts and important limitations, rather than repeating function signatures.
See [Architecture](ARCHITECTURE.md) for boundaries and the
[README](../README.md#development-checks) for supported checks.

- [Transactions and errors](#transactions-and-errors)
- [Accounts, cards and transactions](#accounts-cards-and-transactions)
- [Source ingestion](#source-ingestion)
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
| Text ingestion | Commit payload, observations, transactions, links and canonical values together |
| Create transaction and link | Commit transaction/link/canonicalization together |
| Reprocess | Replace observations/links and recanonicalize in one transaction |
| File ingestion | Move a private file before commit and remove it if the DB write fails |
| Canonicalization helper | Change an ORM object without committing |

Source orchestration owns its transaction and uses flush-only helpers; it does not
compose transaction CRUD commits. Filesystem and database writes cannot be truly
atomic, so upload uses compensating file deletion on a failed commit.

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
not unique: generating one does not itself reject a duplicate transaction. Accounts
store an IANA timezone (default `UTC`); a nullable card timezone overrides it. Changing
either value recalculates affected transaction fingerprints.

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
Timestamp dates use `coalesce(transaction_datetime, posting_datetime)` with inclusive
bounds. The UI interprets calendar dates in each card's effective timezone (card
override, then account timezone), converts their full-day bounds to UTC, and uses an
exclusive next-day bound. Results order by that effective date
descending, nulls last, then ID descending, with no creation-date fallback.

Transaction, payload and observation lists return `(items, total)` with limit/offset pagination.
Transaction reads eagerly load card/account data. Link counts use grouped queries.
Transaction observation links order by payload receipt time, then observation ID.
JSON list endpoints default to 100 and permit at most 1000 records. Transaction
selector references read all options in deterministic batches of 500, so later
cards/accounts remain reachable. Existing account/card CRUD list methods remain unbounded.

## Source ingestion

[source_processing_service.py](../app/services/source_processing_service.py) registers
an immutable payload, runs the parser selected by `(source_kind, media_type)`, stores
its version and creates zero or more observations. The current versioned registry
supports Emirates NBD `sms` plus `text/plain` and Emirates NBD `bank_statement` plus
`application/pdf`.

Exact content hashes are indexed but not unique. The key is unique within the ingestion
method: an identical replay returns the existing resource without parsing or matching
again, while reuse with different content or creation metadata is a conflict. Identical
SMS content with different non-null idempotency keys represents distinct messages and
is processed independently. When identical content cannot be distinguished by reliable
keys, the new payload and observation are preserved, but the observation is marked
`possible_duplicate` and remains unlinked without creating a transaction.

Known non-transaction messages become `ignored`; missing financial extraction becomes
`failed`; both produce no observations. A successful SMS observation preserves source
money, resolves a supplied card or matching last four digits, then attempts automatic
matching. One candidate is linked, no candidates creates a transaction, and multiple
candidates leave the observation unlinked.

Bank-statement upload validates the PDF signature, normalizes its media type and runs
PDF extraction outside the event loop. A request-only password may decrypt the input
but is excluded from storage and idempotency. `source_timezone` accepts an IANA name;
when omitted it resolves from the card override, account, then `UTC`. The resolved value
is creation metadata, participates in idempotency comparison and is persisted in
`ingestion_metadata` for reprocessing. The Emirates NBD parser extracts card, period and
statement metadata, multi-page rows, continuation text and FX originals; it validates
parsed debit and credit totals against the statement summary. Invalid,
encrypted-with-the-wrong-password and unsupported PDFs are rejected before persistence.
A recognized statement whose rows cannot be extracted consistently is kept as a failed
payload/detail without observations. The configured upload limit defaults to 20 MiB,
and the statement parser rejects more than 100 pages.

## Matching and dates

[find_matching_transactions](../app/utils/matching.py) first restricts candidates by
card ID, amount/currency and calendar day. With FX originals, either the canonical
pair or the original amount/currency pair can match. SMS candidates then use a
conservative merchant comparison: exact normalized names match, multi-token prefix
variants match at a lower similarity threshold, and other variants require two shared
tokens and a higher similarity score. Merchant similarity never widens the card,
money or date candidate set.

The source day comes from posting time, then transaction time, then creation time.
Candidates match when **any** of their posting, transaction or creation timestamps
falls within that same day (`[midnight, next midnight)`). Creation time is an OR
condition even when other timestamps exist; this differs from list/summary filters.
There is no adjacent-day tolerance. A shared business-date helper converts stored UTC
instants to the applicable source/card/account timezone before taking the calendar date
and builds UTC bounds from local midnights, including DST transitions.

Statement matching is deliberately narrower: a candidate must match the resolved card,
booked or original money, and a transaction or posting calendar day from the statement
row. Creation time is used only if the candidate has neither business timestamp. One existing
transaction cannot satisfy two rows in the same statement. Description similarity can
resolve multiple candidates. Tied candidates are assigned deterministically in ID order;
the one-row-per-transaction rule then assigns repeated identical statement rows to
different transactions. No candidates creates a transaction. Dates printed in a statement are also retained as ISO local
calendar dates in observation `extraction_metadata`. Their datetime fields represent
midnight in the persisted payload `source_timezone`, converted to UTC for storage.

Before an automatic or manual link is created, the incoming observation's business
transaction/posting dates are compared with every dated observation already linked to
the candidate transaction. Two observations are consistent when these date sets share
at least one day; this permits a statement posting date to align with an SMS receipt
date when the statement transaction date is the preceding day. A candidate is
conflicting only when both sets are non-empty and disjoint. It is then excluded from
automatic matching; a manual link or move returns a business-validation error. Missing
observation dates cannot prove a conflict and therefore do not block a link.

An SMS candidate is also excluded when its transaction already has an SMS observation
from another payload. SMS receipt time is not transaction identity and is not used to
override this rule. With no remaining candidate, a distinct SMS creates its own
transaction. Reliable retries must reuse their original `Idempotency-Key`; content hash
alone is only sufficient to mark an unkeyed delivery as a possible duplicate.

Fingerprint inputs are card, business day, amount/currency and normalized merchant. The day
prefers posting time, then transaction time, otherwise `unknown`; original monetary
values take precedence when both exist. Fingerprint generation and candidate matching
are separate operations but use the same business-date helper.

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

All operations below live in [source_processing_service.py](../app/services/source_processing_service.py).

| Operation | Behavior |
|-----------|----------|
| Manual link | Rejects an already linked observation, links it to one existing transaction and recanonicalizes. |
| Move | Atomically moves one existing link to another transaction, records it as manual and recanonicalizes both transactions. |
| Create-and-link | Requires effective card, amount and currency; observation values precede request fallbacks. Creates a transaction and manual link atomically. |
| Unlink | Removes only the link, preserves payload/observation/transaction and recanonicalizes from remaining observations. HTML callers also supply the expected transaction ID so a stale/mismatched parent URL cannot unlink another transaction's observation. |
| Reprocess | Requires a registered parser, deletes every old observation/link, recreates output, reruns matching and preserves orphaned transactions. It returns `409` when the payload has a manual link unless `force_manual_links=true` explicitly authorizes replacement. |

Observation IDs may change during reprocessing. A deliberate parser failure commits
the failed status with no old observations; an unexpected system/database failure
rolls back the replacement. Reprocess is not a read-only preview.

Use `POST /api/v1/transaction-observations/{observation_id}/move` with a
`transaction_id` JSON body instead of composing unlink and link requests. The latter
leaves an externally visible intermediate state and cannot roll both canonicalizations
back together. Operational checks for adjacent-day SMS assignments and conflicting
observation dates are documented in [Source-link audit](SOURCE_LINK_AUDIT.md).

## Files and canonicalization

Uploads stream to a temporary file under configured `UPLOAD_DIR`, calculate SHA-256,
then move to an opaque storage name. The original name is metadata only. Files are
private parser inputs: no API/HTML download route or response exposes their path or
contents. Emirates NBD credit-card statement PDFs are processed at upload; unsupported
file formats remain `pending` when no parser is registered.

[canonicalize_transaction](../app/utils/canonicalization.py) runs after link, unlink
and successful reprocess. Statement observations take monetary, posting and description
priority; SMS observations take transaction date, kind and location priority. Ties use
extraction confidence, newer payload receipt, then observation ID. Monetary pairs stay
within one observation. Missing source values preserve the current canonical field;
therefore a later source operation can overwrite a direct manual transaction edit but
does not blank a field with no replacement. FX fee is preserved, while normalization,
fingerprint and applicable FX rate are refreshed.

## Authentication and summaries

[User services](../app/services/user_service.py) validate email/username uniqueness,
hash passwords and commit writes. [Auth services](../app/services/auth_service.py)
accept username or email, check password and active status, and create JWTs without
DB writes. Registration policy belongs to routes; CLI creation bypasses it.

[Dashboard overview](../app/services/dashboard_service.py) is the single business
operation used by `GET /api/v1/dashboard` and the cookie-authenticated HTML page. It
returns immutable period/currency values without ORM records and implements the
[Dashboard calendar and spending contract](ui/DASHBOARD.md#summary-data), with an
injectable server-calendar `today`. Two read-only SQL queries discover effective
card timezones and aggregate the four displayed periods plus the comparison range;
query count does not grow with transaction count. It never commits or converts
currencies. The API exposes the current period, three previous periods and comparison
date range through typed response schemas. It accepts no date, account, card or
currency filters. The web route renders a complete 503 error state on a failed read,
with no partial totals.

When changing these contracts, use synthetic fixtures and isolate DB/network work.
Cover duplicate content, ambiguous matches, reprocessing links, FX failure, zero
amounts and date boundaries as relevant. Existing runnable checks are listed in
the [README](../README.md#development-checks); pytest fixtures are not configured.
