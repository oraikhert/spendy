# Управление миграциями базы данных

Проект использует Alembic для управления схемой базы данных.

## Быстрый старт

### Первоначальная настройка (уже выполнена)

```bash
alembic init alembic
```

### Создание первой миграции

После того как вы определили модели в `app/models/`, создайте миграцию:

```bash
alembic revision --autogenerate -m "Initial migration: create users table"
```

### Применение миграций

```bash
alembic upgrade head
```

## Основные команды

### Создание новой миграции

После изменения моделей:

```bash
alembic revision --autogenerate -m "описание изменений"
```

Пример:
```bash
alembic revision --autogenerate -m "Add transactions table"
```

### Применение всех миграций

```bash
alembic upgrade head
```

### Откат последней миграции

```bash
alembic downgrade -1
```

### Откат к конкретной версии

```bash
alembic downgrade <revision_id>
```

### Откат всех миграций

```bash
alembic downgrade base
```

### Просмотр истории миграций

```bash
alembic history
```

### Текущая версия базы данных

```bash
alembic current
```

### Просмотр SQL без применения

```bash
alembic upgrade head --sql
```

## Рабочий процесс

1. **Изменяете модели** в `app/models/`
2. **Создаете миграцию**: `alembic revision --autogenerate -m "описание"`
3. **Проверяете миграцию** в `alembic/versions/`
4. **Применяете миграцию**: `alembic upgrade head`

## Важные замечания

### Проверяйте автогенерированные миграции

Alembic автоматически генерирует миграции, но не всегда идеально. Всегда проверяйте:

- Правильность типов данных
- Индексы и ограничения
- Значения по умолчанию
- Nullable/Not Nullable

### Данные при миграции

Если миграция влияет на существующие данные:

```python
def upgrade() -> None:
    # Добавляем колонку как nullable
    op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))
    
    # Заполняем существующие записи
    op.execute("UPDATE users SET phone = '' WHERE phone IS NULL")
    
    # Делаем колонку NOT NULL
    op.alter_column('users', 'phone', nullable=False)
```

### SQLite ограничения

SQLite имеет ограничения на ALTER TABLE:
- Не поддерживает DROP COLUMN (до версии 3.35.0)
- Ограниченная поддержка ALTER COLUMN
- Может потребоваться пересоздание таблицы

Для SQLite может понадобиться:

```python
def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('new_field', sa.String(50)))
```

## Переход на PostgreSQL

При переходе на PostgreSQL:

1. Создайте базу данных в PostgreSQL
2. Измените `DATABASE_URL` в `.env`
3. Запустите миграции: `alembic upgrade head`

База данных будет создана с актуальной схемой.

## Пример миграции

```python
"""Add email verification

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2026-02-06 10:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'abc123def456'
down_revision: Union[str, None] = 'previous_revision'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', 
        sa.Column('email_verified', sa.Boolean(), 
                  nullable=False, server_default='0')
    )
    op.add_column('users', 
        sa.Column('verification_token', sa.String(255), 
                  nullable=True)
    )


def downgrade() -> None:
    op.drop_column('users', 'verification_token')
    op.drop_column('users', 'email_verified')
```

## Решение проблем

### Конфликт версий

Если несколько разработчиков создали миграции:

```bash
alembic merge heads -m "merge migrations"
```

### Сброс миграций (для разработки)

```bash
# Откатить все
alembic downgrade base

# Удалить файлы миграций
rm alembic/versions/*.py

# Удалить базу данных
rm spendy.db

# Создать новую миграцию
alembic revision --autogenerate -m "Initial migration"

# Применить
alembic upgrade head
```

### Ручное редактирование таблицы alembic_version

В крайнем случае (только для разработки!):

```sql
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('revision_id');
```
