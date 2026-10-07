import asyncio
import logging

import httpx

from app.indexer.models import Cursor
from app.indexer.projections import apply_transaction
from app.settings import settings

log = logging.getLogger("clipfi.indexer")
CURSOR_KEY = "last_signature"


class RpcClient:
    def __init__(self, url, client=None):
        self.url = url
        self.client = client or httpx.AsyncClient(timeout=30)
        self._id = 0

    async def call(self, method, params):
        self._id += 1
        r = await self.client.post(self.url, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"rpc {method}: {body['error']}")
        return body.get("result")

    async def signatures(self, address, before=None, until=None, limit=1000):
        opts = {"limit": limit, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        return await self.call("getSignaturesForAddress", [address, opts]) or []

    async def transaction(self, signature):
        return await self.call("getTransaction", [signature, {
            "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed",
        }])

    async def close(self):
        await self.client.aclose()


class Poller:
    def __init__(self, db, decoder, rpc=None, program_id=None):
        self.db = db
        self.decoder = decoder
        self.rpc = rpc or RpcClient(settings.rpc_url)
        self.program_id = program_id or settings.program_id

    async def last_signature(self):
        async with self.db.session() as s:
            c = await s.get(Cursor, CURSOR_KEY)
            return c.value if c else None

    async def set_last_signature(self, session, sig):
        c = await session.get(Cursor, CURSOR_KEY)
        if c is None:
            session.add(Cursor(key=CURSOR_KEY, value=sig))
        else:
            c.value = sig

    async def collect_new(self, until):
        out = []
        before = None
        while True:
            page = await self.rpc.signatures(self.program_id, before=before, until=until)
            if not page:
                break
            out.extend(page)
            if len(page) < 1000:
                break
            before = page[-1]["signature"]
        return out

    async def poll_once(self):
        until = await self.last_signature()
        infos = await self.collect_new(until)
        processed = 0
        for info in reversed(infos):
            sig = info["signature"]
            if info.get("err"):
                async with self.db.session() as s:
                    await self.set_last_signature(s, sig)
                    await s.commit()
                continue
            tx = await self.rpc.transaction(sig)
            if tx is None:
                continue
            logs = (tx.get("meta") or {}).get("logMessages") or []
            async with self.db.session() as s:
                processed += await apply_transaction(s, self.decoder, sig, tx.get("slot", info.get("slot", 0)), tx.get("blockTime"), logs)
                await self.set_last_signature(s, sig)
                await s.commit()
        return processed

    async def run(self, interval=None, stop=None):
        interval = settings.poll_seconds if interval is None else interval
        while not (stop and stop.is_set()):
            try:
                n = await self.poll_once()
                if n:
                    log.info("indexed %d events", n)
            except Exception as e:
                log.warning("poll failed: %s", e)
            await asyncio.sleep(interval)
