# Database migrations

Use this document to initialize or change a schema. Run local commands from the
repository root with `venv` active. Alembic loads `DATABASE_URL` through application
settings, including `.env`; confirm the target without printing credentials.
Return to the [documentation index](../README.md#documentation).

- [New database](#new-database)
- [Existing database with Alembic history](#existing-database-with-alembic-history)
- [SQLite created by application startup](#sqlite-created-by-application-startup)
- [Changing the schema](#changing-the-schema)
- [Backend differences](#backend-differences)
- [Recovery and rollback](#recovery-and-rollback)

## New database

For a new SQLite database, choose an unused file path in `DATABASE_URL`. For
PostgreSQL, create the database first and use `postgresql+asyncpg://...`;
the driver is already in [requirements.txt](../requirements.txt).

Apply the repository's existing migrations **before the first application start**:

```bash
alembic upgrade head
alembic current
```

Then follow [local startup](../README.md#local-setup) or
[container startup](DEPLOYMENT.md#first-deployment). Do not run `alembic init`
or generate another initial revision: the migration environment/history already exists.

For PostgreSQL in Docker, use the same migrations via the container commands in
Deployment. Changing `DATABASE_URL` and applying migrations creates a schema; it
does not transfer existing SQLite records or uploaded files.

## Existing database with Alembic history

1. Confirm the environment and take a recoverable backup before schema changes.
2. Inspect the current revision, repository heads and migration files:

   ```bash
   alembic current
   alembic heads
   alembic history --verbose
   ```

3. Review pending `upgrade()` operations and any data backfills, then apply:

   ```bash
   alembic upgrade head
   alembic current
   ```

4. Start/restart the app and verify an operation that reads the database.
   `/health` checks only HTTP availability.

The canonical history is [alembic/versions/](../alembic/versions/), not a manually
copied revision table. Current revision metadata alone does not prove that the
live schema matches the ORM models.

## SQLite created by application startup

[init_db()](../app/database.py) calls `Base.metadata.create_all()` for SQLite.
It creates missing tables from current models but does not apply ALTER operations
or record Alembic revisions. PostgreSQL has no startup schema creation.

If tables exist but `alembic current` reports no revision, do not treat the database
as empty: the initial migration will attempt to create existing tables. Also do
not assume it matches `head` just because startup succeeded.

- **Data must be kept:** stop writers, back up the database and inspect a copy.
  Compare tables, columns, nullability, indexes and constraints against the migration
  history. Plan and verify an explicit reconciliation before changing revision metadata.
  There is no universal stamp/reset command for this situation.
- **Disposable development data:** point `DATABASE_URL` at a new unused SQLite file,
  apply [the new database procedure](#new-database), and keep the old file until it
  is confirmed unnecessary. Do not delete migration files to reset local data.

## Changing the schema

After editing models, use a disposable development database with the expected
existing schema and revision:

```bash
alembic revision --autogenerate -m "Describe the schema change"
```

Review the generated revision before applying it. Check renames versus drop/add,
defaults, nullability, indexes, uniqueness, foreign keys and data backfills.
Backfill existing rows before enforcing new non-null constraints. Add a new
revision for corrections; do not rewrite deployed revisions.

Verify upgrade and, when reversible, downgrade/upgrade on disposable databases.
Record which backends were checked. `alembic upgrade head --sql` can help inspect
SQL, but does not validate runtime behavior and is not suitable for every migration
that needs live schema reflection or data access.

## Backend differences

SQLite has limited ALTER support; use Alembic batch operations when the intended
change requires rebuilding a table. Enable SQLite foreign keys for constraint checks.
PostgreSQL must also be checked when constraints, types or backfills are affected.

Known schema differences in the current code/history: the rename migration retains
`source_events.transaction_datetime` as non-null, while the model permits null;
the sender migration uses length 200, while the model uses 50. A database created
with `create_all()` can therefore differ from one upgraded through Alembic. These
need explicit corrective migrations; documentation changes do not reconcile them.
In particular, file ingestion omits contextual transaction time and may fail on
the migrated non-null schema.

## Recovery and rollback

| Symptom or task | Procedure |
|-----------------|-----------|
| Missing table/column | Confirm the database target and revision; apply pending migrations if this is a tracked schema. For an untracked SQLite schema, use the reconciliation section above. |
| Multiple heads | Inspect both branches and their data effects. After resolving conflicts, create a reviewed merge revision with `alembic merge heads -m "Merge migration branches"`. |
| Failed migration | Stop writes; inspect the error, revision and actual schema. Some operations may have applied, especially on SQLite. Repair a copy before retrying against retained data. |
| Roll back one revision | Review its `downgrade()`, backup and data-loss implications first. Use `alembic downgrade -1` only on the intended, explicitly approved database. |

Rollback may drop data and is not a replacement for restoring a verified backup.
Do not manually edit `alembic_version`, delete revision files, or stamp a retained
database as a generic fix for migration errors.
