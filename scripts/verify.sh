#!/usr/bin/env bash
# Run every check AKSHARA's CI runs. Exits non-zero on the first failure.
# Backend integration tests need PostgreSQL and Redis (see backend/tests/README.md).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== lint & types";        make -s lint
echo "== backend tests";       (cd backend && uv run pytest -q)
echo "== frontend tests";      (cd frontend && npx vitest run)
echo "== frontend build";      (cd frontend && npm run -s build >/dev/null)
echo "ALL CHECKS PASSED"
