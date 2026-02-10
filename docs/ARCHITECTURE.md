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
│   │   └── user.py          # User model
│   │
│   ├── schemas/             # Pydantic schemas (validation)
│   │   └── user.py          # User schemas
│   │
│   ├── services/            # Service layer (business logic)
│   │   ├── user_service.py  # User CRUD
│   │   └── auth_service.py  # Auth and tokens
│   │
│   ├── api/v1/              # API v1 (JSON)
│   │   └── auth.py          # Register, login, me
│   │
│   ├── web/                 # Web routes (HTML)
│   │   ├── auth.py          # Login/register pages
│   │   └── pages.py         # Other pages (dashboard, etc.)
│   │
│   ├── templates/           # Jinja2 templates
│   │   ├── base.html
│   │   ├── auth/            # login.html, register.html
│   │   └── dashboard.html
│   │
│   ├── static/              # CSS, etc.
│   │
│   └── core/                # Utilities
│       ├── security.py      # JWT, password hashing
│       └── deps.py          # FastAPI dependencies
│
├── requirements.txt
├── .env
└── run.py
```

## Database schema

### Table: users

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    is_superuser BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

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

**Functions:** See [SERVICE_LAYER.md](SERVICE_LAYER.md) for full list (user_service, auth_service).

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

### Planned models

- Transaction, Category, Budget, Family, Account

### Planned services / API

- transaction_service, category_service, budget_service, family_service, report_service
- `/api/v1/transactions`, `/api/v1/categories`, `/api/v1/budgets`, `/api/v1/families`, `/api/v1/reports`

## Service layer benefits

1. **Reuse** — logic in one place, used by API and web
2. **Testability** — test services without HTTP
3. **Flexible UI** — change presentation without changing logic
4. **Thin routes** — routes handle HTTP only
5. **Scalable** — easy to add new clients (API, web, mobile)
6. **Framework-agnostic** — business logic not tied to FastAPI
