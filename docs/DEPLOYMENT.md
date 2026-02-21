# Spendy Deployment Guide (VDS, Docker, Nginx, Let’s Encrypt)

This document describes a practical “development deployment” setup for **Spendy** on a cloud VDS using:

- **Docker + Docker Compose** (FastAPI + PostgreSQL)
- **Nginx** as a reverse proxy on the host
- **Let’s Encrypt** TLS certificates with automatic renewal
- **Alembic** migrations (Async SQLAlchemy)

The goal: a repeatable, minimal, and safe setup where:
- App is accessible via HTTPS domain
- Postgres is not exposed publicly
- Deploy updates via `git pull` + `docker compose up -d --build`

---

## 1) Prerequisites

### Domain
- Create an **A record**: `spendy.example.com` → your VDS public IP

### Server
- Ubuntu 22.04/24.04 recommended (works on 20.04 too)
- SSH access (root or a sudo user)

### Repository
- Spendy code is available on GitHub (public or via SSH deploy key)

---

## 2) Server Preparation

SSH into the server:

```bash
ssh root@YOUR_SERVER_IP
```

Update packages:

```bash
apt update && apt -y upgrade
apt -y install git curl ufw nginx
```

Firewall:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Install Docker + Compose plugin:

```bash
curl -fsSL https://get.docker.com | sh
apt -y install docker-compose-plugin
docker --version
docker compose version
```

---

## 3) Project Directory

Use a clean location such as:

```bash
mkdir -p /opt/spendy
cd /opt/spendy
git clone https://github.com/<you>/<Spendy>.git .
```

> For private repos, use SSH deploy keys.

---

## 4) Application Configuration (.env)

Create `/opt/spendy/.env`:

```env
# Postgres password (used by docker compose)
POSTGRES_PASSWORD=CHANGE_ME_STRONG

# Database URL (Async SQLAlchemy)
DATABASE_URL=postgresql+asyncpg://spendy:CHANGE_ME_STRONG@db:5432/spendy

# Security
SECRET_KEY=CHANGE_ME_SUPER_SECRET
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App
APP_NAME=Spendy
DEBUG=False
```

**Important:** Since Spendy uses async SQLAlchemy, use:
- `postgresql+asyncpg://...`
and ensure `asyncpg` is in `requirements.txt`.

---

## 5) Dockerfile (Project Root)

Create `/opt/spendy/Dockerfile`:

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 6) docker-compose.yml (Postgres + App)

Create `/opt/spendy/docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    container_name: spendy-db
    environment:
      POSTGRES_DB: spendy
      POSTGRES_USER: spendy
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"  # local-only for SSH tunnel usage
    volumes:
      - spendy_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U spendy -d spendy"]
      interval: 5s
      timeout: 5s
      retries: 20
    restart: unless-stopped

  app:
    build: .
    container_name: spendy-app
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"  # local-only; exposed via Nginx
    volumes:
      - ./data/uploads:/app/data/uploads
    restart: unless-stopped

volumes:
  spendy_pgdata:
```

### Data persistence
- PostgreSQL data is stored in the Docker volume: `spendy_pgdata`
- Uploaded files are stored on the host: `/opt/spendy/data/uploads`

---

## 7) IMPORTANT: Avoid `create_all()` on Postgres

Spendy currently initializes DB tables in code via `Base.metadata.create_all()` (SQLite-friendly), but on Postgres **schema should be managed by Alembic**.

Recommended approach:
- Keep `create_all()` only for SQLite local development
- For Postgres: do **not** create tables automatically at app startup

In `app/database.py`, gate init logic like:

```python
async def init_db() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

This prevents:
`DuplicateTableError: relation "accounts" already exists`

---

## 8) Start the Stack

From `/opt/spendy`:

```bash
docker compose up -d --build
docker compose ps
docker logs -n 100 spendy-app
```

Local health check:

```bash
curl -I http://127.0.0.1:8000
```

---

## 9) Run Alembic Migrations

Run migrations inside the app container:

```bash
docker exec -it spendy-app alembic upgrade head
```

Verify:

```bash
docker exec -it spendy-app alembic current
```

> Your `alembic/env.py` is already async-aware, so this is supported.

---

## 10) Nginx Reverse Proxy (Host)

Create `/etc/nginx/sites-available/spendy.conf`:

```nginx
server {
    listen 80;
    server_name spendy.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        client_max_body_size 25m;
    }
}
```

Enable config:

```bash
mkdir -p /var/www/certbot
ln -s /etc/nginx/sites-available/spendy.conf /etc/nginx/sites-enabled/spendy.conf
nginx -t
systemctl reload nginx
```

---

## 11) Let’s Encrypt TLS (Certbot)

Install certbot:

```bash
apt -y install certbot python3-certbot-nginx
```

Issue certificate:

```bash
certbot --nginx -d spendy.example.com
```

Auto-renewal check:

```bash
systemctl status certbot.timer
certbot renew --dry-run
```

---

## 12) Deploy Updates (Repeatable Process)

```bash
cd /opt/spendy
git pull
docker compose up -d --build
docker exec -it spendy-app alembic upgrade head
docker logs -n 80 spendy-app
```

---

## 13) Database Access (Terminal)

Inside Postgres container:

```bash
docker exec -it spendy-db psql -U spendy -d spendy
```

Useful commands:

```sql
\dt
\d accounts
\q
```

---

## 14) pgAdmin (Laptop) Connection via SSH Tunnel

Because Postgres is bound to `127.0.0.1:5432` on the server, use an SSH tunnel.

### Recommended (pgAdmin built-in SSH Tunnel)
In pgAdmin “Add New Server”:

**Connection tab**
- Host: `127.0.0.1`
- Port: `5432`
- Database: `spendy`
- Username: `spendy`
- Password: `POSTGRES_PASSWORD`

**SSH Tunnel tab**
- Tunnel host: your server domain or IP
- Username: `root` (or your deploy user)
- Auth: SSH key file (recommended)
- Keep alive (seconds): `60`

### Alternative (manual SSH tunnel)
On your laptop:

```bash
ssh -L 15432:127.0.0.1:5432 root@spendy.example.com
```

Then in pgAdmin:
- Host: `127.0.0.1`
- Port: `15432`

---

## 15) Reset / Cleanup

### Reset Postgres data completely
```bash
docker compose down -v
```

or:
```bash
docker volume rm spendy_pgdata
```

### Rebuild app without losing DB data
```bash
docker compose up -d --build
```

(DB persists because it is stored in the volume.)

---

## 16) Notes / Best Practices (Minimal)

- Keep Postgres bound to localhost (`127.0.0.1`) and use SSH tunnel for remote access.
- Use Alembic migrations for schema changes (don’t use `create_all()` on Postgres).
- Store uploads on host with bind mount (`./data/uploads`).
- Keep `.env` outside git and use strong secrets.
