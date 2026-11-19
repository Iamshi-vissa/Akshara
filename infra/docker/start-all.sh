#!/bin/bash
# Run the API and the Celery worker in one container (hosts such as Render attach a persistent
# disk to a single service, and both processes need the blob store). If either process exits,
# the container exits so the platform restarts it.
set -euo pipefail

root="${AKSHARA_STORAGE_ROOT:-/data/blobs}"
mkdir -p "$root" 2>/dev/null || true
if ! touch "$root/.write-test" 2>/dev/null; then
  echo "FATAL: blob storage $root is not writable by uid $(id -u). Mount a persistent disk there." >&2
  exit 1
fi
rm -f "$root/.write-test"

alembic upgrade head
celery -A app.workers.celery_app worker --loglevel=INFO --concurrency="${AKSHARA_WORKER_CONCURRENCY:-2}" &
uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*' &
wait -n
echo "A process exited; stopping the container so it is restarted." >&2
exit 1
