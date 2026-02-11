# Spendy application architecture

## Project structure

```
spendy/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings
│   ├── database.py          # DB and session setup
│   │
│   ├── models/              # SQLAlchemy models
│   │   ├── user.py          # User
│   │   ├── account.py       # Account (institution, currency)
│   │   ├── card.py          # Card (account_id, masked number, type)
│   │   ├── transaction.py   # Transaction (canonical; amount, currency, fingerprint)
│   │   ├── source_event.py  # SourceEvent (raw text/file, parsed_*, parse_status)
│   │   └── transaction_source_link.py  # Link transaction ↔ source_event
│   │
│   ├── schemas/             # Pydantic schemas (account, card, transaction, source_event, dashboard)
│   ├── services/            # account, card, transaction, source_event, dashboard (+ user, auth)
│   ├── utils/               # parsing (SMS/text), matching (fingerprint), canonicalization
│   │
│   ├── api/v1/              # auth, accounts, cards, transactions, source_events, dashboard, meta
│   ├── web/                 # Login/register, pages
│   ├── templates/           # base, auth, dashboard
│   ├── static/              # CSS
│   └── core/                # security.py, deps.py
│
├── data/uploads/            # Stored uploads (git-ignored except .gitkeep)
├── alembic/versions/        # Migrations (users, transaction tables, parsed_card_number)
├── requirements.txt
├── .env
└── run.py
```

## Database schema

### Table: users

See `app/models/user.py`. Columns: id, email, username, hashed_password, full_name, is_active, is_superuser, created_at, updated_at.

### Transaction domain tables

- **accounts** — id, institution, name, account_currency, created_at, updated_at.
- **cards** — id, account_id (FK), card_masked_number, card_type (debit|credit), name; UNIQUE(account_id, card_masked_number). See `app/models/card.py`.
- **transactions** — id, card_id (FK), amount, currency, transaction_datetime, posting_datetime, description, transaction_kind (purchase|topup|refund|other), optional FX fields, merchant_norm, fingerprint; indexes on (card_id, posting_datetime), (card_id, transaction_datetime), (card_id, amount, currency), fingerprint. See `app/models/transaction.py`.
- **source_events** — id, source_type (e.g. sms_text, pdf_statement), received_at, raw_text, file_path, raw_hash (unique), parsed_* fields (amount, currency, description, parsed_card_number, etc.), account_id/card_id (optional), parse_status (new|parsed|failed). See `app/models/source_event.py`.
- **transaction_source_links** — composite PK (transaction_id, source_event_id), match_confidence, is_primary. See `app/models/transaction_source_link.py`.

Migrations: `alembic/versions/` (trans001 for transaction tables, parsed_card_001 for parsed_card_number). See [MIGRATIONS.md](MIGRATIONS.md).

## Auth flow (with service layer)

### User registration

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /api/v1/auth/register
       │ {email, username, password}
       ▼
┌──────────────────────┐
│  API: auth.register  │
│  (HTTP handling)     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Service:             │
│ user_service         │
│ .create_user()       │──► Check email unique
│                      │──► Check username unique
│                      │──► Hash password
│                      │──► Create User in DB
│                      │──► Commit
└──────────┬───────────┘
           │
           │ User object / ValueError
           ▼
┌──────────────────────┐
│  API: auth.register  │──► Map to HTTP status
└──────────┬───────────┘
           │
           │ 201 Created / 400 Bad Request
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

### User login

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /api/v1/auth/login
       │ {username, password}
       ▼
┌──────────────────────┐
│  API: auth.login     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Service:             │
│ auth_service         │
│ .authenticate_user() │──► Find by username or email
│                      │──► Check password (bcrypt)
│                      │──► Check is_active
└──────────┬───────────┘
           │ User object / ValueError
           ▼
┌──────────────────────┐
│ Service:             │
│ auth_service         │
│ .create_user_access  │──► Build JWT payload
│ _token()             │──► Generate token
└──────────┬───────────┘
           │ Token object
           ▼
┌──────────────────────┐
│  API: auth.login     │──► HTTP response
└──────────┬───────────┘
           │
           │ {access_token, token_type}
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

### Get profile

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ GET /api/v1/auth/me
       │ Authorization: Bearer <token>
       ▼
┌──────────────────────┐
│  API: auth.me        │
│  Dependency:         │
│  get_current_active  │──► Decode JWT
│  _user()             │──► Get user_id
│                      │──► user_service.get_user_by_id()
│                      │──► Check is_active
└──────────┬───────────┘
           │
           │ User object
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

## Security components

### 1. Password hashing (bcrypt)

```python
passlib.context.CryptContext(schemes=["bcrypt"])
```

- One-way hashing; salt generated and stored automatically; protects against rainbow tables.

### 2. JWT (JSON Web Tokens)

```python
jose.jwt.encode(data, SECRET_KEY, algorithm="HS256")
```

**Token payload:**
```json
{
  "sub": 1,              // user_id
  "username": "user",
  "exp": 1234567890      // expiry
}
```

**Settings:** `SECRET_KEY` from `.env`; `ALGORITHM`: HS256; `ACCESS_TOKEN_EXPIRE_MINUTES`: 30 (configurable).

### 3. OAuth2 password flow

Standard OAuth2 password bearer:

```python
OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
```

## Layered architecture

### Service-layer overview

```mermaid
graph TD
    Browser[Browser]
    APIClient[API Client<br/>Mobile/External]
    WebPages[Web Pages<br/>Jinja2+HTMX HTML]
    API[API Routes<br/>JSON responses]
    Services[Service Layer<br/>Business Logic]
    DB[(Database<br/>SQLite/PostgreSQL)]
    Security[Core Security<br/>JWT, Password Hashing]
    
    Browser --> WebPages
    APIClient --> API
    WebPages --> Services
    API --> Services
    Services --> DB
    Services --> Security
```

**Benefits:** One business layer for API and web; API returns JSON for external clients; web uses Jinja2+HTMX; easy to move to SPA later without changing services.

### Layers

```
┌─────────────────────────────────────────┐
│        Presentation Layer               │
│  API Routes (/api/v1/*) → JSON          │
│  Web Routes (/auth/*, /dashboard) → HTML│
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Service Layer                   │
│  user_service: create_user, get_user_*  │
│  auth_service: authenticate_user,       │
│                create_user_access_token │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Data Access Layer               │
│  SQLAlchemy models, async sessions      │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│            Database                     │
│  SQLite (dev) / PostgreSQL (prod)       │
└─────────────────────────────────────────┘
```

### Responsibilities

#### API routes (app/api/v1/)

- Handle and validate HTTP requests
- Call service layer
- Map exceptions to HTTP status codes
- Return JSON
- Auth via Bearer token

**Example:**
```python
@router.post("/register")
async def register(user_in: UserCreate, db: AsyncSession):
    try:
        user = await user_service.create_user(user_in, db)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

#### Web routes (app/web/)

- Render HTML with Jinja2
- Handle forms with HTMX
- Call the same service layer
- Auth via HTTP-only cookies
- Return HTML or HTMX headers

**Example:**
```python
@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        user = await auth_service.authenticate_user(username, password, db)
        token = await auth_service.create_user_access_token(user)
        
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/dashboard"
        response.set_cookie(key="access_token", value=token.access_token, httponly=True)
        return response
    except ValueError as e:
        return HTMLResponse(content=f'<div class="alert alert-error">{e}</div>')
```

**Stack:** Jinja2 (templates), HTMX (forms without reload), Tailwind CSS, DaisyUI (components).

#### Service layer (app/services/)

- Business logic
- Uniqueness checks
- Business rules
- Work with multiple models
- Return domain objects or raise `ValueError`

**Example:**
```python
async def create_user(user_in: UserCreate, db: AsyncSession) -> User:
    if await get_user_by_email(user_in.email, db):
        raise ValueError("Email already registered")
    
    db_user = User(...)
    db.add(db_user)
    await db.commit()
    return db_user
```

**Functions:** See [SERVICE_LAYER.md](SERVICE_LAYER.md) for full list (user_service, auth_service, account_service, card_service, transaction_service, source_event_service, dashboard_service).

#### Models (app/models/)

- Table definitions, relations, indexes, constraints.

#### Core (app/core/)

- security.py: JWT, password hashing
- deps.py: FastAPI dependencies

**Auth helpers:** `get_current_user()` (API, Bearer); `get_current_user_from_cookie()` / `get_current_user_from_cookie_required()` (web).

## Dependencies

Protected endpoints use:

```
get_current_active_user
        │
        ├──► get_current_user
        │           ├──► oauth2_scheme (extract token)
        │           └──► get_db
        │
        └──► Check is_active
```

## Switching to PostgreSQL

1. Set `DATABASE_URL` in `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@localhost/spendy
   ```
2. Install driver: `pip install asyncpg`
3. Code stays the same (SQLAlchemy abstraction).

## Web UI (current)

- API routes (JSON) and web routes (HTML) both use the service layer.
- HTMX submits forms without full reload; server returns HTML fragments or redirect headers.
- JWT in HTTP-only cookie (XSS protection).

### Possible next steps

**Phase 1:** More web pages (transactions, reports, settings, family groups).

**Phase 2:** Optional move to SPA (React/Vue): remove `app/web/` and templates; API and services unchanged.

### Implemented (transaction tracking)

- **Models:** Account, Card, Transaction, SourceEvent, TransactionSourceLink.
- **Services:** account_service, card_service, transaction_service, source_event_service, dashboard_service; utils: `app/utils/parsing.py` (SMS/text parsing), `app/utils/matching.py` (fingerprint, merchant_norm), `app/utils/canonicalization.py`.
- **API:** `/api/v1/accounts`, `/api/v1/cards`, `/api/v1/transactions`, `/api/v1/source-events`, `/api/v1/dashboard/summary`, `/api/v1/meta/transaction-kinds`. Source events support text ingest, file upload, manual link, create-transaction-and-link, reprocess, download.

### Planned (not yet implemented)

- Category, Budget, Family; category_service, budget_service, family_service, report_service; corresponding API routes.

## Service layer benefits

1. **Reuse** — logic in one place, used by API and web
2. **Testability** — test services without HTTP
3. **Flexible UI** — change presentation without changing logic
4. **Thin routes** — routes handle HTTP only
5. **Scalable** — easy to add new clients (API, web, mobile)
6. **Framework-agnostic** — business logic not tied to FastAPI
