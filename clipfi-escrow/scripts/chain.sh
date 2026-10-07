#!/usr/bin/env bash
set -euo pipefail

cluster=${1:-localnet}
brand=${2:-}
cd /work

case "$cluster" in
  localnet)
    rpc=http://validator:8899
    rpc_host=http://localhost:8899
    rpc_backend=http://host.docker.internal:8899
    ;;
  devnet)
    rpc=https://api.devnet.solana.com
    rpc_host=$rpc
    rpc_backend=$rpc
    ;;
  *)
    echo "cluster must be localnet or devnet" >&2
    exit 1
    ;;
esac

wallet=/root/.config/solana/id.json
if [ ! -f "$wallet" ]; then
  solana-keygen new --no-bip39-passphrase --silent --outfile "$wallet"
fi
solana config set --url "$rpc" --keypair "$wallet" >/dev/null
deployer=$(solana address)
echo "deployer $deployer"

if [ "$cluster" = localnet ]; then
  solana airdrop 500 "$deployer" >/dev/null
else
  for attempt in 1 2 3; do
    if solana airdrop 2 "$deployer" >/dev/null 2>&1; then break; fi
    sleep 5
  done
fi
echo "balance $(solana balance "$deployer")"

program_keypair=target/deploy/clipfi_escrow-keypair.json
if [ ! -f "$program_keypair" ]; then
  mkdir -p target/deploy
  solana-keygen new --no-bip39-passphrase --silent --outfile "$program_keypair"
fi
program=$(solana-keygen pubkey "$program_keypair")
if ! grep -q "$program" programs/clipfi_escrow/src/lib.rs; then
  anchor keys sync
  rm -f target/deploy/clipfi_escrow.so
fi
if [ ! -f target/deploy/clipfi_escrow.so ]; then
  anchor build
  cp target/idl/clipfi_escrow.json idl/clipfi_escrow.json
  cp target/types/clipfi_escrow.ts idl/clipfi_escrow.ts
fi
echo "program $program"

solana program deploy target/deploy/clipfi_escrow.so \
  --program-id "$program_keypair" \
  --upgrade-authority "$wallet" \
  --url "$rpc" >/dev/null
echo "deployed"

mkdir -p .keys
mint_file=.keys/mint-$cluster.json
if [ -f "$mint_file" ]; then
  mint=$(python3 -c "import json;print(json.load(open('$mint_file'))['mint'])")
else
  mint=$(spl-token create-token --decimals 6 --output json --url "$rpc" | python3 -c "import json,sys;print(json.load(sys.stdin)['commandOutput']['address'])")
  spl-token create-account "$mint" --url "$rpc" >/dev/null
  spl-token mint "$mint" 1000000 --url "$rpc" >/dev/null
  echo "{\"mint\": \"$mint\"}" > "$mint_file"
fi
echo "mint $mint"

if [ -n "$brand" ]; then
  if [ "$cluster" = localnet ]; then
    solana airdrop 10 "$brand" >/dev/null
  fi
  spl-token create-account "$mint" --owner "$brand" --fee-payer "$wallet" --url "$rpc" >/dev/null 2>&1 || true
  spl-token mint "$mint" 10000 --recipient-owner "$brand" --url "$rpc" >/dev/null
  echo "brand $brand funded with 10000 clipUSD"
fi

python3 - "$cluster" "$rpc" "$rpc_host" "$rpc_backend" "$program" "$mint" "$deployer" "$wallet" <<'EOF'
import json, sys
cluster, rpc_internal, rpc_host, rpc_backend, program, mint, deployer, wallet = sys.argv[1:]
secret = json.load(open(wallet))
out = {
    "cluster": cluster,
    "rpc_url": rpc_host,
    "rpc_url_internal": rpc_internal,
    "rpc_url_backend": rpc_backend,
    "program_id": program,
    "mint": mint,
    "deployer": deployer,
    "deployer_secret": secret,
}
json.dump(out, open(".keys/chain.json", "w"), indent=2)
open(".keys/cluster", "w").write(cluster + "\n")
import os, secrets
existing = {}
if os.path.exists(".keys/compose.env"):
    for line in open(".keys/compose.env"):
        if "=" in line:
            key, value = line.rstrip("
").split("=", 1)
            existing[key] = value
partner_token = existing.get("CLIPFI_PARTNER_TOKEN") or secrets.token_urlsafe(32)
open(".keys/compose.env", "w").write(
    f"CLIPFI_RPC_URL={rpc_internal}
CLIPFI_PROGRAM_ID={program}
CLIPFI_CLIPUSD_MINT={mint}
CLIPFI_PARTNER_TOKEN={partner_token}
"
)
EOF
echo "wrote .keys/chain.json, .keys/cluster, .keys/compose.env"
