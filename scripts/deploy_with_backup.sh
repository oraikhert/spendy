#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="/opt/spendy"

cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
    echo "Error: $PROJECT_DIR/.env was not found." >&2
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: the production checkout contains tracked changes; refusing to deploy." >&2
    exit 1
fi

SPENDY_BACKUP_KEEP_APP_STOPPED=true "$PROJECT_DIR/scripts/backup.sh"

exec "$PROJECT_DIR/scripts/deploy.sh"
