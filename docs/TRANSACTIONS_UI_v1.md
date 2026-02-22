# Spendy MVP UI Spec — Transactions Screens (daisyUI)

This document describes two core MVP screens for the Spendy web UI:

1. **Transactions list + filters**
2. **Transaction details (with sources)**

It is aligned with the current data model:
- `Account`, `Card`, `Transaction`, `SourceEvent`, `TransactionSourceLink`

And it proposes concrete UI components using **daisyUI** (Tailwind component classes), including form validation patterns.

---

## Data Model (UI-relevant fields)

### Account
- `institution` (string)
- `name` (string)
- `account_currency` (char(3))

### Card
- `account_id` (FK → Account)
- `card_masked_number` (string)
- `card_type` (`debit` | `credit`)
- `name` (string)

### Transaction (canonical)
- `card_id` (FK → Card)
- `amount` (numeric, signed)
- `currency` (char(3))
- `transaction_datetime` (datetime, nullable)
- `posting_datetime` (datetime, nullable)
- `description` (text)
- `location` (text, nullable)
- `transaction_kind` (`purchase` | `topup` | `refund` | `other`)
- FX (optional):
  - `original_amount` (numeric, nullable)
  - `original_currency` (char(3), nullable)
  - `fx_rate` (numeric, nullable)
  - `fx_fee` (numeric, nullable)
- Debug (read-only):
  - `merchant_norm` (string, nullable)
  - `fingerprint` (string, nullable)

### SourceEvent (raw + parsed)
- `source_type` (`telegram_text` | `sms_text` | `sms_screenshot` | `bank_screenshot` | `pdf_statement` | `manual`)
- `created_at` (datetime)
- `updated_at` (datetime)
- raw:
  - `raw_text` (text, nullable)
  - `file_path` (text, nullable)
  - `raw_hash` (string)
- parsed (nullable):
  - `parsed_amount`, `parsed_currency`
  - `parsed_transaction_datetime`, `parsed_posting_datetime`
  - `parsed_description`
  - `parsed_card_number` (string(4), nullable)
  - `parsed_transaction_kind` (string(50), nullable)
  - `parsed_location` (string(200), nullable)
- context (optional):
  - `account_id` (FK → Account, nullable)
  - `card_id` (FK → Card, nullable)
  - `transaction_datetime` (datetime, nullable)
  - `sender` (string(50), nullable)
  - `recipients` (string(500), nullable)
  - `parsed_original_amount`, `parsed_original_currency`
- status:
  - `parse_status` (`new` | `parsed` | `failed`)
  - `parse_error` (text, nullable)

### TransactionSourceLink
- `match_confidence` (float, nullable)
- `is_primary` (bool)

---

## Canonicalization rules (MVP)
The UI should reflect these rules clearly:

- **Primary date displayed in lists**:  
  Use `posting_datetime` if present, otherwise `transaction_datetime`. If both are null, fall back to `created_at`.

- **Canonical fields (“truth”)**:
  - Amount/currency typically come from `pdf_statement` sources when present.
  - `transaction_datetime` is often best from SMS/push-like sources when present.
  - Description may differ across sources; canonical `Transaction.description` is the “selected best value”.

- **Sources are never lost**:
  Multiple `SourceEvent` records can link to a single canonical `Transaction` via `TransactionSourceLink`.

---

# Screen 1 — Transactions list + filters

## Goal
- Provide a fast overview of spending for a selected period.
- Enable search and filtering across transactions.
- Make it easy to open **Transaction details**.
- Surface deduplication status via the number of linked sources.

## Layout (Desktop)

### Desktop Wireframe (table + filters sidebar)
```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Transactions                                                                 [ + Add ] [Import]│
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────┬──────────────────────────────────────────────────────────────┐
│ FILTERS                        │ RESULTS                                                      │
│                               │  Summary:  128 tx   Out: -12,340 AED   In: +2,100 AED        │
│ Account                        │  Sort: [ Date ▼ ]  View: [Table] [Cards]                      │
│ ┌───────────────────────────┐ │  ┌────────────────────────────────────────────────────────┐  │
│ │ Emirates NBD • Main AED   │ │  │ Date      │ Description                │ Card   │ Amt   │  │
│ └───────────────────────────┘ │  │───────────┼────────────────────────────┼────────┼───────│  │
│ Card                           │  │ 2026-02-16│ CARREFOUR • Dubai Mall     │ ****1234│ -120 │  │
│ ┌───────────────────────────┐ │  │           │ 2 sources                  │        │ AED   │  │
│ │ Visa Credit • **** 1234   │ │  │ 2026-02-15│ TALABAT                    │ ****1234│ -45  │  │
│ └───────────────────────────┘ │  │           │ 1 source                   │        │ AED   │  │
│ Period                         │  │ 2026-02-14│ REFUND: Amazon             │ ****9876│ +30  │  │
│ [ Today ] [ Week ] [ Month ]   │  │           │ 3 sources                  │        │ AED   │  │
│ [ Custom ▼ ]                    │  └────────────────────────────────────────────────────────┘  │
│ Search                          │  Pagination:  ◀ Prev   1 2 3 ...   Next ▶   Per page [50]   │
│ Kind (multi)                    │                                                              │
│ Direction (All/Out/In)          │                                                              │
│ Amount range                    │                                                              │
│ Currency                        │                                                              │
│ [ Apply ]  [ Reset ]            │                                                              │
└───────────────────────────────┴──────────────────────────────────────────────────────────────┘
```

## Layout (Mobile)

### Mobile Wireframe (cards + filters drawer/bottom sheet)
```text
┌─────────────────────────────────────────┐
│ Transactions                     [+] [≡]│
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Period: [Month ▼]  Feb 2026             │
│ Quick: [Today] [Week] [Month] [Custom]  │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ 🔎 Search: [ carrefour / 120 / taxi  ]  │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Summary: Out -12,340 AED  In +2,100 AED │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 16 Feb • CARREFOUR Dubai Mall           │
│ ****1234 • purchase • 2 sources         │
│                          -120.50 AED    │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ 15 Feb • TALABAT                        │
│ ****1234 • purchase • 1 source          │
│                           -45.00 AED    │
└─────────────────────────────────────────┘

FILTER DRAWER (opens on [≡])
┌─────────────────────────────────────────┐
│ Filters                            [X]  │
│ Account: [Emirates NBD • Main ▼]        │
│ Card:    [Visa • ****1234 ▼]            │
│ Kind:    [purchase ▼] (multi)           │
│ Direction: (•)All ( )Out ( )In          │
│ Amount:  Min [   ]  Max [   ]           │
│ Currency: [AED ▼]                       │
│ [ Apply ]                 [ Reset ]      │
└─────────────────────────────────────────┘
```

---

## UI Components (daisyUI) + Validation

### Header actions
- **Buttons**: `btn`, `btn-primary`, `btn-outline` (Button component)

### Filters container
- **Desktop sidebar**: `card` container
- **Mobile drawer**: `drawer` component for responsive filter panel

### Filter controls (per field)

1) **Account**
- Component: `select` with options from `/accounts`
- daisyUI: `select select-bordered w-full`

2) **Card**
- Component: `select` (dependent on selected account)
- daisyUI: `select select-bordered w-full` (disabled when no account)

3) **Period**
- Quick presets: `join` group of `btn join-item`
- Custom range:
  - `input input-bordered` with `type="date"`

4) **Search**
- `input input-bordered` with `type="search"`

5) **Transaction kind**
- MVP: `select select-bordered` (single)
- If multi later: `checkbox` list

6) **Direction**
- `radio` group (`All / Outflow / Inflow`)

7) **Amount range**
- Two `input input-bordered` number fields, `step="0.01"`
- Validation: `min_amount <= max_amount` (UI + server)

8) **Currency**
- `select select-bordered` (optional)

### Results table/cards
- **Desktop**: `table table-zebra` inside `overflow-x-auto`
- **Badges**: `badge` for kind/currency/date-type/sources count
- **Pagination**: `pagination` (uses `join`)

### Error / empty states
- `alert alert-info` (empty results)
- `alert alert-error` (API errors)

### Validation styling (daisyUI validator)
Use `validator` + `validator-hint` with `input/select/textarea` for HTML5 validation feedback.

Example:
```html
<fieldset>
  <input class="input input-bordered validator w-full"
         type="number" required step="0.01" />
  <div class="validator-hint">Enter a valid amount</div>
</fieldset>
```

---

## Behaviors (MVP)
- Default sorting: date desc (posting → transaction → created)
- Each row shows: date + badge (P/T/C), description (+ location), card, kind, amount/currency, FX (optional), sources count

---

# Screen 2 — Transaction details (with sources)

## Goal
- Show canonical transaction fields (the “truth”).
- Show all linked sources (raw + parsed), with match metadata.
- Allow editing canonical fields.
- Allow reprocessing sources and selecting primary source.

## Layout (Desktop)

### Desktop Wireframe (two columns: canonical + sources)
```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ← Back  Transaction Details                                                     [Edit] [Delete]│
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  Amount: -120.50 AED      Kind: purchase     Card: Visa • ****1234     Account: ENBD • Main AED│
│  Description: CARREFOUR Dubai Mall                                                               │
│  Dates:  Transaction: 2026-02-16 18:41   Posting: 2026-02-17 03:10                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────┬───────────────────────────────────────────────┐
│ CANONICAL (Transaction)                         │ SOURCES (SourceEvent + Link)                  │
│ Card:     [ Visa • ****1234 ▼ ]                │  Source #1  [PRIMARY]  confidence: 0.98       │
│ Kind:     [ purchase ▼ ]                       │  Type: pdf_statement     Created: 2026-02-17 │
│ Amount:   [ -120.50 ] Currency: [ AED ▼ ]      │  Parse: parsed                                   │
│ Transaction datetime: [ 2026-02-16 18:41 ]     │  Preview: "CARREFOUR ... AED 120.50"            │
│ Posting datetime:     [ 2026-02-17 03:10 ]     │  File: statement_feb.pdf  [View]                 │
│ Description: [ textarea ]                      │  Actions: [Set primary] [Reprocess] [Unlink]    │
│ Location:  [ Dubai Mall ]                      │  ▾ Raw / Parsed details (expand)                │
│ FX (optional):                                 │                                                 │
│ Original amount: [ 33.10 ] [ EUR ▼ ]            │  Source #2            confidence: 0.83          │
│ FX rate:        [ 3.64 ]   FX fee: [ 0.00 ]     │  Type: sms_text        Created: 2026-02-16     │
│ merchant_norm (ro) / fingerprint (ro)          │  Raw preview + parsed summary                    │
│                              [ Save changes ]   │                                                 │
└───────────────────────────────────────────────┴───────────────────────────────────────────────┘
```

## Layout (Mobile)

### Mobile Wireframe (stack + Tabs: Details / Sources)
```text
┌─────────────────────────────────────────┐
│ ← Transaction                            │   [⋯]
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ -120.50 AED                              │
│ CARREFOUR Dubai Mall                     │
│ purchase • Visa ****1234                 │
│ Txn: 16 Feb 18:41   Post: 17 Feb 03:10   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ [ Details ]   [ Sources (3) ]            │
└─────────────────────────────────────────┘
```

---

## UI Components (daisyUI) + Validation

### Header / Actions
- Buttons: `btn`, `btn-primary`, `btn-outline`, `btn-error`
- Optional mobile actions: `dropdown` menu

### Canonical form (Transaction)
Container: `card` (desktop), stacked sections (mobile)

Field mapping:

1) **Card**
- `select select-bordered w-full`
- Required

2) **Kind**
- `select select-bordered w-full`
- Required (default `purchase`)

3) **Amount**
- `input input-bordered validator w-full` type number, step 0.01
- Required, non-zero (server-side)
- Allow negative/positive

4) **Currency**
- `select select-bordered validator w-full`
- Required, `^[A-Z]{3}$` (server-side)

5) **Transaction datetime / Posting datetime**
- `input input-bordered w-full` type `datetime-local`
- Optional
- Recommended rule: if both exist, posting >= transaction

6) **Description**
- `textarea textarea-bordered validator w-full`
- Required, length limit (server-side)

7) **Location**
- `input input-bordered w-full` optional

**FX section (optional)**
- show when any FX field present or user toggles “Add FX”
- `original_amount` (number), `original_currency` (select), `fx_rate` (number), `fx_fee` (number)
- Validation:
  - if original_amount set → original_currency required (and vice versa)

**Read-only debug**
- `merchant_norm`, `fingerprint` as monospace text with `badge` labels

### Sources list
Each source is a `card` with:
- `badge` for source_type
- `badge` for parse_status (success/warning/error)
- `badge badge-outline` PRIMARY
- Confidence value (text; optional `progress` later)
- Preview: raw_text snippet or file label

Actions:
- `btn btn-sm` Set primary
- `btn btn-sm btn-outline` Reprocess
- `btn btn-sm btn-ghost` Unlink (optional MVP)

Expanded raw/parsed:
- Show structured parsed fields: amount/currency, tx/posting datetimes, description, card last4, kind, location, plus context (sender/recipients).
- Use `modal` (`<dialog>`) for full raw text and/or file preview.
- For file uploads elsewhere: `file-input`.

### Tabs on mobile
- `tabs` + `tab` (two tabs: Details / Sources(N))

### Alerts
- Reprocess in progress: `alert alert-info`
- Success: `alert alert-success`
- Failure: `alert alert-error` + show `parse_error`

---

## daisyUI components referenced (official docs)
- Input (`input`) — supports `date`, `datetime-local`, `search`, `number`
- Select (`select`)
- Textarea (`textarea`)
- File input (`file-input`)
- Validator (`validator`, `validator-hint`)
- Button (`btn`)
- Table (`table`)
- Pagination (`pagination`) + Join (`join`)
- Drawer (`drawer`)
- Tabs (`tabs`, `tab`)
- Modal (`modal`)
- Dropdown (`dropdown`)
- Badge (`badge`)
- Alert (`alert`)
- Radio (`radio`) / Checkbox (`checkbox`)

---

## API mapping (minimal)
### Transactions list
- `GET /accounts`
- `GET /accounts/{account_id}/cards`
- `GET /transactions?...filters...`

### Transaction details + sources
- `GET /transactions/{transaction_id}`
- `PATCH /transactions/{transaction_id}`
- `GET /transactions/{transaction_id}/sources`
- `PATCH /transactions/{transaction_id}/sources/{source_event_id}` (set primary)
- `POST /source-events/{source_event_id}/reprocess`
