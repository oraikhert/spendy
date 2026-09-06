# Deployment: Docker, PostgreSQL and Nginx

This is the runbook for the existing single-server deployment. It uses the
repository's Docker configuration, PostgreSQL storage, host Nginx and Let's Encrypt.
Read [the access model](ARCHITECTURE.md#access-model) before exposing an installation:
authenticated users share transaction data and server-side CSRF validation is absent.
Return to the [documentation index](../README.md#documentation).

- [Prerequisites](#prerequisites)
- [Server preparation](#server-preparation)
- [Configuration](#configuration)
- [First deployment](#first-deployment)
- [Users](#users)
- [HTTPS proxy](#https-proxy)
- [Updates and backups](#updates-and-backups)
- [Database access and maintenance](#database-access-and-maintenance)

## Prerequisites

Use an Ubuntu server with SSH access and a domain A record pointing to the server.
Commands below assume a root/admin shell on the server; adapt privileges for your
deployment user.

## Server preparation

### Update and install packages

```bash
apt update && apt -y upgrade
apt -y install git curl ufw nginx
```

### Configure the firewall

Allow SSH, HTTP and HTTPS before enabling the firewall:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

### Install Docker and the Compose plugin

```bash
curl -fsSL https://get.docker.com | sh
apt -y install docker-compose-plugin
docker --version
docker compose version
```

### Install Certbot

```bash
apt -y install certbot python3-certbot-nginx
```

Clone the repository into `/opt/spendy`, using your actual remote URL or SSH deploy
key. Run Compose commands from that directory.

## Configuration

Use the committed [Dockerfile](../Dockerfile) and
[docker-compose.yml](../docker-compose.yml); do not recreate copies from documentation.
Compose defines services `db` and `app`, binds PostgreSQL and HTTP to host loopback,
stores PostgreSQL in a named volume, and mounts `./data/uploads` into the app.

For a new deployment, copy [.env.example](../.env.example) to `.env` and configure:

```dotenv
POSTGRES_PASSWORD=REPLACE_WITH_DB_PASSWORD
DATABASE_URL=postgresql+asyncpg://spendy:REPLACE_WITH_DB_PASSWORD@db:5432/spendy
SECRET_KEY=REPLACE_WITH_RANDOM_SECRET
REGISTRATION_ENABLED=false
DEBUG=false
```

Use the same database password in both settings; URL-encode special characters
in the connection URL. Generate a signing secret with
`python3 -c "import secrets; print(secrets.token_hex(32))"`. Preserve existing secrets
on updates. Keep `.env` out of Git and restrict its filesystem permissions.

`db` is the Compose hostname used from inside the app container. The PostgreSQL
driver is already a project dependency. App settings are defined in
[app/config.py](../app/config.py); Docker-only variables such as `POSTGRES_PASSWORD`
are consumed by Compose.

## First deployment

Build the app and start PostgreSQL, then check that `db` becomes healthy:

```bash
cd /opt/spendy
mkdir -p data/uploads
docker compose build app
docker compose up -d db
docker compose ps
```

Apply migrations in a one-off app container **before starting the HTTP service**:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app alembic current
docker compose up -d app
docker compose logs --tail=100 app
curl --fail http://127.0.0.1:8000/health
```

The one-off container uses the app image and `.env` without running its normal
server command. PostgreSQL schema creation is already disabled in `init_db()`;
no code edit is required. Use [Migrations](MIGRATIONS.md) for schema decisions and
known model/history differences. A successful health response confirms HTTP only;
also verify login and a protected database-backed request.

## Users

With migrations applied, create a user while self-registration remains disabled.
In a Bash shell on the server:

```bash
read -r -s -p 'New user password: ' spendy_user_password
docker compose run --rm app python scripts/create_user.py \
  --email owner@example.com --username owner --password "$spendy_user_password"
unset spendy_user_password
```

Replace the synthetic email/username with the intended account. The current CLI
accepts its password through a process argument; the prompt avoids putting the
literal password in shell history. For a local installation, run the same
`python scripts/create_user.py` command with `venv` active, without the Compose prefix.
Input validation comes from [UserCreate](../app/schemas/user.py).

## HTTPS proxy

Create `/etc/nginx/sites-available/spendy.conf` using your real domain:

```nginx
server {
    listen 80;
    server_name spendy.example.com;

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

Enable the site once, validate Nginx, then issue the certificate:

```bash
ln -s /etc/nginx/sites-available/spendy.conf /etc/nginx/sites-enabled/spendy.conf
nginx -t
systemctl reload nginx
certbot --nginx -d spendy.example.com
certbot renew --dry-run
systemctl status certbot.timer
```

Verify HTTPS login in a browser, including the cookie's Secure flag and redirect
behavior. Secure-cookie selection depends on the scheme seen by the app; forwarding
the header alone does not establish that Uvicorn trusts the proxy. If it sees HTTP,
configure trusted forwarded-header handling for the actual proxy/container network
before considering HTTPS login verified. Review the CORS policy in
[app/main.py](../app/main.py) for the intended client origins.

## Updates and backups

Before a schema-changing update, record the deployed Git revision, stop app writes
and back up both the database and uploads. For example, with the `db` service running:

```bash
cd /opt/spendy
git rev-parse HEAD
docker compose stop app
mkdir -p /var/backups/spendy
spendy_backup_id=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T db pg_dump -U spendy -d spendy -Fc \
  > "/var/backups/spendy/$spendy_backup_id.dump"
tar -czf "/var/backups/spendy/$spendy_backup_id-uploads.tar.gz" data/uploads
```

Check both commands succeeded and validate restore on a separate database before
relying on a backup. Keep backups outside the repository and copy them to durable
storage according to the installation's retention policy.

With a clean deployment checkout, update the code and migrate before restarting:

```bash
git pull --ff-only
docker compose build app
docker compose run --rm app alembic upgrade head
docker compose run --rm app alembic current
docker compose up -d app
docker compose logs --tail=100 app
curl --fail http://127.0.0.1:8000/health
```

The same update can be run as one command on the production server from the
deployed checkout:

```bash
./scripts/deploy.sh                 # update without a backup
./scripts/deploy_with_backup.sh     # update with database and upload backups
```

Both scripts expect the project at `/opt/spendy` and an existing `.env` file.
They stop on the first failed command and wait for the health endpoint after the
app restarts. If a migration fails, the app remains stopped for recovery. The
backup script stores a PostgreSQL dump and an archive of `data/uploads` in
`/var/backups/spendy` before starting the update.

Run each step only after the previous one succeeds. If migration fails, leave the
app stopped and use [migration recovery](MIGRATIONS.md#recovery-and-rollback).
An older image may not support the new schema; code rollback alone is insufficient.
After an update, verify HTTPS login and database-backed behavior again.

## Database access and maintenance

For an interactive database session on the server:

```bash
docker compose exec db psql -U spendy -d spendy
```

Use `\dt` to list tables and `\q` to exit. For a desktop SQL client, open an SSH
tunnel from the laptop:

```bash
ssh -N -L 15432:127.0.0.1:5432 deploy@spendy.example.com
```

Connect the client to `127.0.0.1:15432`, database/user `spendy`, using the configured
database password. Substitute the actual SSH user and host.

`docker compose stop app` stops HTTP while retaining data. Rebuilding the app
retains the PostgreSQL volume and upload mount. Named-volume deletion, including
`docker compose down -v`, destroys database storage and is not routine maintenance.
For a clean test environment, use a separate deployment and data location.
