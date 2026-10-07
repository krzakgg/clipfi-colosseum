import base64
import hashlib
import struct

from app.indexer.borsh import b58decode, b58encode
from app.indexer.decoder import EventDecoder

CAMPAIGN = "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
CREATOR = "11111111111111111111111111111112"


def test_base58_roundtrip():
    raw = b58decode(CAMPAIGN).rjust(32, b"\0")
    assert len(raw) == 32
    assert b58encode(raw) == CAMPAIGN
    print(f"base58 roundtrip ok for {CAMPAIGN}")


def test_decode_settled_from_hand_built_log_line(decoder, idl):
    ev = next(e for e in idl["events"] if e["name"] == "Settled")
    fields = next(t for t in idl["types"] if t["name"] == "Settled")["type"]["fields"]
    assert [f["name"] for f in fields] == ["campaign", "creator", "epoch", "units", "amount", "unlock_ts", "evidence_hash"]
    evidence = hashlib.sha256(b"evidence").digest()
    payload = bytes(ev["discriminator"])
    payload += b58decode(CAMPAIGN).rjust(32, b"\0")
    payload += b58decode(CREATOR).rjust(32, b"\0")
    payload += struct.pack("<Q", 7)
    payload += struct.pack("<4Q", 1000, 20, 3, 0)
    payload += struct.pack("<Q", 12_345_678)
    payload += struct.pack("<q", -5)
    payload += evidence
    line = "Program data: " + base64.b64encode(payload).decode()
    print(f"log line: {line[:60]}... ({len(payload)} bytes)")
    name, data = decoder.decode_log_line(line)
    print(f"decoded {name}: {data}")
    assert name == "Settled"
    assert data == {
        "campaign": CAMPAIGN, "creator": CREATOR, "epoch": 7, "units": [1000, 20, 3, 0],
        "amount": 12_345_678, "unlock_ts": -5, "evidence_hash": evidence.hex(),
    }
    assert decoder.encode_event("Settled", data) == payload
    print("encode(decode(payload)) == payload")


def test_every_idl_event_roundtrips(decoder, idl):
    samples = {"pubkey": CAMPAIGN, "u64": 42, "i64": -42, "u32": 3, "u16": 9, "bool": True}
    for ev in idl["events"]:
        fields = next(t for t in idl["types"] if t["name"] == ev["name"])["type"]["fields"]
        data = {}
        for f in fields:
            ty = f["type"]
            if isinstance(ty, str):
                data[f["name"]] = samples[ty]
            elif ty["array"][0] == "u8":
                data[f["name"]] = bytes(range(ty["array"][1])).hex()
            else:
                data[f["name"]] = [1, 2, 3, 4]
        line = decoder.build_log_line(ev["name"], data)
        name, out = decoder.decode_log_line(line)
        assert (name, out) == (ev["name"], data)
        print(f"{ev['name']}: {len(fields)} fields roundtrip ok")


def test_decoder_handles_future_events_from_idl_only():
    idl = {
        "events": [{"name": "Staked", "discriminator": list(hashlib.sha256(b"event:Staked").digest()[:8])}],
        "types": [
            {"name": "Tier", "type": {"kind": "enum", "variants": [{"name": "Bronze"}, {"name": "Gold", "fields": [{"name": "bonus_bps", "type": "u16"}]}]}},
            {"name": "Meta", "type": {"kind": "struct", "fields": [{"name": "note", "type": "string"}, {"name": "tags", "type": {"vec": "u32"}}]}},
            {"name": "Staked", "type": {"kind": "struct", "fields": [
                {"name": "creator", "type": "pubkey"}, {"name": "amount", "type": "u64"}, {"name": "total", "type": "u128"},
                {"name": "unlock_ts", "type": {"option": "i64"}}, {"name": "tier", "type": {"defined": {"name": "Tier"}}},
                {"name": "meta", "type": {"defined": {"name": "Meta"}}}, {"name": "sig", "type": "bytes"},
                {"name": "hash", "type": {"array": ["u8", 32]}}, {"name": "flag", "type": "bool"},
            ]}},
        ],
    }
    d = EventDecoder(idl)
    data = {
        "creator": CREATOR, "amount": 10 ** 9, "total": 2 ** 70, "unlock_ts": None, "tier": {"Gold": {"bonus_bps": 250}},
        "meta": {"note": "hi", "tags": [1, 2]}, "sig": "deadbeef", "hash": "00" * 32, "flag": False,
    }
    name, out = d.decode_log_line(d.build_log_line("Staked", data))
    print(f"future event {name} decoded: {out}")
    assert name == "Staked" and out == data
    data["unlock_ts"] = 99
    data["tier"] = "Bronze"
    assert d.decode_log_line(d.build_log_line("Staked", data))[1] == data
    print("option=Some and unit enum variant ok")


def test_ignores_non_event_lines(decoder):
    assert decoder.decode_log_line("Program log: hello") is None
    assert decoder.decode_log_line("Program data: AAAA") is None
    assert decoder.decode_log_line("Program data: " + base64.b64encode(b"\xff" * 20).decode()) is None
    assert decoder.decode_logs(["Program log: x", "Program data: !!!"]) == []
    print("non-event, short, unknown-discriminator and malformed lines ignored")
