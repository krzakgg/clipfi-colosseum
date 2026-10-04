$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

docker compose run --rm anchor bash -lc @'
set -euo pipefail

if [ ! -d /workspace/public-examples/.git ]; then
  git clone --depth 1 https://github.com/solana-foundation/program-examples.git /workspace/public-examples
fi

cd /workspace/public-examples/tokens/escrow/anchor
anchor build
anchor deploy --provider.cluster devnet
'@
