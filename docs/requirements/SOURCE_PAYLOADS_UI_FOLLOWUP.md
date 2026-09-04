# Source payload and observation UI follow-up

## Status and scope

This is the implementation brief for the UI iteration after the backend split of
`SourceEvent`. The current transaction Sources panel was deliberately not adapted
as part of that backend change and may fail against the new ORM/service contracts.
Do not treat the legacy panel as the current backend contract.

The follow-up must update cookie-authenticated HTML routes, view models, templates,
HTMX behavior and source-specific web tests. It must not add PDF/image parsing or
restore file downloads.

## Backend concepts

```text
SourcePayload 1 ── N TransactionObservation 1 ── 0..1 TransactionSourceLink N ── 1 Transaction
       │
       └── 0..1 BankStatementDetail
```

- `SourcePayload` is immutable evidence: raw SMS text or a private stored file,
  content hash, source kind, media type, ingestion method, receipt time and parser state.
- `TransactionObservation` is one extracted financial assertion. A statement or
  screenshot can eventually produce many observations; an ignored or failed payload
  can produce none.
- `TransactionSourceLink` is the final match. One observation cannot be linked to
  multiple transactions. `is_primary` no longer exists.
- A transaction can have observations from several independent payloads. Canonical
  values are recalculated after link, unlink and successful reprocess.

## JSON API available to the UI design

- `POST /api/v1/source-payloads/text`
- `POST /api/v1/source-payloads/upload`
- `GET /api/v1/source-payloads` and `GET /api/v1/source-payloads/{payload_id}`
- `POST /api/v1/source-payloads/{payload_id}/reprocess`
- `GET /api/v1/transaction-observations` and `GET /api/v1/transaction-observations/{observation_id}`
- `POST /api/v1/transaction-observations/{observation_id}/link`
- `POST /api/v1/transaction-observations/{observation_id}/transaction`
- `DELETE /api/v1/transaction-observations/{observation_id}/link`
- `GET /api/v1/transactions/{transaction_id}/observations`

Payload summaries expose `id`, kind, media type, ingestion method, original filename,
`has_file`, content hash, receipt time, processing state, parser identity, safe error
data and timestamps. Payload detail adds raw text, ingestion metadata, observations
and optional statement details. Observation fields include its IDs/item key, monetary
pairs, dates, description, kind, location, account/card hints, raw fragment, extraction
confidence/metadata and timestamps. Observation detail adds the parent payload summary
and optional link; link fields include transaction ID, match confidence/method/time and
matcher identity. No response exposes `file_path`, file contents or a download URL.
There is intentionally no download endpoint. The future HTML implementation may show
that a private attachment exists, but must not render a download button or derive a
storage path.

## Legacy-to-new presentation mapping

| Legacy `SourceEvent` value | New presentation source |
|---|---|
| `source_type` | `payload.source_kind`, `media_type`, and `ingestion_method` |
| `raw_text`, `raw_hash`, file fields | Parent payload |
| `parse_status`, `parse_error` | Parent payload processing state/error |
| `parsed_*` transaction fields | Observation fields without the `parsed_` prefix |
| sender and recipients | `payload.ingestion_metadata` |
| account/card context | Observation, with payload metadata as ingestion context |
| `source_event_id` in forms/URLs | `observation_id` for link actions; `payload_id` for payload details |
| `is_primary` | Removed; do not replace it with a UI concept |

## Required transaction detail behavior

- Render one card/row per linked observation, not per payload. Include a compact
  parent payload summary so multiple rows can identify their shared evidence.
- Show extracted amount/currency, source transaction and posting dates, description,
  type, location, card last four, extraction confidence and match metadata when present.
- Show payload kind/media/ingestion labels, receipt time, processing status and parser
  name/version. Raw SMS text may be shown only in an explicitly expanded detail area.
- Do not show raw file paths, hashes as filenames, file contents or download controls.
- Unlink by observation ID. Confirmation must explain that payload, observation,
  private file and transaction remain, while canonical transaction values may change.
- Refresh the transaction record as well as its observation list after unlink because
  canonical amount, dates, description, kind or location may have been recalculated.
- Paginate observations deterministically using the backend order. Several observations
  from one payload must remain separate entries.

## States and actions

- `pending`: stored, but no compatible parser exists yet. Reprocess is unavailable
  until backend support is added.
- `processed`: parsing completed; it can have linked or unlinked observations.
- `ignored`: recognized as non-financial and normally has no observations.
- `failed`: processing failed. Show the safe general error and offer reprocess only
  when the backend accepts it.
- Unlinked observations need separate review/link/create-transaction affordances;
  ambiguous automatic matches remain unlinked rather than showing candidate links.
- Reprocess is destructive to observations and links. Confirm it, then replace all
  cached IDs and results from the response. Canonical transactions left without a
  source are retained and may require separate review.
- A `409` can mean an unsupported parser, an already linked observation or another
  state conflict. A `404` means the item changed/disappeared; refresh the relevant list.

## HTML implementation areas

- Replace legacy source calls in `app/web/transactions.py` with observation/payload
  service calls and build a dedicated presentation model; do not expose ORM objects
  directly to templates.
- Update the transaction Sources partial and any confirmation/error copy to the new
  identifiers and canonicalization consequences.
- Remove every legacy file-download route, URL, button and availability check.
- Preserve ordinary form fallback, HTMX fragment targets/swaps, CSRF validation,
  validated local return URLs, pagination clamping and no-store/history protections.
- Keep autoescaping for raw text/errors/metadata, accessible labels and status regions,
  restored keyboard focus, confirmation Cancel/Escape behavior and the 360 px layout.

## Acceptance checks for the UI iteration

- Adapt `tests/test_transactions_web.py` to payloads/observations and restore the full
  HTML suite as an acceptance gate.
- Cover multiple observations from one payload, shared payload summaries, all processing
  states, linked/unlinked records, reprocess ID replacement and canonical refresh.
- Verify unlink with ordinary POST and HTMX, page clamping, missing/stale IDs, auth,
  CSRF, escaping and database failure recovery.
- Assert that no rendered page contains a storage path or download control and that
  old HTML download URLs return 404.
- Browser-check desktop and 360 px layouts, keyboard focus, screen-reader status text,
  session expiry and Back/Forward behavior without storing bank data in browser history.
