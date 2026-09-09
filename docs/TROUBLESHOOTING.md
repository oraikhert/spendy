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
- [Workspace selection or deletion fails](#workspace-selection-or-deletion-fails)
- [API checks fail](#api-checks-fail)
- [Codex Browser reports ERR_BLOCKED_BY_CLIENT](#codex-browser-reports-err_blocked_by_client)
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

## Workspace selection or deletion fails

**Symptom:** an archived selection redirects to Workspaces, a financial API returns
`409 Workspace archived`, or permanent deletion is rejected.

**Check:** confirm the target workspace, the caller's workspace-local role and the
current lifecycle state. Archive clears a selected web workspace without selecting a
replacement. Permanent deletion requires an owner, an already archived workspace and
an exact case-sensitive `confirmation_name`; a form opened before another lifecycle
change is stale and must be reloaded.

**Fix:** select an active workspace explicitly, or have an owner restore the archived
workspace. For permanent deletion, reload its management page and type the stored name
exactly. Do not edit status or tenant records directly in the database.

**Verify:** the active selector excludes archived workspaces while management still
lists them. After deletion, verify the workspace is absent. If logs contain a safe
post-commit cleanup diagnostic, the database deletion is final; inspect the opaque
`UPLOAD_DIR/.quarantine` operation directory as an operator without exposing file
paths or contents. Restore files manually only for a logged pre-commit compensation
failure, never to imply that committed database records can be recovered.

## API checks fail

**Symptom:** cannot connect, registration returns 403/400, or output reports failures.

**Check:** use `python tests/test_api.py`, with development dependencies installed.
It targets localhost:8000 and creates fixed test users; a reused database may already
contain them. Its caught exceptions may leave a successful process exit code.

**Fix:** follow the [isolated API-check procedure](../README.md#development-checks)
with a fresh temporary database and registration enabled. Never reset your normal
database to make tests pass.

**Verify:** inspect every reported check, not just the final process status.

## Codex Browser reports ERR_BLOCKED_BY_CLIENT

**Symptom:** the Codex in-app browser reports `net::ERR_BLOCKED_BY_CLIENT` for an
isolated local test server, even though the origin appears under **Settings > Browser**.

This message does not by itself prove that macOS or the configured site permission
blocked the request. Chromium can first replace an unreachable page with an internal
`data:text/html` error page; Codex then rejects inspection of that internal page and
surfaces the secondary policy error. Opening the JSON `/health` response as a browser
page can produce the same misleading result even when Uvicorn logs `GET /health 200`.

**Check:** use the following order so the first failed layer is visible:

1. Start the disposable server from a local terminal using the
   [browser-smoke setup](../README.md#development-checks), and wait for
   `Application startup complete`. Keep that terminal and process running.
2. From another local terminal, run `curl http://127.0.0.1:8139/health`. A JSON
   response verifies HTTP readiness only; do not use `/health` as the browser's
   first page.
3. In **Settings > Browser**, allow the exact origin
   `http://127.0.0.1:8139`. Scheme, host and non-default port are part of the
   origin; an entry for `localhost`, HTTPS or another port does not replace it.
4. Open `http://127.0.0.1:8139/auth/login` in the Codex browser and inspect the
   Uvicorn access log.

Interpret the result before changing settings:

- No browser `GET` appears in the server log: the browser cannot reach that server
  process or the exact origin is not allowed. Restart the server from a local terminal,
  confirm the port, and review **Settings > Browser**. In a managed environment, an
  administrator policy may be stricter than the visible user permission.
- The server logs the HTML route with `200` and it renders: browser access works;
  ignore an earlier `/health` navigation failure and continue the smoke test from
  HTML routes.
- The browser's generated error page reports `ERR_CONNECTION_REFUSED`, and no matching
  request reaches Uvicorn: the server was stopped, still starting, or running in an
  isolated execution environment. Restore reachability rather than adding more site
  entries.
- The server logs the HTML route with `200`, but that HTML route still fails: capture
  the Codex desktop log and browser/server timestamps and report the issue; this is
  distinct from the known readiness/error-page cases above.

**Fix:** keep one disposable local server alive for the entire browser pass, probe
readiness with `curl`, and begin automation at `/auth/login`, `/auth/register` or the
target HTML page. Reuse the exact allowed origin throughout redirects and links.
Stop the server and remove its disposable database after the test.

**Verify:** register a synthetic user, reach `/workspaces/onboarding`, create a
synthetic workspace, and open `/workspaces`. Confirm each request appears in the
server access log and repeat the relevant page at desktop and 360 px widths.

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
