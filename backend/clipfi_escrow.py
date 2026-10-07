import base64
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

_INT_FORMATS = {
    "u8": ("<B", 1), "i8": ("<b", 1), "u16": ("<H", 2), "i16": ("<h", 2),
    "u32": ("<I", 4), "i32": ("<i", 4), "u64": ("<Q", 8), "i64": ("<q", 8),
    "f32": ("<f", 4), "f64": ("<d", 8),
}
_WIDE_INTS = {"u128": (16, False), "i128": (16, True), "u256": (32, False), "i256": (32, True)}
_IDL_PATH_CANDIDATES = (
    "../clipfi/idl/clipfi_escrow.json",
    "../../clipfi/idl/clipfi_escrow.json",
    "../clipfi-escrow/idl/clipfi_escrow.json",
    "../clipfi-escrow/target/idl/clipfi_escrow.json",
)


class IdlError(Exception):
    pass


def anchor_discriminator(name: str, namespace: str = "global") -> bytes:
    return hashlib.sha256(f"{namespace}:{name}".encode("utf-8")).digest()[:8]


def associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    address, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)], ASSOCIATED_TOKEN_PROGRAM_ID
    )
    return address


def to_pubkey(value: Any) -> Pubkey:
    if isinstance(value, Pubkey):
        return value
    if isinstance(value, (bytes, bytearray)):
        return Pubkey.from_bytes(bytes(value))
    return Pubkey.from_string(str(value))


def resolve_idl_path(configured: str | None, base_dir: Path | None = None) -> Path:
    base = base_dir or Path(__file__).resolve().parent
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = base / path
        if path.is_file():
            return path
        raise IdlError(f"IDL not found at {path}")
    for candidate in _IDL_PATH_CANDIDATES:
        path = (base / candidate).resolve()
        if path.is_file():
            return path
    raise IdlError("IDL clipfi_escrow.json not found; set SOLANA_ESCROW_IDL_PATH")


class BorshCodec:
    def __init__(self, types: dict[str, dict]) -> None:
        self._types = types

    def encode(self, ty: Any, value: Any) -> bytes:
        if isinstance(ty, str):
            return self._encode_primitive(ty, value)
        if "array" in ty:
            inner, length = ty["array"]
            if len(value) != length:
                raise IdlError(f"array length {len(value)} != {length}")
            return b"".join(self.encode(inner, item) for item in value)
        if "vec" in ty:
            return struct.pack("<I", len(value)) + b"".join(self.encode(ty["vec"], item) for item in value)
        if "option" in ty:
            if value is None:
                return b"\x00"
            return b"\x01" + self.encode(ty["option"], value)
        if "coption" in ty:
            if value is None:
                return b"\x00\x00\x00\x00"
            return b"\x01\x00\x00\x00" + self.encode(ty["coption"], value)
        if "defined" in ty:
            return self._encode_defined(self._defined_name(ty), value)
        raise IdlError(f"unsupported type {ty!r}")

    def decode(self, ty: Any, data: bytes, offset: int = 0) -> tuple[Any, int]:
        if isinstance(ty, str):
            return self._decode_primitive(ty, data, offset)
        if "array" in ty:
            inner, length = ty["array"]
            items = []
            for _ in range(length):
                item, offset = self.decode(inner, data, offset)
                items.append(item)
            return items, offset
        if "vec" in ty:
            (length,) = struct.unpack_from("<I", data, offset)
            offset += 4
            items = []
            for _ in range(length):
                item, offset = self.decode(ty["vec"], data, offset)
                items.append(item)
            return items, offset
        if "option" in ty:
            flag = data[offset]
            offset += 1
            if flag == 0:
                return None, offset
            return self.decode(ty["option"], data, offset)
        if "coption" in ty:
            (flag,) = struct.unpack_from("<I", data, offset)
            offset += 4
            if flag == 0:
                return None, offset
            return self.decode(ty["coption"], data, offset)
        if "defined" in ty:
            return self._decode_defined(self._defined_name(ty), data, offset)
        raise IdlError(f"unsupported type {ty!r}")

    def encode_struct(self, fields: list[dict], value: dict) -> bytes:
        out = []
        for field in fields:
            if field["name"] not in value:
                raise IdlError(f"missing field {field['name']}")
            out.append(self.encode(field["type"], value[field["name"]]))
        return b"".join(out)

    def decode_struct(self, fields: list[dict], data: bytes, offset: int = 0) -> tuple[dict, int]:
        result = {}
        for field in fields:
            result[field["name"]], offset = self.decode(field["type"], data, offset)
        return result, offset

    def struct_fields(self, name: str) -> list[dict]:
        definition = self._types.get(name)
        if not definition or definition.get("kind") != "struct":
            raise IdlError(f"struct type {name} not in IDL")
        return definition["fields"]

    @staticmethod
    def _defined_name(ty: dict) -> str:
        defined = ty["defined"]
        return defined["name"] if isinstance(defined, dict) else defined

    def _encode_primitive(self, ty: str, value: Any) -> bytes:
        if ty in _INT_FORMATS:
            fmt, _ = _INT_FORMATS[ty]
            return struct.pack(fmt, value)
        if ty in _WIDE_INTS:
            size, signed = _WIDE_INTS[ty]
            return int(value).to_bytes(size, "little", signed=signed)
        if ty == "bool":
            return b"\x01" if value else b"\x00"
        if ty == "pubkey" or ty == "publicKey":
            return bytes(to_pubkey(value))
        if ty == "string":
            raw = value.encode("utf-8")
            return struct.pack("<I", len(raw)) + raw
        if ty == "bytes":
            raw = bytes(value)
            return struct.pack("<I", len(raw)) + raw
        raise IdlError(f"unsupported primitive {ty}")

    def _decode_primitive(self, ty: str, data: bytes, offset: int) -> tuple[Any, int]:
        if ty in _INT_FORMATS:
            fmt, size = _INT_FORMATS[ty]
            (value,) = struct.unpack_from(fmt, data, offset)
            return value, offset + size
        if ty in _WIDE_INTS:
            size, signed = _WIDE_INTS[ty]
            return int.from_bytes(data[offset:offset + size], "little", signed=signed), offset + size
        if ty == "bool":
            return data[offset] != 0, offset + 1
        if ty == "pubkey" or ty == "publicKey":
            return str(Pubkey.from_bytes(data[offset:offset + 32])), offset + 32
        if ty == "string":
            (length,) = struct.unpack_from("<I", data, offset)
            offset += 4
            return data[offset:offset + length].decode("utf-8"), offset + length
        if ty == "bytes":
            (length,) = struct.unpack_from("<I", data, offset)
            offset += 4
            return bytes(data[offset:offset + length]), offset + length
        raise IdlError(f"unsupported primitive {ty}")

    def _encode_defined(self, name: str, value: Any) -> bytes:
        definition = self._types.get(name)
        if not definition:
            raise IdlError(f"type {name} not in IDL")
        kind = definition.get("kind")
        if kind == "struct":
            return self.encode_struct(definition["fields"], value)
        if kind == "enum":
            return self._encode_enum(definition["variants"], value)
        if kind == "type":
            return self.encode(definition["alias"], value)
        raise IdlError(f"unsupported kind {kind}")

    def _decode_defined(self, name: str, data: bytes, offset: int) -> tuple[Any, int]:
        definition = self._types.get(name)
        if not definition:
            raise IdlError(f"type {name} not in IDL")
        kind = definition.get("kind")
        if kind == "struct":
            return self.decode_struct(definition["fields"], data, offset)
        if kind == "enum":
            return self._decode_enum(definition["variants"], data, offset)
        if kind == "type":
            return self.decode(definition["alias"], data, offset)
        raise IdlError(f"unsupported kind {kind}")

    def _encode_enum(self, variants: list[dict], value: Any) -> bytes:
        if isinstance(value, str):
            variant_name, payload = value, None
        elif isinstance(value, dict) and len(value) == 1:
            (variant_name, payload), = value.items()
        else:
            raise IdlError(f"bad enum value {value!r}")
        for index, variant in enumerate(variants):
            if variant["name"] != variant_name:
                continue
            out = struct.pack("<B", index)
            fields = variant.get("fields") or []
            if not fields:
                return out
            if isinstance(fields[0], dict) and "name" in fields[0]:
                return out + self.encode_struct(fields, payload)
            return out + b"".join(self.encode(ty, item) for ty, item in zip(fields, payload))
        raise IdlError(f"unknown enum variant {variant_name}")

    def _decode_enum(self, variants: list[dict], data: bytes, offset: int) -> tuple[Any, int]:
        index = data[offset]
        offset += 1
        if index >= len(variants):
            raise IdlError(f"enum index {index} out of range")
        variant = variants[index]
        fields = variant.get("fields") or []
        if not fields:
            return variant["name"], offset
        if isinstance(fields[0], dict) and "name" in fields[0]:
            payload, offset = self.decode_struct(fields, data, offset)
        else:
            payload = []
            for ty in fields:
                item, offset = self.decode(ty, data, offset)
                payload.append(item)
        return {variant["name"]: payload}, offset


class IdlProgram:
    def __init__(self, idl: dict, program_id: Pubkey | str | None = None) -> None:
        self.idl = idl
        self.program_id = to_pubkey(program_id or idl["address"])
        self.codec = BorshCodec({item["name"]: item["type"] for item in idl.get("types", [])})
        self.instructions = {item["name"]: item for item in idl["instructions"]}
        self.accounts = {item["name"]: item for item in idl.get("accounts", [])}

    @classmethod
    def load(cls, path: Path | str, program_id: Pubkey | str | None = None) -> "IdlProgram":
        with open(path, "r", encoding="utf-8") as handle:
            return cls(json.load(handle), program_id)

    def instruction_discriminator(self, name: str) -> bytes:
        spec = self.instructions.get(name)
        if spec is None:
            raise IdlError(f"instruction {name} not in IDL")
        if spec.get("discriminator"):
            return bytes(spec["discriminator"])
        return anchor_discriminator(name)

    def account_discriminator(self, name: str) -> bytes:
        spec = self.accounts.get(name)
        if spec is None:
            raise IdlError(f"account {name} not in IDL")
        if spec.get("discriminator"):
            return bytes(spec["discriminator"])
        return anchor_discriminator(name, "account")

    def account_fields(self, name: str) -> list[dict]:
        return self.codec.struct_fields(name)

    def has_account_field(self, name: str, field: str) -> bool:
        return any(item["name"] == field for item in self.account_fields(name))

    def encode_args(self, name: str, args: dict) -> bytes:
        spec = self.instructions[name]
        out = [self.instruction_discriminator(name)]
        for arg in spec.get("args", []):
            if arg["name"] not in args:
                raise IdlError(f"missing arg {arg['name']} for {name}")
            out.append(self.codec.encode(arg["type"], args[arg["name"]]))
        return b"".join(out)

    def encode_account(self, name: str, value: dict) -> bytes:
        return self.account_discriminator(name) + self.codec.encode_struct(self.account_fields(name), value)

    def decode_account(self, name: str, data: bytes) -> dict:
        discriminator = self.account_discriminator(name)
        if data[:8] != discriminator:
            raise IdlError(f"account data is not a {name}")
        value, _ = self.codec.decode_struct(self.account_fields(name), data, 8)
        return value

    def instruction(self, name: str, args: dict | None, accounts: dict[str, Any]) -> Instruction:
        spec = self.instructions.get(name)
        if spec is None:
            raise IdlError(f"instruction {name} not in IDL")
        metas = []
        for account in spec["accounts"]:
            key = account["name"]
            value = accounts.get(key)
            if value is None and account.get("address"):
                value = account["address"]
            if value is None:
                if account.get("optional"):
                    metas.append(AccountMeta(self.program_id, False, False))
                    continue
                raise IdlError(f"missing account {key} for {name}")
            metas.append(AccountMeta(to_pubkey(value), bool(account.get("signer")), bool(account.get("writable"))))
        return Instruction(self.program_id, self.encode_args(name, args or {}), metas)

    def build(self, name: str, args: dict | None, accounts: dict[str, Any]) -> dict:
        return instruction_payload(self.instruction(name, args, accounts))

    def config_pda(self) -> Pubkey:
        return Pubkey.find_program_address([b"config"], self.program_id)[0]

    def campaign_pda(self, brand: Pubkey, campaign_id: int) -> Pubkey:
        return Pubkey.find_program_address(
            [b"campaign", bytes(brand), int(campaign_id).to_bytes(8, "little")], self.program_id
        )[0]

    def position_pda(self, campaign: Pubkey, creator: Pubkey) -> Pubkey:
        return Pubkey.find_program_address([b"position", bytes(campaign), bytes(creator)], self.program_id)[0]

    def payout_pda(self, campaign: Pubkey, creator: Pubkey, epoch: int) -> Pubkey:
        return Pubkey.find_program_address(
            [b"payout", bytes(campaign), bytes(creator), int(epoch).to_bytes(8, "little")], self.program_id
        )[0]

    def stake_pda(self, creator: Pubkey) -> Pubkey:
        return Pubkey.find_program_address([b"stake", bytes(creator)], self.program_id)[0]


def instruction_payload(instruction: Instruction) -> dict:
    return {
        "program_id": str(instruction.program_id),
        "data": base64.b64encode(bytes(instruction.data)).decode("ascii"),
        "accounts": [
            {"pubkey": str(meta.pubkey), "is_signer": meta.is_signer, "is_writable": meta.is_writable}
            for meta in instruction.accounts
        ],
    }


def instruction_from_payload(payload: dict) -> Instruction:
    return Instruction(
        Pubkey.from_string(payload["program_id"]),
        base64.b64decode(payload["data"]),
        [
            AccountMeta(Pubkey.from_string(item["pubkey"]), item["is_signer"], item["is_writable"])
            for item in payload["accounts"]
        ],
    )


def account_field_offset(program: IdlProgram, account: str, field: str) -> int:
    offset = 8
    for item in program.account_fields(account):
        if item["name"] == field:
            return offset
        offset += _fixed_size(program.codec, item["type"])
    raise IdlError(f"field {field} not in {account}")


def _fixed_size(codec: BorshCodec, ty: Any) -> int:
    if isinstance(ty, str):
        if ty in _INT_FORMATS:
            return _INT_FORMATS[ty][1]
        if ty in _WIDE_INTS:
            return _WIDE_INTS[ty][0]
        if ty == "bool":
            return 1
        if ty in ("pubkey", "publicKey"):
            return 32
        raise IdlError(f"{ty} has no fixed size")
    if "array" in ty:
        inner, length = ty["array"]
        return _fixed_size(codec, inner) * length
    if "defined" in ty:
        definition = codec._types[BorshCodec._defined_name(ty)]
        if definition["kind"] == "struct":
            return sum(_fixed_size(codec, field["type"]) for field in definition["fields"])
        if definition["kind"] == "enum" and all(not variant.get("fields") for variant in definition["variants"]):
            return 1
    raise IdlError(f"{ty!r} has no fixed size")
