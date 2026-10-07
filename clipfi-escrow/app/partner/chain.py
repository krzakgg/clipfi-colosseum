import json

from app.settings import settings

DECIMALS = 6


class Issuer:
    def __init__(self, keypair_path=None, mint=None, rpc_url=None):
        self.keypair_path = keypair_path or settings.issuer_keypair
        self.mint = mint or settings.clipusd_mint
        self.rpc_url = rpc_url or settings.rpc_url
        self._kp = None

    @property
    def enabled(self):
        return bool(self.keypair_path and self.mint)

    def _load(self):
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey

        if self._kp is None:
            with open(self.keypair_path, "r", encoding="utf-8") as f:
                self._kp = Keypair.from_bytes(bytes(json.load(f)))
        return self._kp, Pubkey.from_string(self.mint)

    @property
    def deposit_address(self):
        if not self.enabled:
            return None
        kp, _ = self._load()
        return str(kp.pubkey())

    async def mint_to(self, wallet, amount):
        from solana.rpc.async_api import AsyncClient
        from solders.pubkey import Pubkey
        from spl.token.async_client import AsyncToken
        from spl.token.constants import TOKEN_PROGRAM_ID

        kp, mint = self._load()
        owner = Pubkey.from_string(wallet)
        async with AsyncClient(self.rpc_url) as client:
            token = AsyncToken(client, mint, TOKEN_PROGRAM_ID, kp)
            ata = await token.create_associated_token_account(owner, skip_confirmation=False)
            res = await token.mint_to(ata, kp, amount)
            return str(res.value)

    async def burn_from(self, wallet, amount):
        from solana.rpc.async_api import AsyncClient
        from solders.pubkey import Pubkey
        from spl.token.async_client import AsyncToken
        from spl.token.constants import TOKEN_PROGRAM_ID
        from spl.token.instructions import get_associated_token_address

        kp, mint = self._load()
        owner = Pubkey.from_string(wallet)
        ata = get_associated_token_address(owner, mint)
        async with AsyncClient(self.rpc_url) as client:
            token = AsyncToken(client, mint, TOKEN_PROGRAM_ID, kp)
            info = await token.get_account_info(ata)
            if info.delegate != kp.pubkey() or info.delegated_amount < amount:
                return None
            res = await token.burn(ata, kp, amount)
            return str(res.value)
