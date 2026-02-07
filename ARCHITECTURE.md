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

## Диаграмма потока авторизации

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ POST /api/v1/auth/register
       │ {email, username, password}
       ▼
┌──────────────────┐
│  auth.register   │──► Проверка существования
│                  │──► Хеширование пароля
│                  │──► Создание User в БД
└────────┬─────────┘
         │
         │ 201 Created
         ▼
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       │ POST /api/v1/auth/login
       │ {username, password}
       ▼
┌──────────────────┐
│   auth.login     │──► Поиск пользователя
│                  │──► Проверка пароля
│                  │──► Создание JWT токена
└────────┬─────────┘
         │
         │ {access_token, token_type}
         ▼
┌─────────────┐
│   Client    │──► Сохранение токена
└──────┬──────┘
       │
       │ GET /api/v1/auth/me
       │ Authorization: Bearer <token>
       ▼
┌──────────────────┐
│   auth.me        │
│                  │
│ ┌──────────────┐ │
│ │get_current   │ │──► Декодирование JWT
│ │_active_user  │ │──► Извлечение user_id
│ └──────────────┘ │──► Загрузка User из БД
└────────┬─────────┘──► Проверка is_active
         │
         │ User data
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

## Слои приложения

```
┌─────────────────────────────────────────┐
│          API Layer (FastAPI)            │
│  ┌────────────────────────────────────┐ │
│  │  Роуты (/api/v1/auth/*)            │ │
│  └────────────────────────────────────┘ │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│       Business Logic Layer              │
│  ┌────────────────────────────────────┐ │
│  │  Валидация (Pydantic Schemas)      │ │
│  │  Аутентификация (JWT)              │ │
│  │  Авторизация (dependencies)        │ │
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

### Планируемые модели:

- **Transaction** - операции (доходы/расходы)
- **Category** - категории операций
- **Budget** - бюджеты по категориям
- **Family** - семейные группы
- **Account** - счета (наличные, карты, и т.д.)

### Планируемые API эндпоинты:

- `/api/v1/transactions` - управление транзакциями
- `/api/v1/categories` - управление категориями
- `/api/v1/budgets` - управление бюджетами
- `/api/v1/families` - управление семейными группами
- `/api/v1/reports` - отчеты и аналитика
