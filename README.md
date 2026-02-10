# Spendy — Family Budget Tracking Application

A family budget tracking app built with FastAPI.

## Tech stack

- **Backend**: FastAPI
- **Frontend**: Jinja2 + HTMX + Tailwind CSS + DaisyUI
- **Database**: SQLite (can be switched to PostgreSQL)
- **ORM**: SQLAlchemy 2.0 (async)
- **Authentication**: JWT (Bearer for API, HTTP-only cookies for web pages)
- **Password hashing**: bcrypt

## Quick start

```bash
python -m venv venv
source venv/bin/activate   # Mac/Linux; on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # optional
python run.py
```

Or use scripts: `./install.sh` (install), then `./start.sh` (run).

After starting:
- **Web UI**: http://localhost:8000 (redirects to login)
- **API docs**: http://localhost:8000/docs

If you have install issues, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Project structure

```
spendy/
├── app/
│   ├── main.py              # Application entry point
│   ├── config.py            # Configuration
│   ├── database.py          # Database setup
│   ├── models/              # SQLAlchemy models (DB tables)
│   ├── schemas/             # Pydantic schemas (validation)
│   ├── services/            # Service layer (business logic)
│   │   ├── user_service.py  # User CRUD
│   │   └── auth_service.py  # Auth and tokens
│   ├── api/v1/              # API routes (JSON)
│   ├── web/                 # Web routes (HTML)
│   │   ├── auth.py          # Login/register pages
│   │   └── pages.py         # Other pages (dashboard, etc.)
│   ├── templates/           # Jinja2 templates
│   ├── static/              # CSS, JS, images
│   └── core/                # Utilities (security, deps)
├── docs/                    # Documentation
├── alembic/                 # DB migrations
├── requirements.txt
├── run.py
└── README.md
```

### Architecture

The app uses a **layered architecture with a service layer**:

```
┌─────────────────────────────────────────┐
│         Clients                         │
├──────────────────┬──────────────────────┤
│   Web Pages      │      REST API        │
│  (Jinja2+HTMX)   │    (JSON/Bearer)     │
└────────┬─────────┴──────────┬───────────┘
         │                    │
         └────────┬───────────┘
                  │
         ┌────────▼─────────┐
         │    Services      │
         │ (Business logic) │
         └────────┬─────────┘
                  │
         ┌────────▼─────────┐
         │     Models       │
         │   (SQLAlchemy)    │
         └────────┬─────────┘
                  │
         ┌────────▼─────────┐
         │    Database      │
         │     (SQLite)     │
         └──────────────────┘
```

**Benefits:** Business logic is separate from HTTP; one service layer serves both API and web; services are easy to test; REST API stays available for other clients. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Installation and run

### 1. Virtual environment and dependencies

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

If you get an SSL error on macOS: `pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt` or use `./install.sh`.

### 2. Environment

```bash
cp .env.example .env
```

For production, change `SECRET_KEY` (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).

### 3. Run

```bash
python run.py
# or
uvicorn app.main:app --reload
```

App: http://localhost:8000  
Swagger: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc

## Web UI

The app has a web UI with Jinja2, HTMX, Tailwind CSS and DaisyUI.

### Pages

| Path | Description |
|------|-------------|
| `/` | Home (redirects to `/auth/login`) |
| `/auth/login` | Login |
| `/auth/register` | Register |
| `/auth/logout` | Logout |
| `/dashboard` | User dashboard (auth required) |

### Features

- **HTMX** — forms submit without full page reload
- **Tailwind CSS + DaisyUI** — responsive UI
- **HTTP-only cookies** — JWT stored safely (XSS protection)
- **Validation** — client and server
- **Auto login** — after register you are logged in

### Using the web UI

1. Open http://localhost:8000
2. Click "Register" to create an account
3. After register you are logged in and see the dashboard

## API endpoints

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/login` | Login (returns JWT) |
| GET | `/api/v1/auth/me` | Current user (token required) |

**Register** — JSON: `email`, `username`, `password` (min 8 chars), `full_name` (optional).  
**Login** — form-data: `username` (or email), `password`. Response: `access_token`, `token_type: "bearer"`.  
**Profile** — header: `Authorization: Bearer <access_token>`.

## Using the API

### Via Swagger UI (http://localhost:8000/docs)

1. **Register**: POST `/api/v1/auth/register` → "Try it out" → enter data → "Execute".
2. **Login**: POST `/api/v1/auth/login` → enter username and password → "Execute" → copy `access_token`.
3. **Authorize**: "Authorize" → paste token in Value → "Authorize".
4. **Profile**: GET `/api/v1/auth/me` → "Try it out" → "Execute".

### Data requirements

- **Email** — valid, unique.
- **Username** — 3–100 chars, unique.
- **Password** — 8–72 chars.

### Full flow (bash)

```bash
# Register
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "username": "testuser", "password": "testpassword123", "full_name": "Test User"}'

# Login and save token
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=testpassword123" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Profile
curl -X GET "http://localhost:8000/api/v1/auth/me" -H "Authorization: Bearer $TOKEN"
```

### Python example

```python
import requests
BASE = "http://localhost:8000/api/v1"
requests.post(f"{BASE}/auth/register", json={"email": "u@ex.com", "username": "u", "password": "password123", "full_name": "User"})
r = requests.post(f"{BASE}/auth/login", data={"username": "u", "password": "password123"}, headers={"Content-Type": "application/x-www-form-urlencoded"})
token = r.json()["access_token"]
print(requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"}).json())
```

### API errors

- **400** "Email already registered" / "Username already taken" — use another email or username.
- **401** "Incorrect username or password" — wrong credentials.
- **401** "Could not validate credentials" — wrong or expired token; login again.
- **400** "Inactive user" — user is deactivated.

### Tips

- JWT expires in 30 minutes (configurable in `.env`).
- Login accepts **username** or **email** in the `username` field.
- More examples in `api_examples.http` (VS Code REST Client).

## FAQ

- **Stop the server?** — `Ctrl+C` in the terminal.
- **Where is data stored?** — In `spendy.db` (SQLite) in the project root.
- **Reset DB?** — Stop server, run `rm spendy.db`; DB is recreated on next start.
- **Request examples?** — `api_examples.http` or Swagger UI.
- **Run tests:**  
  1. `pip install -r requirements-dev.txt`  
  2. `python test_api.py` (from project root with venv active)

## Switching to PostgreSQL

1. Create a database in PostgreSQL.
2. In `.env`: `DATABASE_URL=postgresql+asyncpg://user:password@localhost/spendy`
3. `pip install asyncpg`
4. Restart the app (or apply migrations; see [docs/MIGRATIONS.md](docs/MIGRATIONS.md)).

## Security

- Passwords hashed with bcrypt.
- JWT for auth; expiry set in `.env`.
- In production: use HTTPS, your own `SECRET_KEY`, and limit CORS in `app/main.py`.

## Roadmap

1. **Budget management** — transactions (income/expense), categories, accounts
2. **Web pages** — transactions, reports, settings
3. **Family groups** — shared family budget
4. **Reports** — charts, stats, export
5. **Notifications** — reminders, budget alerts
6. **Mobile app** — React Native or Flutter
7. **Auth** — OAuth, two-factor

## Documentation

| File | Description |
|------|-------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture and design |
| [docs/SERVICE_LAYER.md](docs/SERVICE_LAYER.md) | Service layer: structure, usage, examples |
| [docs/MIGRATIONS.md](docs/MIGRATIONS.md) | Alembic migrations |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Install and run problems |

## License

MIT
