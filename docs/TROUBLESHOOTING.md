# Troubleshooting

Find the symptom below. Use [local setup](../README.md#local-setup) for the normal
installation path; this document only covers deviations. Run local Python commands
from the repository root with `venv` active. Return to the
[documentation index](../README.md#documentation).

- [Environment or import errors](#environment-or-import-errors)
- [Dependency installation fails](#dependency-installation-fails)
- [Port already in use](#port-already-in-use)
- [Database errors](#database-errors)
- [Registration or login fails](#registration-or-login-fails)
- [API checks fail](#api-checks-fail)
- [Source processing or FX fails](#source-processing-or-fx-fails)
- [Rebuild the Python environment](#rebuild-the-python-environment)
- [Request help](#request-help)

## Environment or import errors

**Symptom:** `externally-managed-environment`, missing `fastapi`, or missing `app`.

**Check:** `pwd`, `python --version`, `python -m pip --version`. The working directory
must be the repository root and pip should belong to `venv`.

**Fix:** activate `venv` and install the declared dependencies using the README.
Do not install packages globally to bypass an externally managed Python environment.

**Verify:** `python -c "import fastapi, uvicorn, sqlalchemy; print('Imports OK')"`.

## Dependency installation fails

| Symptom | Check and fix | Verify |
|---------|---------------|--------|
| SSL certificate verification error | Inspect Python's certificate configuration with `python -c "import ssl; print(ssl.get_default_verify_paths())"`. Repair the certificates for that Python distribution or configure the required organization CA. For python.org macOS installs, use the supplied Install Certificates command. | Retry `python -m pip install -r requirements.txt` with certificate verification enabled. |
| No compatible distribution / build failure | Identify the failing package and Python version. Python 3.13 matches the repository Dockerfile; do not replace project dependencies with unrelated individual installs. | Install the unchanged requirements, then run `python -m pip check`. |
| Missing compiler or PostgreSQL headers | On macOS, install Command Line Tools (`xcode-select --install`); on Ubuntu/Debian, install required build headers/tools, including `libpq-dev` if the failing package needs it. For Windows compiler failures, use the appropriate Build Tools or WSL. | Retry the failing requirements installation and inspect its exit status. |

The legacy `install.sh` can retry with trusted-host flags. These bypass certificate
verification for those hosts; repairing the certificate configuration is the normal
resolution. There is no need to copy a temporary diagnostics script into the project.

## Port already in use

**Symptom:** address already in use on port 8000.

**Check:** on macOS/Linux, `lsof -i :8000` identifies the process. Stop your own
development server with `Ctrl+C`, or choose a different local port:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

**Verify:** open [health on port 8001](http://localhost:8001/health). The API test
script targets port 8000, so use its dedicated setup instead of this alternate port.

## Database errors

**Symptom:** missing table/column, table already exists, or database file cannot open.

**Check:** confirm the selected `DATABASE_URL` without exposing credentials, the
working directory and `alembic current`. For SQLite, check the parent directory's
existence and write permissions. A relative path is resolved from the working directory.

**Fix:** follow [Migrations](MIGRATIONS.md) for the matching scenario: new database,
tracked existing database, or SQLite created at startup. For filesystem errors,
correct the path/ownership or use a writable development location.

**Verify:** inspect the revision/schema and run a database-backed operation.
Startup's “Database initialized” log and `/health` do not establish schema compatibility.
For nullability/type errors, check the documented [backend differences](MIGRATIONS.md#backend-differences).

## Registration or login fails

**Symptom:** API registration returns 403, registration page redirects, or login fails.

**Check:** `.env.example` disables registration. Check the selected environment's
`REGISTRATION_ENABLED` value and whether the user exists. API login expects form
fields, not a JSON body; the `username` field accepts username or email.

**Fix:** enable registration only where intended and restart, or use
[manual creation](DEPLOYMENT.md#users). For an expired/invalid token, log in again.
Web sessions renew while the protected UI is actively used and expire after
`ACCESS_TOKEN_EXPIRE_MINUTES` without activity; API bearer tokens retain a fixed
lifetime. Inactive accounts and incorrect credentials have distinct errors; inspect
the response.

**Verify:** log in and request `/api/v1/auth/me` with the bearer token. For web-only
HTTPS problems, check [proxy and cookie behavior](DEPLOYMENT.md#https-proxy).

## API checks fail

**Symptom:** cannot connect, registration returns 403/400, or output reports failures.

**Check:** use `python tests/test_api.py`, with development dependencies installed.
It targets localhost:8000 and creates fixed test users; a reused database may already
contain them. Its caught exceptions may leave a successful process exit code.

**Fix:** follow the [isolated API-check procedure](../README.md#development-checks)
with a fresh temporary database and registration enabled. Never reset your normal
database to make tests pass.

**Verify:** inspect every reported check, not just the final process status.

## Source processing or FX fails

**Symptom:** idempotency conflict, unlinked observation, upload still `pending`, or FX matching failure.

**Check:** inspect status and link metadata without logging raw messages/files.
Duplicate content is allowed unless the same `Idempotency-Key` is reused with different
creation data. Missing card/amount/currency or ambiguous matches can leave an
observation unlinked; file parsing is not implemented.

**Fix:** use the [ingestion and linking contracts](SERVICE_LAYER.md#text-ingestion)
to decide whether manual linking or reprocessing is appropriate. For FX 502,
check configured provider reachability and supported currencies before retrying.
Reprocessing deletes and recreates observations and links; it is not a harmless
diagnostic command and never deletes orphaned canonical transactions.

**Verify:** inspect the resulting payload, observations, transaction and links, including currency,
original monetary values and dates.

## Rebuild the Python environment

If the environment itself is broken, close the server and deactivate `venv`.
Rename the old environment to an unused backup name, create a fresh `venv`, and
install the declared requirements following [local setup](../README.md#local-setup).
Confirm imports and dependency consistency before discarding the old environment.
Preserve `.env`, databases, uploads and migration history throughout this procedure.

## Request help

Provide the failing command, Python/OS versions, relevant package versions and a
redacted traceback. For schema errors include the backend and revision, without the
connection password. Exclude tokens, secrets, raw bank messages, databases and uploads.
