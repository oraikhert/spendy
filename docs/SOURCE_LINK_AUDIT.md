# Source-link audit

Return to the [documentation index](../README.md#documentation).

Run [`scripts/audit_source_links.sql`](../scripts/audit_source_links.sql) after a
source migration or bulk reprocessing operation and periodically in production. A
weekly run is a reasonable default while SMS and statement ingestion are active.
The script is PostgreSQL-specific, starts a read-only transaction and never changes
payloads, observations, links or transactions.

From the PostgreSQL container used by the deployment:

```bash
docker compose exec -T db \
  psql -U spendy -d spendy -X -v ON_ERROR_STOP=1 -P pager=off \
  < scripts/audit_source_links.sql
```

The first result set reports transactions linked to SMS observations from more than
one payload. Automatic matching treats those payloads as separate messages, regardless
of their timestamps. The second reports pairs of observations in one transaction whose
business transaction dates disagree; a statement's persisted `source_timezone` wins
for statement/SMS comparisons. The third reports statement/SMS observations linked to
different transactions despite agreeing on card, business date and booked or original
money. It is intended to find old UTC-boundary splits. All are candidate lists for
review, not repair commands: merchant descriptions, migrated links, delayed delivery
and missing transaction dates can require human interpretation.

The audit intentionally excludes raw payload text, file contents and internal file
paths. Treat merchant descriptions and identifiers as private financial metadata and
limit access to the output.

Do not update `transaction_source_links` directly. Correct a confirmed assignment
through `POST /api/v1/transaction-observations/{observation_id}/move`; this updates
the link and recanonicalizes both affected transactions atomically.
