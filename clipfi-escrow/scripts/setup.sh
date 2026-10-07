#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

cluster=${1:-localnet}
brand=${2:-}
if [ -z "${WAGGI_DIR:-}" ]; then
  if [ -f ../backend/main.py ]; then WAGGI_DIR=..; else WAGGI_DIR=../waggi; fi
fi
export WAGGI_DIR

mkdir -p .keys
if [ "$cluster" = localnet ]; then
  echo "== local validator"
  docker compose --profile localnet up -d --wait validator
fi

echo "== program, deployer, clipUSD mint ($cluster)"
docker compose --profile tools run --rm anchor bash -c "sed -i 's/\r$//' scripts/chain.sh && bash scripts/chain.sh $cluster $brand"

echo "== tools image"
docker compose --profile tools build tools

echo "== init_config + bonus pool"
docker compose --profile tools run --rm tools python scripts/init_config.py

echo "== waggi .env"
docker compose --profile tools run --rm tools python scripts/write_env.py

echo "== indexer + partner"
docker compose up -d --build --wait indexer partner

echo "== waggi stack"
(cd "$WAGGI_DIR" && docker compose up -d --build)
code=000
for attempt in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/solana/config || true)
  [ "$code" = 200 ] && break
  sleep 2
done
echo "backend /api/solana/config -> $code"
curl -s http://localhost:8000/api/solana/config
echo
echo "frontend  http://localhost:5173"
echo "backend   http://localhost:8000/docs"
echo "indexer   http://localhost:8001/health"
echo "partner   http://localhost:8002/health"
if [ "$cluster" = localnet ]; then
  echo "wallet: Phantom -> Settings -> Developer settings -> custom RPC http://localhost:8899"
else
  echo "wallet: Phantom -> Settings -> Developer settings -> Devnet"
fi
echo "end-to-end check: scripts/docker-compose.sh e2e"
echo "keys and addresses: .keys/chain.json (demo only, never commit)"
