# Spendy - Family Budget Tracking Application

Приложение для отслеживания семейного бюджета, построенное на FastAPI.

## Технологический стек

- **Backend**: FastAPI
- **Database**: SQLite (с возможностью миграции на PostgreSQL)
- **ORM**: SQLAlchemy 2.0 (async)
- **Authentication**: JWT tokens
- **Password Hashing**: bcrypt

## Быстрый старт

```bash
python -m venv venv
source venv/bin/activate   # Mac/Linux; на Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # опционально
python run.py
```

Или через скрипты: `./install.sh` (установка), затем `./start.sh` (запуск). Документация API: http://localhost:8000/docs

При проблемах с установкой см. [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Структура проекта

```
spendy/
├── app/
│   ├── main.py              # Главный файл приложения
│   ├── config.py            # Конфигурация приложения
│   ├── database.py          # Настройка базы данных
│   ├── models/              # SQLAlchemy модели (таблицы БД)
│   ├── schemas/             # Pydantic схемы (валидация)
│   ├── services/            # Сервисный слой (бизнес-логика)
│   │   ├── user_service.py  # CRUD операции с пользователями
│   │   └── auth_service.py  # Аутентификация и токены
│   ├── api/v1/              # API роуты (JSON responses)
│   └── core/                # Утилиты (security, deps)
├── docs/                    # Документация (архитектура, миграции, решение проблем)
├── alembic/                 # Миграции БД
├── requirements.txt
├── run.py
└── README.md
```

### Архитектура

Приложение использует **многослойную архитектуру с сервисным слоем**:

```
API Routes (JSON) → Services (бизнес-логика) → Models (БД)
```

**Преимущества:**
- Бизнес-логика отделена от HTTP слоя
- Один сервисный слой может использоваться разными клиентами (API, веб-страницы, мобильные приложения)
- Легко тестировать сервисы независимо от HTTP
- Готовность к добавлению Jinja2+HTMX или SPA в будущем

Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Установка и запуск

### 1. Виртуальное окружение и зависимости

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

При ошибке SSL (macOS): `pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -r requirements.txt` или используйте `./install.sh`.

### 2. Настройка окружения

```bash
cp .env.example .env
```

Для продакшена смените `SECRET_KEY` (например: `python -c "import secrets; print(secrets.token_hex(32))"`).

### 3. Запуск

```bash
python run.py
# или
uvicorn app.main:app --reload
```

Приложение: http://localhost:8000  
Swagger: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc

## API Endpoints

### Авторизация

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/v1/auth/register` | Регистрация |
| POST | `/api/v1/auth/login` | Вход (получение JWT) |
| GET | `/api/v1/auth/me` | Текущий пользователь (нужен токен) |

**Регистрация** — JSON: `email`, `username`, `password` (мин. 8 символов), `full_name` (опционально).  
**Вход** — form-data: `username` (или email), `password`. Ответ: `access_token`, `token_type: "bearer"`.  
**Профиль** — заголовок: `Authorization: Bearer <access_token>`.

## Использование API

### Через Swagger UI (http://localhost:8000/docs)

1. **Регистрация**: POST `/api/v1/auth/register` → «Try it out» → введите данные → «Execute».
2. **Вход**: POST `/api/v1/auth/login` → введите username и password → «Execute» → скопируйте `access_token`.
3. **Авторизация**: кнопка «Authorize» → вставьте токен в поле Value → «Authorize».
4. **Профиль**: GET `/api/v1/auth/me` → «Try it out» → «Execute».

### Требования к данным

- **Email** — валидный адрес, уникальный.
- **Username** — 3–100 символов, уникальный.
- **Password** — 8–72 символа.

### Полный цикл (bash)

```bash
# Регистрация
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "username": "testuser", "password": "testpassword123", "full_name": "Test User"}'

# Вход и сохранение токена
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=testpassword123" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Профиль
curl -X GET "http://localhost:8000/api/v1/auth/me" -H "Authorization: Bearer $TOKEN"
```

### Пример на Python

```python
import requests
BASE = "http://localhost:8000/api/v1"
requests.post(f"{BASE}/auth/register", json={"email": "u@ex.com", "username": "u", "password": "password123", "full_name": "User"})
r = requests.post(f"{BASE}/auth/login", data={"username": "u", "password": "password123"}, headers={"Content-Type": "application/x-www-form-urlencoded"})
token = r.json()["access_token"]
print(requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"}).json())
```

### Возможные ошибки API

- **400** «Email already registered» / «Username already taken» — смените email или username.
- **401** «Incorrect username or password» — неверные учётные данные.
- **401** «Could not validate credentials» — неверный или истёкший токен, войдите снова.
- **400** «Inactive user» — пользователь деактивирован.

### Полезные советы

- JWT действует 30 минут (настраивается в `.env`).
- Вход возможен по **username** или по **email** в поле `username`.
- Примеры запросов также в файле `api_examples.http` (REST Client в VS Code).

## Часто задаваемые вопросы

- **Как остановить сервер?** — `Ctrl+C` в терминале.
- **Где хранятся данные?** — В файле `spendy.db` (SQLite) в корне проекта.
- **Как сбросить БД?** — Остановите сервер, выполните `rm spendy.db`, при следующем запуске БД создастся заново.
- **Примеры запросов?** — `api_examples.http` или Swagger UI.
- **Запуск тестов:** 
  1. `pip install -r requirements-dev.txt` (установка test зависимостей)
  2. `python test_api.py` (в каталоге проекта с активированным venv)

## Переход с SQLite на PostgreSQL

1. Создайте БД в PostgreSQL.
2. В `.env`: `DATABASE_URL=postgresql+asyncpg://user:password@localhost/spendy`
3. `pip install asyncpg`
4. Перезапустите приложение (или примените миграции: см. [docs/MIGRATIONS.md](docs/MIGRATIONS.md)).

## Безопасность

- Пароли хешируются с bcrypt.
- JWT для аутентификации, срок жизни настраивается в `.env`.
- В продакшене: HTTPS, свой `SECRET_KEY`, ограничьте CORS в `app/main.py`.

## Дальнейшее развитие

1. Миграции БД (Alembic) — см. [docs/MIGRATIONS.md](docs/MIGRATIONS.md).
2. Модели бюджета — транзакции, категории, счета.
3. API для доходов/расходов.
4. Семейные группы и совместный бюджет.
5. Отчёты и аналитика.
6. Уведомления (напоминания, превышение бюджета).
7. Frontend (React/Vue).

## Документация

| Файл | Описание |
|------|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура и дизайн приложения |
| [docs/SERVICE_LAYER.md](docs/SERVICE_LAYER.md) | Сервисный слой: структура, использование, примеры |
| [docs/MIGRATIONS.md](docs/MIGRATIONS.md) | Работа с миграциями Alembic |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Решение проблем при установке и запуске |

## Лицензия

MIT
