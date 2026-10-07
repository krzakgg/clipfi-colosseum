import os
from dataclasses import dataclass, field
from pathlib import Path

IDL_PATH = Path(__file__).resolve().parent.parent / "idl" / "clipfi_escrow.json"


def _list(v):
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class Settings:
    rpc_url: str = field(default_factory=lambda: os.getenv("CLIPFI_RPC_URL", "https://api.devnet.solana.com"))
    program_id: str = field(default_factory=lambda: os.getenv("CLIPFI_PROGRAM_ID", "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./clipfi.db"))
    poll_seconds: float = field(default_factory=lambda: float(os.getenv("CLIPFI_POLL_SECONDS", "5")))
    idl_path: Path = field(default_factory=lambda: Path(os.getenv("CLIPFI_IDL_PATH", str(IDL_PATH))))
    margin_bps: int = field(default_factory=lambda: int(os.getenv("CLIPFI_MARGIN_BPS", "1500")))
    denylist: list = field(default_factory=lambda: _list(os.getenv("CLIPFI_DENYLIST", "")))
    issuer_keypair: str = field(default_factory=lambda: os.getenv("CLIPFI_ISSUER_KEYPAIR", ""))
    clipusd_mint: str = field(default_factory=lambda: os.getenv("CLIPFI_CLIPUSD_MINT", ""))
    indexer_port: int = field(default_factory=lambda: int(os.getenv("CLIPFI_INDEXER_PORT", "8001")))
    partner_port: int = field(default_factory=lambda: int(os.getenv("CLIPFI_PARTNER_PORT", "8002")))
    partner_token: str = field(default_factory=lambda: os.getenv("CLIPFI_PARTNER_TOKEN", ""))

    @property
    def database_url_normalized(self):
        u = self.database_url
        if u.startswith("postgresql://"):
            return "postgresql+asyncpg://" + u[len("postgresql://"):]
        if u.startswith("postgres://"):
            return "postgresql+asyncpg://" + u[len("postgres://"):]
        if u.startswith("sqlite://") and "+aiosqlite" not in u:
            return "sqlite+aiosqlite://" + u[len("sqlite://"):]
        return u


settings = Settings()
