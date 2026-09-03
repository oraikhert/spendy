# Spendy

Spendy tracks accounts, cards, transactions and their source messages/files.
The JSON API supports transaction management, SMS parsing, matching and summaries;
the web UI currently provides login, optional registration and a dashboard page.
File uploads are stored, but PDF/image parsing is not implemented. Family groups,
budgets, reports and transaction management pages remain future work.

Built with FastAPI, async SQLAlchemy, Pydantic, Alembic and SQLite/PostgreSQL.
The UI uses Jinja2, HTMX, Tailwind CSS and DaisyUI; no frontend build is required.

## Documentation

Read the document for your task; there is no need to load the entire documentation.

| Task | Start here |
|------|------------|
| Install, run, use the API or run checks | This README |
| Locate code or understand architectural decisions | [Architecture](docs/ARCHITECTURE.md) |
| Understand transaction screens and behavior | [Transactions UI](docs/ui/TRANSACTIONS.md) |
| Implement transaction screens, iteration 1 | [Transactions UI task v1](docs/requirements/TRANSACTIONS_UI_v1.md) |
| Change ingestion, matching, money handling or service behavior | [Service contracts](docs/SERVICE_LAYER.md) |
| Initialize, upgrade or change a database schema | [Migrations](docs/MIGRATIONS.md) |
| Deploy or update the Docker/PostgreSQL installation | [Deployment](docs/DEPLOYMENT.md) |
| Diagnose installation or runtime errors | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Work as a coding agent | [Project rules](AGENTS.md) |

UI documentation in `docs/ui/<FEATURE>.md` describes the target interface in the
present tense. Keep one current file per feature, without version numbers or delivery status.

Development tasks use `docs/requirements/<FEATURE>_v<N>.md`, starting at `v1`.
Each task links to the UI documentation and records its scope, baseline, status and
acceptance checks. Revise the open iteration in place; create the next version for
a new delivery iteration. Keep completed task scopes unchanged and record the UI
documentation's Git revision at completion so their references remain traceable.

## Local setup

Run commands from the repository root. Python 3.13 matches the
[Docker runtime](Dockerfile). The commands below use a POSIX shell; on Windows,
activate the environment with `venv\Scripts\activate`.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

For a new checkout, copy [.env.example](.env.example) to `.env`; preserve any
existing `.env`. Settings are defined in [app/config.py](app/config.py).
Choose `DATABASE_URL` before initializing the schema. The example uses the local
SQLite file `spendy.db`; environment variables override values from `.env`.

Initialize a **new, empty database before starting the app** using
[the migration procedure](docs/MIGRATIONS.md#new-database). For an existing
database, use the appropriate scenario in that document first.

The example `.env` disables registration. To create the first local user through
the UI, set `REGISTRATION_ENABLED=true`, then start the app:

```bash
python run.py
```

Open [the web UI](http://localhost:8000), register and log in. To close registration
afterward, set `REGISTRATION_ENABLED=false` and restart. For installations where
self-registration stays disabled, use [manual user creation](docs/DEPLOYMENT.md#users).
Set a unique `SECRET_KEY` before using the app with real data.

For later starts, activate `venv` and run the same command; `./start.sh` is a
shortcut. `./install.sh` installs dependencies but does not initialize migrations
or configure users. Stop the development server with `Ctrl+C`.

## API usage

- [Swagger UI](http://localhost:8000/docs) lists current endpoints and schemas.
- [ReDoc](http://localhost:8000/redoc) provides an alternative API reference.
- [api_examples.http](api_examples.http) contains auth requests and error examples.
- [Health](http://localhost:8000/health) checks HTTP availability, not DB readiness.

Use an existing user, or register with `POST /api/v1/auth/register` when
registration is enabled. Login at `POST /api/v1/auth/login` uses form fields
`username` (username or email) and `password`. Send the returned token as
`Authorization: Bearer <access_token>` for protected requests.

Account, card, transaction, source-event and dashboard APIs require an active user.
Health, login, registration, exchange-rate lookup and transaction-kind metadata
do not require a token; disabled registration returns 403. Authentication does not
provide per-user budget isolation: see [the current access model](docs/ARCHITECTURE.md#access-model).
For exact validation limits and payloads, use Swagger and
[input schemas](app/schemas/), rather than maintaining a second endpoint catalog.

## Development checks

With `venv` active, install [development dependencies](requirements-dev.txt), then
run the parser checks (they do not need a server or database):

```bash
python -m pip install -r requirements-dev.txt
python tests/test_parsing.py
python tests/test_parsing_kind_location.py
```

For [API checks](tests/test_api.py), reserve port 8000 for an isolated test server.
In one terminal, use a fresh temporary SQLite database and enable registration:

```bash
source venv/bin/activate
spendy_test_dir=$(mktemp -d)
export DATABASE_URL="sqlite+aiosqlite:///$spendy_test_dir/api.sqlite3"
export REGISTRATION_ENABLED=true
python run.py
```

This disposable test server deliberately uses SQLite startup bootstrap; it does
not test migrations. In a second terminal, activate `venv` and run:

```bash
python tests/test_api.py
```

The test creates users at `http://localhost:8000`; never point it at your normal
server. Inspect its output as well as its exit code: the script catches failures.
Stop the test server and close its shell afterward so its environment overrides
are not reused. Use a fresh temporary directory for each run.

There is no configured pytest suite, linter, type checker or frontend build.
For documentation-only changes, check content, relative links/anchors, referenced
paths and `git diff --check`; application tests are unnecessary.

## License

MIT
