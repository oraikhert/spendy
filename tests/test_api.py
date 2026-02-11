"""
Simple script for testing the API
Run: python test_api.py
"""
import requests
import json
from typing import Dict, Any

BASE_URL = "http://localhost:8000"
API_V1 = f"{BASE_URL}/api/v1"


def print_response(response: requests.Response, title: str = "Response"):
    """Pretty-print response"""
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
    """Test health check"""
    print("\n🔍 Checking health...")
    response = requests.get(f"{BASE_URL}/health")
    print_response(response, "Health Check")
    assert response.status_code == 200


def test_register_user(email: str, username: str, password: str, full_name: str) -> Dict[str, Any]:
    """Test user registration"""
    print(f"\n📝 Registering user: {username}")
    
    data = {
        "email": email,
        "username": username,
        "password": password,
        "full_name": full_name
    }
    
    response = requests.post(f"{API_V1}/auth/register", json=data)
    print_response(response, f"Registration: {username}")
    
    if response.status_code == 201:
        print(f"✅ User {username} registered successfully!")
        return response.json()
    else:
        print(f"❌ Registration error: {response.status_code}")
        return {}


def test_login(username: str, password: str) -> str:
    """Test login"""
    print(f"\n🔐 Logging in: {username}")
    
    data = {
        "username": username,
        "password": password
    }
    
    response = requests.post(
        f"{API_V1}/auth/login",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    print_response(response, f"Login: {username}")
    
    if response.status_code == 200:
        token = response.json()["access_token"]
        print(f"✅ Login successful! Token received.")
        return token
    else:
        print(f"❌ Login error: {response.status_code}")
        return ""


def test_get_me(token: str):
    """Test getting current user data"""
    print("\n👤 Getting current user data...")
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    response = requests.get(f"{API_V1}/auth/me", headers=headers)
    print_response(response, "User data")
    
    if response.status_code == 200:
        print("✅ User data retrieved!")
        return response.json()
    else:
        print(f"❌ Error fetching data: {response.status_code}")
        return {}


def test_error_cases():
    """Test error handling"""
    print("\n🧪 Testing error handling...")
    
    # 1. Access without token
    print("\n❌ Attempting access without token...")
    response = requests.get(f"{API_V1}/auth/me")
    print(f"Status: {response.status_code} (expected 401)")
    assert response.status_code == 401, "Should return 401"
    print("✅ Correct! Access denied without token.")
    
    # 2. Login with wrong password
    print("\n❌ Attempting login with wrong password...")
    response = requests.post(
        f"{API_V1}/auth/login",
        data={"username": "testuser", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    print(f"Status: {response.status_code} (expected 401)")
    assert response.status_code == 401, "Should return 401"
    print("✅ Correct! Wrong password rejected.")


def main():
    """Main test function"""
    print("\n" + "="*60)
    print("🚀 SPENDY API TESTING")
    print("="*60)
    
    try:
        # 1. Health check
        test_health_check()
        
        # 2. User registration
        user1 = test_register_user(
            email="test@example.com",
            username="testuser",
            password="testpassword123",
            full_name="Test User"
        )
        
        # 3. Register second user
        user2 = test_register_user(
            email="john@example.com",
            username="john",
            password="john123456",
            full_name="John Doe"
        )
        
        # 4. Login
        token = test_login("testuser", "testpassword123")
        
        if token:
            # 5. Get user data
            user_data = test_get_me(token)
        
        # 6. Test error cases
        test_error_cases()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60 + "\n")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to server!")
        print("Make sure the server is running: python run.py\n")
    except AssertionError as e:
        print(f"\n❌ TEST ERROR: {e}\n")
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")


if __name__ == "__main__":
    main()
