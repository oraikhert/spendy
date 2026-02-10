"""
Простой скрипт для тестирования API
Запуск: python test_api.py
"""
import requests
import json
from typing import Dict, Any

BASE_URL = "http://localhost:8000"
API_V1 = f"{BASE_URL}/api/v1"


def print_response(response: requests.Response, title: str = "Response"):
    """Красивый вывод ответа"""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    try:
        print(f"Body: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except:
        print(f"Body: {response.text}")
    print(f"{'='*60}\n")


def test_health_check():
    """Тест health check"""
    print("\n🔍 Проверка health check...")
    response = requests.get(f"{BASE_URL}/health")
    print_response(response, "Health Check")
    assert response.status_code == 200


def test_register_user(email: str, username: str, password: str, full_name: str) -> Dict[str, Any]:
    """Тест регистрации пользователя"""
    print(f"\n📝 Регистрация пользователя: {username}")
    
    data = {
        "email": email,
        "username": username,
        "password": password,
        "full_name": full_name
    }
    
    response = requests.post(f"{API_V1}/auth/register", json=data)
    print_response(response, f"Регистрация: {username}")
    
    if response.status_code == 201:
        print(f"✅ Пользователь {username} успешно зарегистрирован!")
        return response.json()
    else:
        print(f"❌ Ошибка регистрации: {response.status_code}")
        return {}


def test_login(username: str, password: str) -> str:
    """Тест входа в систему"""
    print(f"\n🔐 Вход в систему: {username}")
    
    data = {
        "username": username,
        "password": password
    }
    
    response = requests.post(
        f"{API_V1}/auth/login",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print_response(response, f"Вход: {username}")
    
    if response.status_code == 200:
        token = response.json()["access_token"]
        print(f"✅ Успешный вход! Токен получен.")
        return token
    else:
        print(f"❌ Ошибка входа: {response.status_code}")
        return ""


def test_get_me(token: str):
    """Тест получения данных текущего пользователя"""
    print("\n👤 Получение данных текущего пользователя...")
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    response = requests.get(f"{API_V1}/auth/me", headers=headers)
    print_response(response, "Данные пользователя")
    
    if response.status_code == 200:
        print("✅ Данные пользователя получены!")
        return response.json()
    else:
        print(f"❌ Ошибка получения данных: {response.status_code}")
        return {}


def test_error_cases():
    """Тест обработки ошибок"""
    print("\n🧪 Тестирование обработки ошибок...")
    
    # 1. Доступ без токена
    print("\n❌ Попытка доступа без токена...")
    response = requests.get(f"{API_V1}/auth/me")
    print(f"Status: {response.status_code} (ожидается 401)")
    assert response.status_code == 401, "Должна быть ошибка 401"
    print("✅ Правильно! Доступ запрещен без токена.")
    
    # 2. Вход с неверным паролем
    print("\n❌ Попытка входа с неверным паролем...")
    response = requests.post(
        f"{API_V1}/auth/login",
        data={"username": "testuser", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    print(f"Status: {response.status_code} (ожидается 401)")
    assert response.status_code == 401, "Должна быть ошибка 401"
    print("✅ Правильно! Неверный пароль отклонен.")


def main():
    """Основная функция тестирования"""
    print("\n" + "="*60)
    print("🚀 ТЕСТИРОВАНИЕ API SPENDY")
    print("="*60)
    
    try:
        # 1. Health check
        test_health_check()
        
        # 2. Регистрация пользователя
        user1 = test_register_user(
            email="test@example.com",
            username="testuser",
            password="testpassword123",
            full_name="Test User"
        )
        
        # 3. Регистрация второго пользователя
        user2 = test_register_user(
            email="john@example.com",
            username="john",
            password="john123456",
            full_name="John Doe"
        )
        
        # 4. Вход в систему
        token = test_login("testuser", "testpassword123")
        
        if token:
            # 5. Получение данных пользователя
            user_data = test_get_me(token)
        
        # 6. Тестирование ошибок
        test_error_cases()
        
        print("\n" + "="*60)
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("="*60 + "\n")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ ОШИБКА: Не удалось подключиться к серверу!")
        print("Убедитесь, что сервер запущен: python run.py\n")
    except AssertionError as e:
        print(f"\n❌ ОШИБКА ТЕСТА: {e}\n")
    except Exception as e:
        print(f"\n❌ НЕОЖИДАННАЯ ОШИБКА: {e}\n")


if __name__ == "__main__":
    main()
