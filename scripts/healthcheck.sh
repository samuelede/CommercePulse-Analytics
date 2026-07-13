#!/usr/bin/env bash
# CommercePulse stack health check.
# Validates each layer independently so failures are easy to localize.
#
#   bash scripts/healthcheck.sh
#
# Exits non-zero on the first hard failure.

set -uo pipefail

PASS="  [PASS]"
FAIL="  [FAIL]"
WARN="  [WARN]"
failures=0

hdr() { printf "\n=== %s ===\n" "$1"; }
ok()  { echo "$PASS $1"; }
no()  { echo "$FAIL $1"; failures=$((failures + 1)); }
warn(){ echo "$WARN $1"; }

# --------------------------------------------------------------------------
hdr "1. Container status"
docker compose ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}" 2>/dev/null \
  || { no "docker compose not responding. Is Docker Desktop running?"; exit 1; }

for svc in data-db airflow-db airflow-webserver airflow-scheduler; do
  state=$(docker compose ps --format "{{.Service}} {{.State}}" 2>/dev/null | awk -v s="$svc" '$1==s {print $2}')
  if [ "$state" = "running" ]; then
    ok "$svc is running"
  else
    no "$svc is '${state:-absent}'  ->  docker compose logs $svc --tail 50"
  fi
done

# --------------------------------------------------------------------------
hdr "2. Dependency versions inside the Airflow image"
if docker compose exec -T airflow-scheduler python -c "
import sqlalchemy, pandas, sys
sa = int(sqlalchemy.__version__.split('.')[0])
print(f'SQLAlchemy {sqlalchemy.__version__} | pandas {pandas.__version__}')
sys.exit(0 if sa >= 2 else 1)
" 2>/dev/null; then
  ok "SQLAlchemy is 2.x (required by pandas 2.2)"
else
  no "SQLAlchemy < 2.x or scheduler unreachable  ->  docker compose build --no-cache"
fi

# --------------------------------------------------------------------------
hdr "3. Airflow webserver reachable"
# Match whatever docker-compose published; 8080 is often already taken.
AIRFLOW_PORT="${AIRFLOW_PORT:-$(grep -E '^AIRFLOW_PORT=' .env 2>/dev/null | cut -d= -f2)}"
AIRFLOW_PORT="${AIRFLOW_PORT:-8080}"

if curl -sf -o /dev/null -m 10 "http://127.0.0.1:${AIRFLOW_PORT}/health"; then
  ok "http://127.0.0.1:${AIRFLOW_PORT} responding"
  curl -s -m 10 "http://127.0.0.1:${AIRFLOW_PORT}/health"
  echo
else
  no "webserver not answering on ${AIRFLOW_PORT}  ->  docker compose logs airflow-webserver --tail 50"
fi

# --------------------------------------------------------------------------
hdr "4. Source data in PostgreSQL staging"
for tbl in customers products orders; do
  n=$(docker compose exec -T data-db psql -U postgres -d mandera -tAc \
        "SELECT count(*) FROM staging.$tbl;" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null; then
    ok "staging.$tbl  ($n rows)"
  else
    no "staging.$tbl empty or unreachable"
  fi
done

# --------------------------------------------------------------------------
hdr "5. Analytics outputs"
for tbl in customer_segmentation customer_360 campaign_recommendations; do
  n=$(docker compose exec -T data-db psql -U postgres -d mandera -tAc \
        "SELECT count(*) FROM analytics.$tbl;" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null; then
    ok "analytics.$tbl  ($n rows)"
  else
    warn "analytics.$tbl empty  ->  run: python -m python.pipeline --skip-crm"
  fi
done

# --------------------------------------------------------------------------
hdr "6. Monday CRM credentials"
PYTHONPATH=. python scripts/check_monday.py
rc=$?
[ $rc -eq 1 ] && failures=$((failures + 1))

# --------------------------------------------------------------------------
hdr "Summary"
if [ "$failures" -eq 0 ]; then
  echo "All hard checks passed."
  echo
  echo "Next:"
  echo "  python -m python.pipeline --skip-crm   # analytics only"
  echo "  python -m python.pipeline              # full run, syncs to Monday"
else
  echo "$failures check(s) failed. Fix these before running the pipeline."
  exit 1
fi