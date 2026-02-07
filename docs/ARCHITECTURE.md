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
│   ├── api/v1/              # API эндпоинты версии 1 (JSON)
│   │   └── auth.py          # Авторизация (register, login, me)
│   │
│   ├── web/                 # Веб-эндпоинты (HTML)
│   │   ├── auth.py          # Страницы авторизации/регистрации
│   │   └── pages.py         # Остальные страницы (dashboard и т.д.)
│   │
│   ├── templates/           # Jinja2 шаблоны
│   │   ├── base.html        # Базовый шаблон
│   │   ├── auth/            # Шаблоны авторизации
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   └── dashboard.html   # Панель пользователя
│   │
│   ├── static/              # Статические файлы
│   │   └── css/             # CSS файлы
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

**Преимущества архитектуры:**
- Бизнес-логика не дублируется между API и веб-страницами
- API роуты возвращают JSON для мобильных и внешних клиентов
- Веб-страницы используют Jinja2+HTMX для интерактивного UI
- Один сервисный слой обслуживает оба типа клиентов
- Простая миграция на SPA в будущем без изменения сервисов

### Слои приложения

```
┌─────────────────────────────────────────┐
│        Presentation Layer               │
│  ┌────────────────────────────────────┐ │
│  │  API Routes (/api/v1/*)            │ │ ◄── JSON responses
│  │  Web Routes (/auth/*, /dashboard)  │ │ ◄── HTML responses (Jinja2+HTMX)
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│         Service Layer                   │
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
- Аутентификация через Bearer токены

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

#### 1a. Web Routes (app/web/)
**Ответственность:**
- Отображение HTML страниц через Jinja2 шаблоны
- Обработка форм с HTMX
- Вызов тех же функций сервисного слоя
- Аутентификация через HTTP-only cookies
- Формирование HTML ответов или HTMX-заголовков

**Пример:**
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
        
        # HTMX redirect через заголовок
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/dashboard"
        response.set_cookie(key="access_token", value=token.access_token, httponly=True)
        return response
    except ValueError as e:
        # Возврат HTML фрагмента с ошибкой
        return HTMLResponse(content=f'<div class="alert alert-error">{e}</div>')
```

**Технологии:**
- **Jinja2** - серверный рендеринг шаблонов
- **HTMX** - асинхронная отправка форм без перезагрузки
- **Tailwind CSS** - утилитарные CSS классы
- **DaisyUI** - компоненты UI на базе Tailwind

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
- security.py: криптография, JWT, хеширование паролей
- deps.py: FastAPI dependencies для API и веб-страниц

**Типы аутентификации:**
- `get_current_user()` - для API (Bearer токен из заголовка)
- `get_current_user_from_cookie()` - для веб-страниц (JWT из HTTP-only cookie)
- `get_current_user_from_cookie_required()` - для защищенных веб-страниц

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

## Реализованный веб-интерфейс

### Jinja2 + HTMX + Tailwind + DaisyUI

**Текущее состояние:**
- ✅ API роуты (JSON) - для мобильных и внешних клиентов
- ✅ Веб-роуты (HTML) - для браузерных пользователей
- ✅ Сервисный слой - единый для обоих

**Веб-страницы (app/web/):**
```python
# app/web/auth.py
@router.post("/login")
async def login_post(username: str = Form(...), password: str = Form(...), ...):
    user = await auth_service.authenticate_user(username, password, db)
    token = await auth_service.create_user_access_token(user)
    
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/dashboard"  # HTMX редирект
    response.set_cookie(key="access_token", value=token.access_token, httponly=True)
    return response
```

**Особенности:**
- HTMX отправляет формы асинхронно
- Сервер возвращает HTML фрагменты или заголовки редиректа
- JWT хранится в HTTP-only cookie (защита от XSS)
- API и веб-интерфейс используют один сервисный слой
- Не требуется дублирование бизнес-логики

### Будущие расширения

**Этап 1: Расширение веб-интерфейса**
- Добавить страницы для транзакций
- Страницы отчетов и аналитики
- Страницы настроек профиля
- Управление семейными группами

**Этап 2: Возможная миграция на SPA (React/Vue)**
- Удаляем `app/web/` и шаблоны
- API роуты остаются без изменений
- Сервисный слой остаётся без изменений
- SPA использует существующий API
- Нулевое изменение бизнес-логики

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
