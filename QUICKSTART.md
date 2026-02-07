# Быстрый старт

## 1. Установка зависимостей

```bash
python -m venv venv
source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
```

## 2. Запуск приложения

```bash
python run.py
```

или

```bash
uvicorn app.main:app --reload
```

## 3. Открыть документацию API

http://localhost:8000/docs

## 4. Тестирование API

### Регистрация пользователя

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

### Вход в систему

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=testpassword123"
```

Сохраните полученный `access_token`.

### Получить данные текущего пользователя

```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"
```

## Что реализовано

✅ Базовая структура FastAPI приложения
✅ Асинхронная работа с SQLite через SQLAlchemy
✅ Модель пользователя (User)
✅ Регистрация пользователей
✅ Вход в систему (JWT токены)
✅ Защищенные эндпоинты (требуют авторизации)
✅ Хеширование паролей (bcrypt)
✅ Валидация данных (Pydantic)
✅ Документация API (Swagger/ReDoc)
✅ Готовность к переходу на PostgreSQL

## Следующие шаги

1. Добавить модели для транзакций и категорий
2. Реализовать CRUD операции для бюджета
3. Добавить функционал семейных групп
4. Создать отчеты и аналитику
5. Разработать frontend
