#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

action=${1:-up}
if [ -z "${WAGGI_DIR:-}" ]; then
  if [ -f ../backend/main.py ]; then WAGGI_DIR=..; else WAGGI_DIR=../waggi; fi
fi
export WAGGI_DIR
cluster=localnet
[ -f .keys/cluster ] && cluster=$(tr -d '\r\n' < .keys/cluster)
profile=()
[ "$cluster" = localnet ] && profile=(--profile localnet)

case "$action" in
  up)
    docker compose "${profile[@]}" up -d --wait
    (cd "$WAGGI_DIR" && docker compose up -d)
    ;;
  down)
    (cd "$WAGGI_DIR" && docker compose down)
    docker compose --profile localnet --profile tools down
    ;;
  restart)
    "$0" down
    "$0" up
    ;;
  ps)
    docker compose "${profile[@]}" ps
    (cd "$WAGGI_DIR" && docker compose ps)
    ;;
  logs)
    service=${2:-}
    if [ -n "$service" ]; then
      docker compose "${profile[@]}" logs -f "$service" 2>/dev/null || (cd "$WAGGI_DIR" && docker compose logs -f "$service")
    else
      docker compose "${profile[@]}" logs --tail 50
      (cd "$WAGGI_DIR" && docker compose logs --tail 50)
    fi
    ;;
  e2e)
    docker compose --profile tools run --rm tools python scripts/e2e.py
    ;;
  test)
    docker compose --profile tools run --rm anchor bash -lc 'anchor build && cargo test'
    ;;
  reset)
    (cd "$WAGGI_DIR" && docker compose down -v)
    docker compose --profile localnet --profile tools down -v
    rm -rf .keys
    ;;
  *)
    echo "usage: $0 up|down|restart|ps|logs [service]|e2e|test|reset" >&2
    exit 1
    ;;
esac
