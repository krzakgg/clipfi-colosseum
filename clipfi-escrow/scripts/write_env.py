import json
import secrets
import sys
from pathlib import Path

from chain_common import load_chain, waggi_dir


def read_env(path):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    return lines, values


def write_env(path, lines, updates):
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    waggi = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else waggi_dir()
    chain = load_chain()
    root_env = waggi / ".env"
    tracking_env = waggi / "tracking-service" / ".env"
    tracking_example = waggi / "tracking-service" / ".env.example"

    root_lines, root_values = read_env(root_env)
    tracking_lines, tracking_values = read_env(tracking_env)
    service_token = root_values.get("TRACKING_SERVICE_TOKEN") or tracking_values.get("TRACKING_SERVICE_TOKEN") or secrets.token_urlsafe(48)

    if not tracking_env.exists():
        example_lines, example_values = read_env(tracking_example)
        db_password = secrets.token_urlsafe(24)
        app_password = secrets.token_urlsafe(24)
        redis_password = secrets.token_urlsafe(24)
        write_env(
            tracking_env,
            example_lines,
            {
                "POSTGRES_PASSWORD": db_password,
                "TRACKING_APP_DB_PASSWORD": app_password,
                "TRACKING_DATABASE_URL": f"postgresql://tracking_app:{app_password}@postgres:5432/tracking",
                "REDIS_PASSWORD": redis_password,
                "TRACKING_REDIS_URL": f"redis://:{redis_password}@redis:6379/0",
                "TRACKING_SERVICE_TOKEN": service_token,
                "TRACKING_FINGERPRINT_SECRET": secrets.token_urlsafe(48),
            },
        )
        print(f"created {tracking_env}")

    oracle_token = root_values.get("SOLANA_ORACLE_TOKEN") or secrets.token_urlsafe(48)
    updates = {
        "TRACKING_SERVICE_TOKEN": service_token,
        "SOLANA_CLUSTER": chain["cluster"],
        "SOLANA_RPC_URL": chain["rpc_url_backend"],
        "SOLANA_TREASURY_ADDRESS": chain["deployer"],
        "SOLANA_TREASURY_PRIVATE_KEY": json.dumps(chain["deployer_secret"], separators=(",", ":")),
        "SOLANA_PLATFORM_FEE_WALLET_ADDRESS": chain["deployer"],
        "SOLANA_ESCROW_PROGRAM_ID": chain["program_id"],
        "SOLANA_BMONEY_MINT": chain["mint"],
        "SOLANA_BMONEY_DECIMALS": "6",
        "SOLANA_ORACLE_TOKEN": oracle_token,
    }
    write_env(root_env, root_lines, updates)
    print(f"wrote {root_env}: cluster {chain['cluster']}, rpc {chain['rpc_url_backend']}, program {chain['program_id']}, mint {chain['mint']}")


if __name__ == "__main__":
    main()
