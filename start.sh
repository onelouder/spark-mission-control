#!/bin/bash
# Mission Control v2 — port 3000, requires Postgres + Redis
#
# Usage:
#   ./start.sh            # boot full stack (Docker + migrations + uvicorn)
#   ./start.sh --prod     # production-ish boot: uvicorn --workers 1 with reload off
#   ./start.sh --test     # run pytest against the docker-compose stack
#   ./start.sh --migrate  # run alembic + the v1 -> PG data migration only

set -e
cd "$(dirname "$0")"

MODE="${1:-run}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Starting Docker services (Postgres + Redis)..."
docker compose up -d

echo "Waiting for Postgres..."
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U mission_control -d mission_control >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate

case "$MODE" in
  --test)
    pip install -q -r requirements-dev.txt
    echo "Running pytest suite..."
    pytest "${@:2}"
    exit $?
    ;;
  --migrate)
    pip install -q -r requirements.txt
    echo "Running Alembic + v1 JSON -> PG migration..."
    alembic upgrade head
    python scripts/migrate_json_to_pg.py "${@:2}"
    exit $?
    ;;
  --prod)
    pip install -q -r requirements.txt
    echo "Running migrations..."
    alembic upgrade head

    HOST="${MC2_HOST:-0.0.0.0}"
    PORT="${MC2_PORT:-3000}"
    PUBLIC_URL="${PUBLIC_BASE_URL:-http://${HOST}:${PORT}}"
    echo "Mission Control v2 (prod mode) at ${PUBLIC_URL}"
    echo "  Single uvicorn worker + reload OFF + structured logging."
    echo "  Health: ${PUBLIC_URL}/api/health"
    echo "  Stop:   Ctrl-C (lifespan teardown cancels snooze sweep + dispatch subscriber)."
    echo ""

    LOG_LEVEL="${LOG_LEVEL:-info}"
    exec uvicorn main:app \
      --host "$HOST" \
      --port "$PORT" \
      --workers 1 \
      --no-access-log \
      --log-level "$LOG_LEVEL"
    ;;
  *)
    pip install -q -r requirements.txt
    echo "Running migrations..."
    alembic upgrade head

    PUBLIC_URL="${PUBLIC_BASE_URL:-http://127.0.0.1:3000}"
    echo "Mission Control v2 at ${PUBLIC_URL}"
    echo "  Health: ${PUBLIC_URL}/api/health"
    echo "  Migrate: ./start.sh --migrate"
    echo "  Test:    ./start.sh --test"
    echo ""

    python main.py
    ;;
esac
