from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    database_echo: bool = False

    tracking_internal_url: str = "http://api-internal:8000"
    tracking_redirect_base: str = "http://localhost:8080/r"
    tracking_service_token: SecretStr
    tracking_timeout: float = Field(default=5.0, gt=0)
    solana_cluster: str = "devnet"
    solana_rpc_url: str = "https://api.devnet.solana.com"
    solana_treasury_address: str = ""
    solana_treasury_private_key: SecretStr | None = None
    solana_platform_fee_wallet_address: str = ""
    solana_company_deposit_fee_bps: int = Field(default=100, ge=0, le=10_000)
    solana_company_withdrawal_fee_bps: int = Field(default=100, ge=0, le=10_000)
    solana_creator_withdrawal_fee_bps: int = Field(default=100, ge=0, le=10_000)
    solana_max_withdrawal_lamports: int = Field(default=10_000_000_000, gt=0)
    solana_daily_withdrawal_limit_lamports: int = Field(
        default=50_000_000_000, gt=0
    )
    solana_internal_currency_per_sol: float = Field(default=1.0, gt=0)
    solana_escrow_program_id: str = "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
    solana_escrow_idl_path: str = ""
    solana_oracle_token: SecretStr = SecretStr("")
    solana_bmoney_mint: str = ""
    solana_bmoney_decimals: int = Field(default=6, ge=0, le=18)


@lru_cache
def get_settings() -> Settings:
    return Settings()
