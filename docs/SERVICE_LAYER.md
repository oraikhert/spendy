# Service layer

## What it is

The service layer sits between API routes and the database models. It holds the application’s business logic.

## Why use it

### Without a service layer

All logic lived in API routes:

```python
# app/api/v1/auth.py (old)
@router.post("/register")
async def register(user_in: UserCreate, db: AsyncSession):
    # Check email - 5 lines
    result = await db.execute(select(User).where(User.email == user_in.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check username - 5 lines
    result = await db.execute(select(User).where(User.username == user_in.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Create user - 10 lines
    db_user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        ...
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user
```

**Issues:** Logic duplicated when adding web routes; hard to test (need to mock HTTP); business and HTTP logic mixed; no reuse.

### With a service layer

```python
# app/services/user_service.py
async def create_user(user_in: UserCreate, db: AsyncSession) -> User:
    """All user-creation business logic"""
    if await get_user_by_email(user_in.email, db):
        raise ValueError("Email already registered")
    
    if await get_user_by_username(user_in.username, db):
        raise ValueError("Username already taken")
    
    db_user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        ...
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user
```

```python
# app/api/v1/auth.py
@router.post("/register")
async def register(user_in: UserCreate, db: AsyncSession):
    """Only HTTP handling"""
    try:
        user = await user_service.create_user(user_in, db)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

**Benefits:** One implementation for API and web; easy to test without HTTP; clear separation; reusable logic. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture.

## Structure

```
app/services/
├── __init__.py             # Exports
├── user_service.py         # User CRUD
├── auth_service.py         # Auth and tokens
├── account_service.py      # Account CRUD
├── card_service.py         # Card CRUD
├── transaction_service.py  # Transaction CRUD, list with filters, get sources
├── source_event_service.py # Create from text/upload, link, create-and-link, reprocess
└── dashboard_service.py    # Summary (total_spent, total_income, by_kind)
```

```
app/utils/
├── parsing.py              # parse_text_stub (SMS bank notifications: amount, currency, merchant, card number)
├── matching.py             # normalize_merchant, generate_fingerprint, find_matching_transactions
└── canonicalization.py     # canonicalize_transaction (priority from linked source events)
```

**Usage:**
```python
from app.services import user_service, auth_service, account_service, card_service, transaction_service, source_event_service, dashboard_service

user = await user_service.create_user(...)
account = await account_service.create_account(db, account_data)
# etc.
```

## Service functions

### user_service.py

#### `get_user_by_id(user_id: int, db: AsyncSession) -> User | None`

Get user by ID.

```python
user = await user_service.get_user_by_id(123, db)
if user:
    print(f"Found: {user.username}")
```

#### `get_user_by_email(email: str, db: AsyncSession) -> User | None`

Get user by email.

#### `get_user_by_username(username: str, db: AsyncSession) -> User | None`

Get user by username.

#### `get_user_by_username_or_email(identifier: str, db: AsyncSession) -> User | None`

Find by username or email (e.g. for login).

```python
user = await user_service.get_user_by_username_or_email("johndoe", db)
user = await user_service.get_user_by_username_or_email("john@example.com", db)
```

#### `create_user(user_in: UserCreate, db: AsyncSession) -> User`

Create user with validation: unique email, unique username, password hashing, save to DB.

**Raises:** `ValueError("Email already registered")`, `ValueError("Username already taken")`.

```python
try:
    user = await user_service.create_user(user_in, db)
except ValueError as e:
    print(f"Error: {e}")
```

#### `update_user(user_id: int, user_update: UserUpdate, db: AsyncSession) -> User`

Update user. Validates existence and uniqueness when email/username change; hashes password if changed.

**Raises:** `ValueError("User not found")`, `ValueError("Email already registered")`, `ValueError("Username already taken")`.

### auth_service.py

#### `authenticate_user(username_or_email: str, password: str, db: AsyncSession) -> User`

Check credentials: find user by username or email, verify password (bcrypt), check `is_active`.

**Raises:** `ValueError("Incorrect username or password")`, `ValueError("Inactive user")`.

```python
try:
    user = await auth_service.authenticate_user("johndoe", "password123", db)
except ValueError as e:
    print(f"Login error: {e}")
```

#### `create_user_access_token(user: User) -> Token`

Create JWT access token. Returns `Token` with `access_token` and `token_type` ("bearer").

```python
token = await auth_service.create_user_access_token(user)
print(token.access_token)
```

## Using services in API routes

### Pattern

```python
from app.services import user_service, auth_service

@router.post("/endpoint")
async def endpoint(data: Schema, db: AsyncSession):
    try:
        result = await service_function(data, db)
        return result  # 200 OK
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Register example

```python
@router.post("/register", response_model=UserSchema, status_code=201)
async def register(user_in: UserCreate, db: AsyncSession) -> User:
    try:
        user = await user_service.create_user(user_in, db)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

### Login example

```python
@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm, db: AsyncSession) -> Token:
    try:
        user = await auth_service.authenticate_user(
            form_data.username, form_data.password, db
        )
        token = await auth_service.create_user_access_token(user)
        return token
    except ValueError as e:
        if "Inactive" in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        else:
            raise HTTPException(
                status_code=401,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"}
            )
```

## Using services in web routes

Web routes (Jinja2+HTMX) use the same services. On success return HTML or set cookies/redirect; on `ValueError` return an error fragment or 400. See [ARCHITECTURE.md](ARCHITECTURE.md) for the login example.

## Rules

### In services

- Business logic, validation, checks
- DB access (queries, commits)
- Work with multiple models
- Complex calculations or external integrations

### Not in services

- HTTP-specific code (HTTPException, status codes, headers)
- FastAPI dependencies
- request/response objects
- Building JSON or HTML responses

### Exceptions

Services raise `ValueError`, not `HTTPException`. Routes map them to HTTP:

```python
# Bad - HTTP in service
async def create_user(...):
    if await get_user_by_email(...):
        raise HTTPException(status_code=400, detail="Email exists")

# Good - domain exception
async def create_user(...):
    if await get_user_by_email(...):
        raise ValueError("Email already registered")
```

Typical mapping: 400 (validation), 401 (auth), 404 (not found).

## Testing

Test services without HTTP:

```python
# tests/test_user_service.py
import pytest
from app.services import user_service

@pytest.mark.asyncio
async def test_create_user(db_session):
    user_data = UserCreate(
        email="test@example.com",
        username="testuser",
        password="password123"
    )
    user = await user_service.create_user(user_data, db_session)
    assert user.id is not None
    assert user.email == "test@example.com"

@pytest.mark.asyncio
async def test_create_user_duplicate_email(db_session):
    user_data = UserCreate(
        email="test@example.com",
        username="testuser",
        password="password123"
    )
    await user_service.create_user(user_data, db_session)
    user_data2 = UserCreate(
        email="test@example.com",
        username="testuser2",
        password="password123"
    )
    with pytest.raises(ValueError, match="Email already registered"):
        await user_service.create_user(user_data2, db_session)
```

## Transaction-domain services (reference)

- **account_service** — create_account, get_account, get_accounts, update_account, delete_account. See `app/services/account_service.py`.
- **card_service** — create_card, get_card, get_cards_by_account, update_card, delete_card. See `app/services/card_service.py`.
- **transaction_service** — create_transaction (sets merchant_norm, fingerprint), get_transaction, get_transactions (filters: account_id, card_id, date_from/to, q, kind, min/max_amount, limit, offset), update_transaction, delete_transaction, get_transaction_sources. See `app/services/transaction_service.py`.
- **source_event_service** — create_source_event_from_text (parse + optional auto-match), create_source_event_from_file (stores in data/uploads), get_source_event, get_source_events (filters), link_source_to_transaction, create_transaction_and_link, unlink_source_from_transaction, reprocess_source_event (re-parse + re-match). See `app/services/source_event_service.py`.
- **dashboard_service** — get_dashboard_summary(date_from, date_to, account_id?, card_id?); returns total_spent, total_income, by_kind, count_transactions, last_updated_at. See `app/services/dashboard_service.py`.

Utils: `parse_text_stub` in `app/utils/parsing.py` returns parsed_amount, parsed_currency, parsed_description, parsed_card_number, parse_status. Matching and canonicalization are used inside source_event_service and transaction_service.

## Adding new services

1. **Create the module** (e.g. `app/services/transaction_service.py`) with async functions that take schemas and `db: AsyncSession`, do validation and DB work, return domain objects or raise `ValueError`.
2. **Export in** `app/services/__init__.py`.
3. **Use in routes**: call the service in a try/except and map `ValueError` to HTTP status.

## Moving logic from routes to services

1. Extract the business logic from the route into a new function in a service module.
2. Keep the same logic (DB calls, checks).
3. In the route, call the service and convert `ValueError` to `HTTPException`.

## Summary

The service layer gives:

- **Encapsulation** — business logic in one place
- **Reuse** — same code for API and web
- **Testability** — simple unit tests
- **Flexibility** — change UI without changing logic
- **Scalability** — ready for more clients and features
