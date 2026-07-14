#!/usr/bin/env bash
# CommercePulse stack health check.
#
# Validates each layer independently so a failure localizes immediately.
# Distinguishes "not ready yet" from "actually broken": a stack seconds into
# startup will always fail the deeper checks, and telling someone to rebuild
# when they simply need to wait is a pointless detour.
#
#   bash scripts/healthcheck.sh              # waits for readiness, then checks
#   bash scripts/healthcheck.sh --no-wait    # check immediately, no polling
#
# Exits non-zero if any hard check fails.

set -uo pipefail

PASS="  [PASS]"
FAIL="  [FAIL]"
WARN="  [WARN]"
WAIT_TIMEOUT=90          # seconds to allow the stack to come up
POLL_INTERVAL=3

failures=0
NO_WAIT=0
[ "${1:-}" = "--no-wait" ] && NO_WAIT=1

hdr()  { printf "\n=== %s ===\n" "$1"; }
ok()   { echo "$PASS $1"; }
no()   { echo "$FAIL $1"; failures=$((failures + 1)); }
warn() { echo "$WARN $1"; }

# --------------------------------------------------------------------------
# Resolve the Airflow port. Must tolerate CRLF line endings (routine on
# Windows), trailing whitespace, quotes, and inline comments; otherwise the
# port silently falls back to 8080 and a healthy webserver reads as dead.
# --------------------------------------------------------------------------
if [ -z "${AIRFLOW_PORT:-}" ] && [ -f .env ]; then
  AIRFLOW_PORT=$(
    grep -E '^[[:space:]]*AIRFLOW_PORT[[:space:]]*=' .env 2>/dev/null \
      | tail -1 \
      | cut -d= -f2- \
      | sed -e 's/#.*$//' -e 's/\r$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
            -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
  )
fi
AIRFLOW_PORT="${AIRFLOW_PORT:-8080}"

# --------------------------------------------------------------------------
hdr "1. Container status"
docker compose ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}" 2>/dev/null \
  || { no "docker compose not responding. Is Docker Desktop running?"; exit 1; }

missing=0
for svc in data-db airflow-db airflow-webserver airflow-scheduler; do
  state=$(docker compose ps --format "{{.Service}} {{.State}}" 2>/dev/null | awk -v s="$svc" '$1==s {print $2}')
  if [ "$state" = "running" ]; then
    ok "$svc is running"
  elif [ -z "$state" ]; then
    no "$svc is not running at all"
    missing=$((missing + 1))
  else
    no "$svc is '$state'  ->  docker compose logs $svc --tail 50"
  fi
done

# airflow-init is a one-shot job; it should exit cleanly, not keep running.
init_state=$(docker compose ps -a --format "{{.Service}} {{.State}}" 2>/dev/null | awk '$1=="airflow-init" {print $2}')
if [ "$init_state" = "running" ]; then
  warn "airflow-init is still running (one-shot job); the stack is still coming up"
fi

if [ "$missing" -gt 0 ]; then
  echo
  echo "  $missing service(s) are not up. Everything downstream will fail until"
  echo "  they are. Start the stack, then re-run this check:"
  echo
  echo "      docker compose up -d"
  echo "      bash scripts/healthcheck.sh"
  echo
  echo "  If they exit immediately, read why:"
  echo "      docker compose logs data-db --tail 50"
  exit 1
fi

# --------------------------------------------------------------------------
# Readiness gate. Airflow takes 30-60s to serve after the containers report
# running, so the deeper checks below are meaningless until it does. Poll
# rather than fail, and only give up after WAIT_TIMEOUT.
# --------------------------------------------------------------------------
hdr "2. Waiting for the stack to become ready"

if [ "$NO_WAIT" -eq 1 ]; then
  warn "--no-wait given; skipping the readiness poll"
else
  waited=0
  ready=0
  printf "  polling http://127.0.0.1:%s/health " "$AIRFLOW_PORT"
  while [ "$waited" -lt "$WAIT_TIMEOUT" ]; do
    if curl -sf -o /dev/null -m 5 "http://127.0.0.1:${AIRFLOW_PORT}/health"; then
      ready=1
      break
    fi
    printf "."
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
  done
  echo
  if [ "$ready" -eq 1 ]; then
    ok "stack ready after ${waited}s"
  else
    warn "not ready after ${WAIT_TIMEOUT}s; the checks below may be premature"
  fi
fi

# --------------------------------------------------------------------------
hdr "3. Dependency versions inside the Airflow image"
# Airflow 2.9 requires SQLAlchemy 1.4; pandas 2.2+ requires SQLAlchemy 2.x.
# The two collide, so pandas must stay below 2.2. Assert the pairing.
sa_out=$(docker compose exec -T airflow-scheduler python -c "
import sqlalchemy, pandas, sys
sa = tuple(int(p) for p in sqlalchemy.__version__.split('.')[:2])
pd = tuple(int(p) for p in pandas.__version__.split('.')[:2])
print(f'SQLAlchemy {sqlalchemy.__version__} | pandas {pandas.__version__}')
if sa >= (2, 0):
    print('  SQLAlchemy 2.x breaks Airflow ORM models (MappedAnnotationError)')
    sys.exit(1)
if pd >= (2, 2):
    print('  pandas 2.2+ needs SQLAlchemy 2.x, which Airflow cannot use')
    sys.exit(1)
sys.exit(0)
" 2>&1)
sa_rc=$?

if [ "$sa_rc" -eq 0 ]; then
  echo "  $sa_out"
  ok "SQLAlchemy 1.4 + pandas < 2.2 (the only pairing Airflow and pandas share)"
elif echo "$sa_out" | grep -qiE "not running|no such|is not running"; then
  no "scheduler not reachable yet  ->  wait, then re-run this check"
else
  echo "  $sa_out"
  no "incompatible dependency pair  ->  docker compose build --no-cache"
fi

# --------------------------------------------------------------------------
hdr "4. Airflow webserver reachable"
if curl -sf -o /dev/null -m 10 "http://127.0.0.1:${AIRFLOW_PORT}/health"; then
  ok "http://127.0.0.1:${AIRFLOW_PORT} responding"
  curl -s -m 10 "http://127.0.0.1:${AIRFLOW_PORT}/health"
  echo
else
  no "webserver not answering on ${AIRFLOW_PORT}"
  echo "         checked port ${AIRFLOW_PORT}; set AIRFLOW_PORT in .env if it differs"
  echo "         docker compose logs airflow-webserver --tail 50"
fi

# --------------------------------------------------------------------------
hdr "5. Source data in PostgreSQL staging"
for tbl in customers products orders; do
  n=$(docker compose exec -T data-db psql -U postgres -d mandera -tAc \
        "SELECT count(*) FROM staging.$tbl;" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null; then
    ok "staging.$tbl  ($n rows)"
  else
    no "staging.$tbl empty or unreachable"
    echo "         the seed only loads on a fresh volume:  docker compose down -v && docker compose up -d"
  fi
done

# --------------------------------------------------------------------------
hdr "6. Analytics outputs"
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
hdr "7. Monday CRM credentials"
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
  echo "  python -m python.pipeline              # full run, upserts to Monday"
  echo "  open http://127.0.0.1:${AIRFLOW_PORT}  # Airflow UI (airflow / airflow)"
else
  echo "$failures check(s) failed."
  echo
  echo "If you started the stack moments ago, it may simply not be ready."
  echo "Wait, then re-run:  bash scripts/healthcheck.sh"
  exit 1
fi