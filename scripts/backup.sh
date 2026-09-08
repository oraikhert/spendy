#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/spendy}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/spendy}"
BACKUP_WAIT_ATTEMPTS=30
BACKUP_WAIT_DELAY_SECONDS=2
KEEP_APP_STOPPED="${SPENDY_BACKUP_KEEP_APP_STOPPED:-false}"

case "$KEEP_APP_STOPPED" in
    true|false) ;;
    *)
        echo "Error: SPENDY_BACKUP_KEEP_APP_STOPPED must be 'true' or 'false'." >&2
        exit 1
        ;;
esac

cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
    echo "Error: $PROJECT_DIR/.env was not found." >&2
    exit 1
fi

if [[ ! -d data/uploads ]]; then
    echo "Error: $PROJECT_DIR/data/uploads was not found." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
umask 077

backup_id="$(date -u +%Y%m%dT%H%M%SZ)"
database_backup="$BACKUP_DIR/$backup_id.dump"
uploads_backup="$BACKUP_DIR/$backup_id-uploads.tar.gz"

if [[ -e "$database_backup" || -e "$uploads_backup" ]]; then
    echo "Error: backup files for $backup_id already exist." >&2
    exit 1
fi

temporary_backup_dir="$(mktemp -d "$BACKUP_DIR/.spendy-backup.XXXXXX")"
app_was_running=false
if docker compose ps --status running --services | grep -Fxq app; then
    app_was_running=true
fi

cleanup() {
    rm -rf -- "$temporary_backup_dir"

    if [[ "$app_was_running" == true && "$KEEP_APP_STOPPED" == false ]]; then
        echo "Restarting the app..."
        docker compose up -d app || true
    fi
}
trap cleanup EXIT

echo "Ensuring the database is running..."
docker compose up -d db

echo "Waiting for PostgreSQL..."
for ((attempt = 1; attempt <= BACKUP_WAIT_ATTEMPTS; attempt++)); do
    if docker compose exec -T db pg_isready -U spendy -d spendy >/dev/null 2>&1; then
        break
    fi

    if (( attempt == BACKUP_WAIT_ATTEMPTS )); then
        echo "Error: PostgreSQL did not become ready for the backup." >&2
        exit 1
    fi

    sleep "$BACKUP_WAIT_DELAY_SECONDS"
done

echo "Stopping the app before backup..."
docker compose stop app

echo "Backing up the database..."
docker compose exec -T db pg_dump -U spendy -d spendy -Fc \
    > "$temporary_backup_dir/$backup_id.dump"

echo "Backing up uploads..."
tar -czf "$temporary_backup_dir/$backup_id-uploads.tar.gz" \
    -C "$PROJECT_DIR/data" uploads

mv -- "$temporary_backup_dir/$backup_id.dump" "$database_backup"
mv -- "$temporary_backup_dir/$backup_id-uploads.tar.gz" "$uploads_backup"
rmdir "$temporary_backup_dir"
trap - EXIT

echo "Backups created:"
echo "  $database_backup"
echo "  $uploads_backup"

if [[ "$app_was_running" == true && "$KEEP_APP_STOPPED" == false ]]; then
    echo "Restarting the app..."
    docker compose up -d app
fi
