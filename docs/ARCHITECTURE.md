# Архитектура приложения Spendy

## Структура проекта

```
spendy/
├── app/
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py            # Конфигурация (settings)
│   ├── database.py          # Настройка БД и сессий
│   │
│   ├── models/              # SQLAlchemy модели
│   │   └── user.py          # Модель User
│   │
│   ├── schemas/             # Pydantic схемы (валидация)
│   │   └── user.py          # Схемы для User
│   │
│   ├── services/            # Сервисный слой (бизнес-логика)
│   │   ├── user_service.py  # CRUD операции с пользователями
│   │   └── auth_service.py  # Аутентификация и токены
│   │
│   ├── api/v1/              # API эндпоинты версии 1
│   │   └── auth.py          # Авторизация (register, login, me)
│   │
│   └── core/                # Основные утилиты
│       ├── security.py      # JWT, хеширование паролей
│       └── deps.py          # Зависимости для endpoints
│
├── requirements.txt         # Python зависимости
├── .env                     # Переменные окружения
└── run.py                   # Скрипт запуска
```

## Схема базы данных

### Таблица: users

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

## Диаграмма потока авторизации (с сервисным слоем)

### Регистрация пользователя

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /api/v1/auth/register
       │ {email, username, password}
       ▼
┌──────────────────────┐
│  API: auth.register  │
│  (обработка HTTP)    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Service:             │
│ user_service         │
│ .create_user()       │──► Проверка email (уникальность)
│                      │──► Проверка username (уникальность)
│                      │──► Хеширование пароля
│                      │──► Создание User в БД
│                      │──► Commit транзакции
└──────────┬───────────┘
           │
           │ User object / ValueError
           ▼
┌──────────────────────┐
│  API: auth.register  │──► Преобразование в HTTP статус
└──────────┬───────────┘
           │
           │ 201 Created / 400 Bad Request
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

### Вход пользователя

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /api/v1/auth/login
       │ {username, password}
       ▼
┌──────────────────────┐
│  API: auth.login     │
│  (обработка HTTP)    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Service:             │
│ auth_service         │
│ .authenticate_user() │──► Поиск по username или email
│                      │──► Проверка пароля (bcrypt)
│                      │──► Проверка is_active
└──────────┬───────────┘
           │ User object / ValueError
           ▼
┌──────────────────────┐
│ Service:             │
│ auth_service         │
│ .create_user_access  │──► Создание JWT payload
│ _token()             │──► Генерация токена
└──────────┬───────────┘
           │ Token object
           ▼
┌──────────────────────┐
│  API: auth.login     │──► Преобразование в HTTP ответ
└──────────┬───────────┘
           │
           │ {access_token, token_type}
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

### Получение профиля

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ GET /api/v1/auth/me
       │ Authorization: Bearer <token>
       ▼
┌──────────────────────┐
│  API: auth.me        │
│                      │
│  Dependency:         │
│  get_current_active  │──► Декодирование JWT
│  _user()             │──► Извлечение user_id
│                      │──► user_service.get_user_by_id()
│                      │──► Проверка is_active
└──────────┬───────────┘
           │
           │ User object
           ▼
┌─────────────┐
│   Client    │
└─────────────┘
```

## Компоненты безопасности

### 1. Хеширование паролей (bcrypt)

```python
passlib.context.CryptContext(schemes=["bcrypt"])
```

- Надежное одностороннее хеширование
- Соль автоматически генерируется и сохраняется
- Защита от rainbow table атак

### 2. JWT токены (JSON Web Tokens)

```python
jose.jwt.encode(data, SECRET_KEY, algorithm="HS256")
```

**Структура токена:**
```json
{
  "sub": 1,              // user_id
  "username": "user",    // username
  "exp": 1234567890      // время истечения
}
```

**Параметры:**
- `SECRET_KEY`: Секретный ключ для подписи (из .env)
- `ALGORITHM`: HS256 (HMAC with SHA-256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: 30 минут (настраиваемо)

### 3. OAuth2 Password Flow

Используется стандартная схема OAuth2 с password bearer:

```python
OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
```

## Архитектура приложения

### Текущая архитектура с сервисным слоем

```mermaid
graph TD
    Client[Client/Frontend]
    API[API Routes<br/>JSON responses]
    Pages[Page Routes<br/>Jinja2+HTMX HTML<br/>будущее]
    Services[Service Layer<br/>Business Logic]
    DB[(Database<br/>SQLite/PostgreSQL)]
    Security[Core Security<br/>JWT, Password Hashing]
    
    Client --> API
    Client -.->|будущее| Pages
    API --> Services
    Pages -.->|будущее| Services
    Services --> DB
    Services --> Security
    
    style Pages fill:#f9f,stroke:#333,stroke-dasharray: 5 5
```

**Преимущества архитектуры:**
- Бизнес-логика не дублируется
- API роуты возвращают JSON
- Страничные роуты (будущие) будут возвращать HTML
- SPA (будущее) будет использовать существующий API
- Простая миграция между UI технологиями

### Слои приложения

```
┌─────────────────────────────────────────┐
│        Presentation Layer               │
│  ┌────────────────────────────────────┐ │
│  │  API Routes (/api/v1/*)            │ │ ◄── JSON responses
│  │  Page Routes (будущее)             │ │ ◄── HTML responses
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Service Layer (НОВЫЙ!)          │
│  ┌────────────────────────────────────┐ │
│  │  user_service.py                   │ │
│  │   • create_user()                  │ │
│  │   • get_user_by_id()               │ │
│  │   • get_user_by_email()            │ │
│  │   • update_user()                  │ │
│  │                                    │ │
│  │  auth_service.py                   │ │
│  │   • authenticate_user()            │ │
│  │   • create_user_access_token()     │ │
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Data Access Layer               │
│  ┌────────────────────────────────────┐ │
│  │  SQLAlchemy Models                 │ │
│  │  Async Sessions                    │ │
│  │  Query Building                    │ │
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│            Database Layer               │
│  ┌────────────────────────────────────┐ │
│  │  SQLite (dev)                      │ │
│  │  PostgreSQL (production)           │ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Разделение ответственности

#### 1. API Routes (app/api/v1/)
**Ответственность:**
- Приём и валидация HTTP запросов
- Вызов функций сервисного слоя
- Преобразование исключений в HTTP статусы
- Формирование JSON ответов

**Пример:**
```python
@router.post("/register")
async def register(user_in: UserCreate, db: AsyncSession):
    try:
        user = await user_service.create_user(user_in, db)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

#### 2. Service Layer (app/services/) - НОВЫЙ СЛОЙ
**Ответственность:**
- Бизнес-логика приложения
- Проверка уникальности данных
- Валидация бизнес-правил
- Работа с несколькими моделями
- Возврат доменных объектов или ошибок (ValueError)

**Пример:**
```python
async def create_user(user_in: UserCreate, db: AsyncSession) -> User:
    # Проверка уникальности email
    if await get_user_by_email(user_in.email, db):
        raise ValueError("Email already registered")
    
    # Создание пользователя
    db_user = User(...)
    db.add(db_user)
    await db.commit()
    return db_user
```

**Функции сервисного слоя:**

`user_service.py`:
- `get_user_by_id()` - получение по ID
- `get_user_by_email()` - получение по email
- `get_user_by_username()` - получение по username
- `get_user_by_username_or_email()` - гибкий поиск
- `create_user()` - создание с валидацией
- `update_user()` - обновление с проверками

`auth_service.py`:
- `authenticate_user()` - проверка credentials
- `create_user_access_token()` - генерация JWT

#### 3. Models (app/models/)
**Ответственность:**
- Определение структуры таблиц БД
- Связи между таблицами
- Индексы и ограничения

#### 4. Core Utilities (app/core/)
**Ответственность:**
- security.py: криптография, JWT
- deps.py: FastAPI dependencies

## Зависимости (dependencies)

Цепочка зависимостей для защищенных эндпоинтов:

```
get_current_active_user
        │
        ├──► get_current_user
        │           │
        │           ├──► oauth2_scheme (извлекает токен)
        │           └──► get_db (сессия БД)
        │
        └──► Проверка is_active
```

## Переход на PostgreSQL

Для переключения на PostgreSQL нужно:

1. Изменить `DATABASE_URL` в `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@localhost/spendy
   ```

2. Установить драйвер:
   ```bash
   pip install asyncpg
   ```

3. Код остается неизменным благодаря абстракции SQLAlchemy

## Будущие расширения

### Путь миграции UI

**Текущее состояние:**
- ✅ API роуты (JSON)
- ✅ Сервисный слой

**Этап 1: MVP с Jinja2 + HTMX**
```python
# app/pages/auth.py (будущее)
@router.post("/register")
async def register_page(user_in: UserCreate, db: AsyncSession):
    try:
        user = await user_service.create_user(user_in, db)
        return templates.TemplateResponse("success.html", {...})
    except ValueError as e:
        return templates.TemplateResponse("register.html", {"error": e})
```
- API роуты остаются для мобильных приложений
- Страничные роуты для веб-интерфейса
- Один сервисный слой для обоих

**Этап 2: Миграция на SPA (React/Vue)**
- Удаляем `app/pages/` и шаблоны
- API роуты остаются без изменений
- Сервисный слой остаётся без изменений
- SPA использует существующий API

### Планируемые модели:

- **Transaction** - операции (доходы/расходы)
- **Category** - категории операций
- **Budget** - бюджеты по категориям
- **Family** - семейные группы
- **Account** - счета (наличные, карты, и т.д.)

### Планируемые сервисы:

- `transaction_service.py` - работа с транзакциями
- `category_service.py` - управление категориями
- `budget_service.py` - управление бюджетами
- `family_service.py` - управление семейными группами
- `report_service.py` - генерация отчётов

### Планируемые API эндпоинты:

- `/api/v1/transactions` - управление транзакциями
- `/api/v1/categories` - управление категориями
- `/api/v1/budgets` - управление бюджетами
- `/api/v1/families` - управление семейными группами
- `/api/v1/reports` - отчеты и аналитика

## Преимущества сервисного слоя

1. **Переиспользование кода** - логика написана один раз, используется везде
2. **Тестируемость** - сервисы легко тестировать без HTTP слоя
3. **Гибкость UI** - легко менять presentation layer без изменения логики
4. **Чистота роутов** - роуты занимаются только HTTP, не бизнес-логикой
5. **Масштабируемость** - легко добавлять новые типы клиентов (API, веб, мобильные)
6. **Независимость от фреймворка** - бизнес-логика не привязана к FastAPI
