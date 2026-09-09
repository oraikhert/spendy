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

The source split revision reads the schema produced by `recipients_sender_001`,
including its non-null legacy transaction time and sender length, and moves data into
`source_payloads` and `transaction_observations`. It deliberately drops legacy links
whose source has no amount/currency and resolves multiple links for one source by
old-primary status, then transaction ID. Its downgrade cannot restore discarded links
or more than one observation per payload. Back up retained data before either direction.

`account_card_timezone_001` adds a non-null account timezone with a `UTC` backfill and
a nullable card override. The migration cannot infer geography from existing records;
set retained accounts/cards to their known IANA zones after upgrade. Existing uploaded
statement payloads also need an explicit, reviewed metadata/date backfill before they
can benefit from source-local calendar semantics. Do not guess a zone from filenames
or current server settings.

## Workspace ownership migration

`workspace_ownership_001` creates workspace and membership tables, removes the
obsolete global user privilege column, and backfills all seven financial tables
before enforcing ownership and same-workspace foreign keys. The Legacy Workspace
assignment and empty-installation rules are canonical in
[Workspaces](WORKSPACES.md#registration-and-onboarding).

SQLite batch reconstruction temporarily disables foreign-key enforcement on the
migration connection, checks the rebuilt graph before committing, and restores
enforcement afterward. Runtime SQLite connections enable foreign keys. The revision
preserves observation AUTOINCREMENT and its high-water mark through both directions,
including IDs of previously deleted observations. A downgrade refuses before any
schema change if more than one workspace exists, including empty workspaces; a safe
zero/one-workspace downgrade preserves financial rows but removes membership roles.

For retained data with no existing user, create the intended user through the CLI
or normal registration, then run the explicit operator action against the reviewed
database with `venv` active:

```bash
python scripts/assign_legacy_workspace_owner.py --workspace-id <legacy-id> --user-id <existing-active-user-id>
```

The script accepts only a creatorless Legacy Workspace with no owner. It serializes
assignment and refuses to replace an existing owner. Registration never calls it.
Back up retained data before migration or recovery; verify SQLite and PostgreSQL on
a disposable copy of the actual pre-upgrade schema before production rollout.

`workspace_collaboration_002` follows the ownership revision and adds
`workspace_invitations`. It constrains invited roles and delivery states, uniquely
indexes token hashes, and uses a SQLite/PostgreSQL partial unique index to permit only
one unaccepted, unrevoked invitation per normalized recipient and workspace. Its
downgrade drops invitation history; take a backup before rolling it back.

Workspace archive, restore and aggregate deletion use the existing status,
`archived_at`, ownership and tenant-key schema. Iteration 3 therefore adds no schema
revision: `workspace_collaboration_002` remains the head. Apply it before deploying
the complete lifecycle code. Do not infer schema cascade behavior from permanent
deletion; the service explicitly deletes the tenant graph in one transaction and
coordinates private files separately.

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
