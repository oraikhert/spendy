# Как использовать Spendy

## 🚀 Быстрый старт

### Проверка, что сервер запущен

Откройте в браузере: http://localhost:8000/docs

Если сервер не запущен:
```bash
cd /Users/olegraikhert/Projects/spendy
./start.sh
```

---

## 📝 Использование API

### 1. Регистрация нового пользователя

**Через Swagger UI** (http://localhost:8000/docs):
1. Откройте `/api/v1/auth/register`
2. Нажмите "Try it out"
3. Заполните данные:
   ```json
   {
     "email": "your@email.com",
     "username": "yourusername",
     "password": "yourpassword",
     "full_name": "Your Name"
   }
   ```
4. Нажмите "Execute"

**Или через curl**:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your@email.com",
    "username": "yourusername",
    "password": "yourpassword",
    "full_name": "Your Name"
  }'
```

**Требования к паролю:**
- Минимум 8 символов
- Максимум 72 символа

---

### 2. Вход в систему

**Через Swagger UI**:
1. Откройте `/api/v1/auth/login`
2. Нажмите "Try it out"
3. Введите `username` и `password`
4. Нажмите "Execute"
5. Скопируйте `access_token` из ответа

**Или через curl**:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=yourusername&password=yourpassword"
```

Сохраните полученный `access_token`.

---

### 3. Авторизация в Swagger UI

1. Нажмите кнопку **"Authorize"** в правом верхнем углу Swagger UI
2. Вставьте токен в поле **Value**
3. Нажмите **"Authorize"**
4. Закройте окно

Теперь все защищенные endpoints доступны!

---

### 4. Получение профиля

**Через Swagger UI** (после авторизации):
1. Откройте `/api/v1/auth/me`
2. Нажмите "Try it out"
3. Нажмите "Execute"

**Или через curl**:
```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

---

## 🔐 Требования к данным

### Email
- Должен быть валидным email адресом
- Уникальный (не может быть зарегистрирован дважды)

### Username
- Минимум 3 символа
- Максимум 100 символов
- Уникальный

### Password
- Минимум 8 символов
- Максимум 72 символа (ограничение bcrypt)

---

## 🎯 Примеры использования

### Пример 1: Полный цикл авторизации

```bash
# 1. Регистрация
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "password123",
    "full_name": "Test User"
  }'

# 2. Вход
TOKEN=$(curl -s -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=password123" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# 3. Получение профиля
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer $TOKEN"
```

### Пример 2: Через Python

```python
import requests

BASE_URL = "http://localhost:8000/api/v1"

# Регистрация
register_data = {
    "email": "user@example.com",
    "username": "user",
    "password": "password123",
    "full_name": "User Name"
}
response = requests.post(f"{BASE_URL}/auth/register", json=register_data)
print("Регистрация:", response.json())

# Вход
login_data = {
    "username": "user",
    "password": "password123"
}
response = requests.post(
    f"{BASE_URL}/auth/login",
    data=login_data,
    headers={"Content-Type": "application/x-www-form-urlencoded"}
)
token = response.json()["access_token"]
print("Токен получен!")

# Получение профиля
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(f"{BASE_URL}/auth/me", headers=headers)
print("Профиль:", response.json())
```

---

## ❌ Возможные ошибки

### 400 Bad Request - "Email already registered"
Пользователь с таким email уже существует. Используйте другой email.

### 400 Bad Request - "Username already taken"
Пользователь с таким username уже существует. Используйте другой username.

### 401 Unauthorized - "Incorrect username or password"
Неверный username или пароль при входе.

### 401 Unauthorized - "Could not validate credentials"
Невалидный или истекший токен. Выполните вход заново.

### 400 Bad Request - "Inactive user"
Пользователь деактивирован. Обратитесь к администратору.

---

## 💡 Полезные советы

### 1. Срок действия токена
JWT токен действителен **30 минут**. После истечения нужно войти заново.

### 2. Вход по email
Можно входить как по username, так и по email:
```bash
# По username
username=myusername&password=mypassword

# По email
username=my@email.com&password=mypassword
```

### 3. Просмотр всей документации
Swagger UI: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc

### 4. Тестирование без curl
Используйте файл `api_examples.http` в VSCode с расширением REST Client.

---

## 🧪 Запуск тестов

```bash
cd /Users/olegraikhert/Projects/spendy
source venv/bin/activate
python test_api.py
```

Все тесты должны пройти успешно.

---

## 🛑 Остановка сервера

```bash
# Нажмите Ctrl+C в терминале, где запущен сервер

# Или принудительно остановите
pkill -f "python run.py"
```

---

## 📚 Дополнительная документация

- `README.md` - Полная документация проекта
- `TROUBLESHOOTING.md` - Решение проблем
- `FIXES_LOG.md` - История исправлений
- `QUICK_COMMANDS.txt` - Быстрые команды

---

**Приятного использования!** 🚀
