# Transactions

The Transactions pages support finding, understanding, creating, editing, and deleting records.
Interface labels are English; user content retains its language.

## Data presentation

- Amounts include their currency and two decimal places: money out uses −,
  money in uses +, and zero has no sign. Color supplements the sign.
- Type is `Purchase`, `Top-up`, `Refund`, or `Other`; it does not determine the sign.
- Cards show their name and masked number; accounts show bank and account name.
  The transaction currency can differ from the account currency.
- The list date is the transaction date, falling back to the posting date.
  Undated records show `No date`; the record's creation date never substitutes.
- All displayed timestamps use one browser-local format: abbreviated weekday, date,
  and 24-hour time to seconds (for example, `Sat, 05 Sep 2026 08:11:25`).
  Microseconds and timezone labels are not displayed. Timestamps with a stored UTC
  offset are converted; timestamps without an offset remain the local wall time
  entered by the user.
- Empty descriptions show `No description`. Location appears only when populated
  and different from the description. Source counts describe links, not verification.

## Transaction list

`Transactions` in navigation opens `/transactions`. The page contains `Add transaction`,
filters, the matching count, results, and pagination. No combined monetary total is shown.

At 1024 px and wider, a table shows **Date**, **Description**, **Card**, and **Amount**.
Date identifies `Posted` or `Transaction date`; description includes type and optional
location; card includes its account; amount includes any saved original amount/currency.
Description links to the record; `N sources` links to its Sources section.
Narrower screens show cards, wrapping text and keeping amounts visible.

### Filters

Defaults: `All time`, all accounts, cards, types, directions, and currencies; empty search and amount bounds.

| Control | Behavior |
|---|---|
| Search description | Case-insensitive substring search; trims outer spaces and treats `%` and `_` literally. |
| Period | `All time`, `This month`, or `Custom range`; custom From/To dates are required and ordered. |
| Account | `All accounts` or an account identified by bank and name. |
| More filters: Card | All cards or a card; options follow the selected account. An incompatible selection resets. |
| More filters: Type | All types or one of the four types. |
| More filters: Direction | All, Money out, or Money in. Zero appears only in All. |
| More filters: Currency | All currencies or a three-letter code, with saved-code suggestions. |
| More filters: Amount from/to | Inclusive, nonnegative bounds on absolute amount; either may be empty. Requires a specific currency. |

Conditions combine with AND. Changing currency clears amount bounds. Invalid combinations
show errors without applying a broader search. Date ranges include both complete calendar
days using the transaction date, or the posting date when the transaction date is absent.
Each card's configured timezone defines its calendar-day boundaries (card override,
then account timezone), so a range can include cards from different timezones correctly;
undated records appear only in All time.

`Apply filters` or Enter applies the form; changing fields alone does not. `Reset`
immediately restores defaults. Active advanced filters keep `More filters` expanded
and counted; the amount-bound pair counts once. Applying filters starts at page one.

### Navigation

Results sort by transaction date descending; when it is absent, posting date is used.
Undated records come last, then equal dates sort by record ID descending.
Pages contain 50 records, `Previous` / `Next`, and `1–50 of 128`; unavailable directions are disabled.
Changing a page scrolls to the beginning of the results and moves keyboard focus to its count.
URLs preserve applied filters and page across reload and Back/Forward. `This month`
uses the application's server calendar and stores explicit dates; reopening shows Custom range.
Pages beyond the remaining results resolve to the last available page, or page one when empty.

`Back to transactions` restores the originating list; direct record links return to defaults.

## Transaction details

`/transactions/{id}` contains `Back to transactions`, `Edit`, amount/currency,
full description, and type, followed by Details and Sources. On narrow screens, Details comes first.

Details shows card/account, debit/credit card type, account currency, both transaction
and posting timestamps, location, and saved original amount/exchange rate when present.
Missing timestamps show `Not specified`. Collapsed `Record info` contains Added/Updated
timestamps and any `Recorded FX fee`, labeled `Fee currency is not recorded`.
That fee is read-only and excluded from calculations. `Delete transaction` appears below Details.

### Sources

Sources shows only observations linked to the current transaction, with one card per
observation. Several observations from one payload remain separate cards and repeat a
compact payload summary so their shared evidence is clear. Unlinked observations and
payload reprocessing remain available through the JSON API, not these pages.

Each card identifies its observation and payload. The compact payload summary shows
source kind, media type, ingestion method, receipt time, processing state, parser
name/version, original filename when present, and whether a private attachment exists.
Storage paths, content hashes, file contents and download controls are never rendered.

| State | Label |
|---|---|
| pending | Pending |
| processing | Processing |
| processed | Processed |
| ignored | Ignored |
| failed | Failed; expanded details include the safe processing error. |
| Other | Unknown status. |

`Source details` expands SMS text and observation fragments plus populated extracted
values: monetary pairs, dates, description, card's last four digits, type, location and
extraction confidence. It also shows match method/time/confidence and matcher identity.
Known ingestion context fields contain observation/requested account and card, sender,
and recipients. Arbitrary metadata is not dumped. Extracted source amounts remain
distinct from transaction FX data.

`Unlink observation` confirms that only the link is removed. The payload, observation,
private file, transaction and other links remain, but canonical transaction values can
change. Ordinary POST reloads the record; HTMX refreshes the complete detail content so
canonical fields and Sources stay consistent. Sources paginate independently by payload
receipt time descending and observation ID descending, 20 per page. Removing the last
item on a page returns to the preceding available page. Viewing sources does not process them.

`Move observation`, next to the unlink control, opens a modal destination selector on
the same transaction page. It moves the existing link in one atomic operation rather
than unlinking and linking separately, marks the resulting link as manual, and
recanonicalizes both transactions. The current transaction is excluded from suggestions;
date conflicts and stale links leave the link unchanged and return an explanatory error.

## Create and edit

`Add transaction` opens `/transactions/new`; `Edit` opens `/transactions/{id}/edit`.
Both share a form; source actions are hidden while editing.

| Field | Behavior |
|---|---|
| Card | Required for creation; selected list card, sole available card, or explicit choice. Read-only after creation. |
| Amount | Required signed value; zero allowed. Hint: Use − for money out and + for money in. |
| Currency | Required three Latin letters, trimmed and uppercased. Defaults to the chosen account's currency until manually edited. |
| Type | Required; defaults to Purchase. Changes never alter the amount sign. |
| Description | Required nonempty text after trimming. |
| Transaction date | Optional date/time; starts empty. |
| More details: Posting date | Optional date/time; may precede the transaction date. |
| More details: Location | Optional, trimmed, at most 200 characters. |
| More details: Original amount/currency | Optional signed amount and currency pair; both required when adding or changing it. |
| More details: Exchange rate | Optional positive value; requires both currencies and original amount. Units: 1 original currency = rate transaction currency. |

Amounts allow up to 13 integer and 2 fractional digits; rates allow up to 9 integer
and 6 fractional digits. Excess precision and overflow produce errors, without silent rounding.
`More details` expands when populated or invalid. FX values are saved as entered,
without automatic conversion. Changing amount/currency exposes existing FX values.
Incomplete stored pairs show `Incomplete original amount`; unrelated edits remain possible.
Clearing both original fields clears the rate. Clearing optional fields removes their values;
untouched values, timestamp precision, and existing UTC offsets are preserved.

`Create transaction` / `Save changes` saves and opens the record with confirmation.
Creation does not create a source or deduplicate automatically; editing preserves source data/links.
`Cancel` leaves without saving; abandoning changes requires `Discard unsaved changes?` confirmation.

## States

- Empty lists show `No transactions yet` and Add transaction; unmatched filters offer Reset.
- Without cards, creation is disabled with `Add a card before creating a transaction`.
- Loading retains previous results with an indicator. Saving shows `Saving…` and blocks repeat submission.
- Errors preserve input and focus the first invalid field. Read failures offer Retry;
  uncertain saves/deletes/unlinks request a refresh before retrying.
- Delete confirms the description/amount and irreversible removal. Sources, files, accounts,
  cards, and other source links remain; success returns to the originating list.
- Missing records offer Back to transactions; missing links refresh Sources with an explanation.
- Expired sessions open the full sign-in page. Active users share the application's dataset.
- Controls have labels and visible keyboard focus; dialogs support Cancel/Escape and restore focus.
  Success/loading feedback is announced; layouts fit 360 px without horizontal page scrolling.
