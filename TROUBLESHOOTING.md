# Решение проблем при установке

## Проблема 1: Ошибка "externally-managed-environment"

### Симптомы
```
error: externally-managed-environment
× This environment is externally managed
```

### Причина
На macOS Python управляется через Homebrew и не позволяет устанавливать пакеты глобально.

### Решение
Используйте виртуальное окружение:

```bash
# Создать виртуальное окружение
python3 -m venv venv

# Активировать
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

**Или просто запустите**:
```bash
./install.sh
```

---

## Проблема 2: Ошибка SSL сертификатов

### Симптомы
```
SSLError(SSLCertVerificationError('OSStatus -26276'))
Could not fetch URL https://pypi.org/simple/...
```

### Причина
На macOS Python может не иметь правильно настроенных SSL сертификатов.

### Решение 1: Установка с доверенными хостами (быстро)

```bash
source venv/bin/activate
pip install --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            -r requirements.txt
```

**Или запустите**:
```bash
./install.sh
```

Скрипт автоматически определит проблему и установит с нужными флагами.

### Решение 2: Установка сертификатов (постоянное решение)

#### Вариант A: Через команду (рекомендуется)
```bash
# Для Homebrew Python
/usr/local/bin/python3 -m pip install --upgrade certifi

# Установка сертификатов
/Applications/Python\ 3.*/Install\ Certificates.command
```

#### Вариант B: Вручную
```bash
# Установить certifi
pip install --upgrade certifi

# Создать симлинк
cat << EOF > /tmp/fix_ssl.py
import ssl
import certifi

print(f"Default SSL paths: {ssl.get_default_verify_paths()}")
print(f"Certifi bundle: {certifi.where()}")
EOF

python /tmp/fix_ssl.py
```

---

## Проблема 3: Версии пакетов несовместимы с Python 3.13

### Симптомы
```
ERROR: Could not find a version that satisfies the requirement...
```

### Решение
Файл `requirements.txt` уже обновлен для использования гибких версий (`>=` вместо `==`).

Если проблема сохраняется:

```bash
# Обновите pip
pip install --upgrade pip

# Установите пакеты по одному для диагностики
pip install fastapi
pip install uvicorn[standard]
# и т.д.
```

---

## Проблема 4: Отсутствуют системные зависимости

### Симптомы
```
error: command 'gcc' failed
error: Microsoft Visual C++ 14.0 is required
```

### Решение для macOS
```bash
# Установить Xcode Command Line Tools
xcode-select --install
```

### Решение для Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install python3-dev python3-pip build-essential libpq-dev
```

### Решение для Windows
1. Установите Visual Studio Build Tools
2. Или используйте WSL2 с Ubuntu

---

## Проблема 5: Ошибка при установке psycopg2-binary

### Симптомы
```
ERROR: Failed building wheel for psycopg2-binary
```

### Решение 1: Использовать только SQLite (без PostgreSQL)

Удалите из `requirements.txt`:
```
psycopg2-binary>=2.9.9
```

### Решение 2: Установить системные зависимости

**macOS:**
```bash
brew install postgresql
```

**Linux:**
```bash
sudo apt-get install libpq-dev
```

---

## Проблема 6: Порт 8000 уже занят

### Симптомы
```
ERROR:    [Errno 48] Address already in use
```

### Решение
Измените порт в `run.py`:

```python
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,  # Изменили с 8000 на 8001
        reload=True
    )
```

Или найдите и остановите процесс:
```bash
# Найти процесс на порту 8000
lsof -i :8000

# Остановить процесс
kill -9 <PID>
```

---

## Проблема 7: Модуль не найден при запуске

### Симптомы
```
ModuleNotFoundError: No module named 'fastapi'
ModuleNotFoundError: No module named 'app'
```

### Решение
Убедитесь, что:

1. Виртуальное окружение активировано:
```bash
source venv/bin/activate
# В строке должен появиться (venv)
```

2. Вы в правильной директории:
```bash
pwd
# Должно быть: /Users/olegraikhert/Projects/spendy
```

3. Зависимости установлены:
```bash
pip list | grep fastapi
```

---

## Проблема 8: База данных не создается

### Симптомы
```
sqlite3.OperationalError: unable to open database file
```

### Решение
Проверьте права доступа:

```bash
# Проверить текущую директорию
pwd

# Проверить права
ls -la

# Дать права на запись (если нужно)
chmod +w .
```

---

## Быстрая диагностика

Запустите этот скрипт для проверки окружения:

```bash
cat << 'EOF' > check_env.sh
#!/bin/bash
echo "=== Диагностика окружения Spendy ==="
echo ""
echo "1. Python версия:"
python3 --version
echo ""
echo "2. Виртуальное окружение:"
if [ -d "venv" ]; then
    echo "✅ Найдено"
else
    echo "❌ Не найдено - запустите: python3 -m venv venv"
fi
echo ""
echo "3. Активировано ли venv:"
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✅ Активировано: $VIRTUAL_ENV"
else
    echo "❌ Не активировано - запустите: source venv/bin/activate"
fi
echo ""
echo "4. Установленные пакеты:"
pip list 2>/dev/null | grep -E "fastapi|uvicorn|sqlalchemy" || echo "❌ Пакеты не установлены"
echo ""
echo "5. Файлы проекта:"
ls -1 app/*.py 2>/dev/null | head -5 || echo "❌ Файлы не найдены"
echo ""
echo "==================================="
EOF

chmod +x check_env.sh
./check_env.sh
```

---

## Все еще не работает?

### Полная переустановка

```bash
# 1. Удалить виртуальное окружение
rm -rf venv

# 2. Удалить базу данных (если есть)
rm -f spendy.db

# 3. Очистить кеш pip
pip cache purge

# 4. Создать заново
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# 5. Установить с доверенными хостами
pip install --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            -r requirements.txt

# 6. Проверить
python run.py
```

---

## Получить помощь

Если проблема не решена:

1. Проверьте версию Python: `python3 --version` (нужна 3.10+)
2. Проверьте логи ошибок
3. Создайте issue на GitHub с:
   - Версией Python
   - Операционной системой
   - Полным текстом ошибки
   - Выводом команды `pip list`

---

## Полезные команды

```bash
# Проверка версии Python
python3 --version

# Проверка pip
pip --version

# Список установленных пакетов
pip list

# Обновление pip
pip install --upgrade pip

# Очистка кеша pip
pip cache purge

# Проверка виртуального окружения
which python

# Деактивация виртуального окружения
deactivate
```
