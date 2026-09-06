#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="/opt/spendy"
HEALTH_URL="http://127.0.0.1:8000/health"
HEALTH_ATTEMPTS=30
HEALTH_DELAY_SECONDS=2

cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
    echo "Error: $PROJECT_DIR/.env was not found." >&2
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: the production checkout contains tracked changes; refusing to deploy." >&2
    exit 1
fi

echo "Updating source code..."
git pull --ff-only

echo "Building the app image..."
docker compose build app

echo "Ensuring the database is running..."
docker compose up -d db

echo "Stopping the app before migrations..."
docker compose stop app

echo "Applying database migrations..."
docker compose run --rm app alembic upgrade head
docker compose run --rm app alembic current

echo "Starting the updated app..."
docker compose up -d app

echo "Waiting for $HEALTH_URL..."
for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error "$HEALTH_URL" >/dev/null; then
        echo "Deployment completed successfully."
        docker compose ps
        exit 0
    fi

    if (( attempt < HEALTH_ATTEMPTS )); then
        sleep "$HEALTH_DELAY_SECONDS"
    fi
done

echo "Error: the app did not become healthy after $((HEALTH_ATTEMPTS * HEALTH_DELAY_SECONDS)) seconds." >&2
docker compose logs --tail=100 app >&2 || true
exit 1
