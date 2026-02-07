# Spendy - Family Budget Tracking Application

Приложение для отслеживания семейного бюджета, построенное на FastAPI.

## Технологический стек

- **Backend**: FastAPI
- **Database**: SQLite (с возможностью миграции на PostgreSQL)
- **ORM**: SQLAlchemy 2.0 (async)
- **Authentication**: JWT tokens
- **Password Hashing**: bcrypt via passlib

## Структура проекта

```
spendy/
├── app/
│   ├── __init__.py
│   ├── main.py              # Главный файл приложения
│   ├── config.py            # Конфигурация приложения
│   ├── database.py          # Настройка базы данных
│   ├── models/              # SQLAlchemy модели
│   │   ├── __init__.py
│   │   └── user.py          # Модель пользователя
│   ├── schemas/             # Pydantic схемы
│   │   ├── __init__.py
│   │   └── user.py          # Схемы пользователя
│   ├── api/                 # API роуты
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── auth.py      # Эндпоинты авторизации
│   └── core/                # Базовые утилиты
│       ├── __init__.py
│       ├── security.py      # Работа с паролями и JWT
│       └── deps.py          # Зависимости для роутов
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Установка и запуск

### 1. Создание виртуального окружения

```bash
python -m venv venv
source venv/bin/activate  # Для Linux/Mac
# или
venv\Scripts\activate  # Для Windows
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка окружения

Скопируйте `.env.example` в `.env` и настройте параметры:

```bash
cp .env.example .env
```

**Важно:** Измените `SECRET_KEY` в `.env` на безопасный ключ для продакшена:

```bash
# Генерация безопасного ключа
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Запуск приложения

```bash
uvicorn app.main:app --reload
```

Приложение будет доступно по адресу: http://localhost:8000

- **Документация API (Swagger)**: http://localhost:8000/docs
- **Альтернативная документация (ReDoc)**: http://localhost:8000/redoc

## API Endpoints

### Авторизация

#### Регистрация нового пользователя

```bash
POST /api/v1/auth/register
```

**Request Body:**
```json
{
  "email": "user@example.com",
  "username": "username",
  "password": "securepassword123",
  "full_name": "John Doe"
}
```

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "username",
  "full_name": "John Doe",
  "is_active": true,
  "is_superuser": false,
  "created_at": "2026-02-06T10:00:00",
  "updated_at": "2026-02-06T10:00:00"
}
```

#### Вход (получение токена)

```bash
POST /api/v1/auth/login
```

**Request Body (form-data):**
- username: `username` или `user@example.com`
- password: `securepassword123`

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### Получение информации о текущем пользователе

```bash
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "username",
  "full_name": "John Doe",
  "is_active": true,
  "is_superuser": false,
  "created_at": "2026-02-06T10:00:00",
  "updated_at": "2026-02-06T10:00:00"
}
```

## Примеры использования с curl

### Регистрация

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "testpassword123",
    "full_name": "Test User"
  }'
```

### Вход

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=testpassword123"
```

### Получение информации о пользователе

```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Переход с SQLite на PostgreSQL

Для использования PostgreSQL вместо SQLite:

1. Установите PostgreSQL и создайте базу данных
2. Измените `DATABASE_URL` в `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost/spendy
```

3. Установите дополнительные зависимости:

```bash
pip install asyncpg
```

4. Перезапустите приложение - таблицы будут созданы автоматически

## Безопасность

- Пароли хешируются с использованием bcrypt
- JWT токены для аутентификации
- Токены истекают через 30 минут (настраивается в `.env`)
- Используйте HTTPS в продакшене
- Измените `SECRET_KEY` на случайную строку в продакшене
- Настройте CORS для конкретных доменов в `app/main.py`

## Дальнейшее развитие

Следующие шаги для развития приложения:

1. **Миграции базы данных** - настройка Alembic для управления миграциями
2. **Модели бюджета** - создание моделей для транзакций, категорий, бюджетов
3. **API для бюджета** - эндпоинты для управления доходами/расходами
4. **Семейные группы** - функционал для совместного управления бюджетом
5. **Отчеты и аналитика** - визуализация данных
6. **Уведомления** - напоминания о платежах и превышении бюджета
7. **Frontend** - веб-интерфейс на React/Vue

## Лицензия

MIT
