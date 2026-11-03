#!/usr/bin/env sh
set -e

# 1. Start embedded Redis if REDIS_URL uses localhost and redis-server is available
case "${REDIS_URL:-redis://localhost:6379/0}" in
  redis://localhost*|redis://127.0.0.1*)
    if command -v redis-server >/dev/null 2>&1; then
      echo "Starting embedded Redis server on 127.0.0.1:6379..."
      redis-server --bind 127.0.0.1 --port 6379 --daemonize yes --save "" --appendonly no --maxmemory 64mb --maxmemory-policy allkeys-lru
    fi
    ;;
esac

# 2. Start Celery Worker + Beat in the background if Redis is reachable
python -c "
import redis, sys
from app.core.config import settings
try:
    r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(1)
" && {
  echo "Redis is reachable — starting Celery worker + beat in background..."
  celery -A app.core.celery_app:celery_app worker --beat --loglevel=INFO --concurrency=2 &
} || {
  echo "Redis not reachable — FastAPI will use built-in async/thread fallback for background tasks and schedules."
}

# 3. Start FastAPI (Uvicorn) in the foreground
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

