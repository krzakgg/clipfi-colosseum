#!/usr/bin/env bash
set -euo pipefail

solana config set --url "${SOLANA_URL:-https://api.devnet.solana.com}" >/dev/null

if [ ! -f "${SOLANA_KEYPAIR:-/root/.config/solana/id.json}" ]; then
    mkdir -p "$(dirname "${SOLANA_KEYPAIR:-/root/.config/solana/id.json}")"
    solana-keygen new --no-bip39-passphrase --silent \
        --outfile "${SOLANA_KEYPAIR:-/root/.config/solana/id.json}"
fi

solana config set --keypair "${SOLANA_KEYPAIR:-/root/.config/solana/id.json}" >/dev/null

if [ "${1:-}" = "wallet" ]; then
    solana address
    solana balance
    exit 0
fi

exec "$@"
