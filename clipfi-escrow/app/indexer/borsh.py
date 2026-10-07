import struct

_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INT = {
    "u8": (1, False), "i8": (1, True), "u16": (2, False), "i16": (2, True),
    "u32": (4, False), "i32": (4, True), "u64": (8, False), "i64": (8, True),
    "u128": (16, False), "i128": (16, True),
}


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = bytearray()
    while n:
        n, r = divmod(n, 58)
        out.append(_ALPHABET[r])
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return (b"1" * pad + bytes(out[::-1])).decode()


def b58decode(s):
    n = 0
    for c in s.encode():
        n = n * 58 + _ALPHABET.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\0" * pad + raw


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("borsh: truncated")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b


def _defined_name(d):
    return d["name"] if isinstance(d, dict) else d


def _named(fields):
    return bool(fields) and isinstance(fields[0], dict) and "name" in fields[0]


class Codec:
    def __init__(self, idl):
        self.types = {t["name"]: t["type"] for t in idl.get("types", [])}

    def decode(self, ty, r):
        if isinstance(ty, str):
            if ty in _INT:
                size, signed = _INT[ty]
                return int.from_bytes(r.take(size), "little", signed=signed)
            if ty == "bool":
                return r.take(1)[0] != 0
            if ty == "f32":
                return struct.unpack("<f", r.take(4))[0]
            if ty == "f64":
                return struct.unpack("<d", r.take(8))[0]
            if ty in ("pubkey", "publicKey"):
                return b58encode(r.take(32))
            if ty == "string":
                return r.take(self.decode("u32", r)).decode()
            if ty == "bytes":
                return r.take(self.decode("u32", r)).hex()
            raise ValueError(f"borsh: unknown type {ty}")
        if "array" in ty:
            inner, n = ty["array"]
            if inner == "u8":
                return r.take(n).hex()
            return [self.decode(inner, r) for _ in range(n)]
        if "vec" in ty:
            n = self.decode("u32", r)
            if ty["vec"] == "u8":
                return r.take(n).hex()
            return [self.decode(ty["vec"], r) for _ in range(n)]
        if "option" in ty:
            return self.decode(ty["option"], r) if r.take(1)[0] else None
        if "defined" in ty:
            return self.decode_defined(_defined_name(ty["defined"]), r)
        raise ValueError(f"borsh: unsupported {ty}")

    def decode_defined(self, name, r):
        t = self.types[name]
        if t["kind"] == "struct":
            return self.decode_fields(t.get("fields", []), r)
        if t["kind"] == "enum":
            idx = r.take(1)[0]
            v = t["variants"][idx]
            fields = v.get("fields")
            if not fields:
                return v["name"]
            return {v["name"]: self.decode_fields(fields, r)}
        raise ValueError(f"borsh: unsupported kind {t['kind']}")

    def decode_fields(self, fields, r):
        if _named(fields):
            return {f["name"]: self.decode(f["type"], r) for f in fields}
        return [self.decode(f, r) for f in fields]

    def encode(self, ty, v):
        if isinstance(ty, str):
            if ty in _INT:
                size, signed = _INT[ty]
                return int(v).to_bytes(size, "little", signed=signed)
            if ty == "bool":
                return b"\x01" if v else b"\x00"
            if ty == "f32":
                return struct.pack("<f", v)
            if ty == "f64":
                return struct.pack("<d", v)
            if ty in ("pubkey", "publicKey"):
                return b58decode(v).rjust(32, b"\0")
            if ty == "string":
                b = v.encode()
                return self.encode("u32", len(b)) + b
            if ty == "bytes":
                b = bytes.fromhex(v) if isinstance(v, str) else bytes(v)
                return self.encode("u32", len(b)) + b
            raise ValueError(f"borsh: unknown type {ty}")
        if "array" in ty:
            inner, n = ty["array"]
            if inner == "u8":
                b = bytes.fromhex(v) if isinstance(v, str) else bytes(v)
                if len(b) != n:
                    raise ValueError("borsh: array length")
                return b
            return b"".join(self.encode(inner, x) for x in v)
        if "vec" in ty:
            if ty["vec"] == "u8":
                b = bytes.fromhex(v) if isinstance(v, str) else bytes(v)
                return self.encode("u32", len(b)) + b
            return self.encode("u32", len(v)) + b"".join(self.encode(ty["vec"], x) for x in v)
        if "option" in ty:
            return b"\x00" if v is None else b"\x01" + self.encode(ty["option"], v)
        if "defined" in ty:
            return self.encode_defined(_defined_name(ty["defined"]), v)
        raise ValueError(f"borsh: unsupported {ty}")

    def encode_defined(self, name, v):
        t = self.types[name]
        if t["kind"] == "struct":
            return self.encode_fields(t.get("fields", []), v)
        if t["kind"] == "enum":
            vname = v if isinstance(v, str) else next(iter(v))
            idx = next(i for i, x in enumerate(t["variants"]) if x["name"] == vname)
            fields = t["variants"][idx].get("fields")
            if not fields:
                return bytes([idx])
            return bytes([idx]) + self.encode_fields(fields, v[vname])
        raise ValueError(f"borsh: unsupported kind {t['kind']}")

    def encode_fields(self, fields, v):
        if _named(fields):
            return b"".join(self.encode(f["type"], v[f["name"]]) for f in fields)
        return b"".join(self.encode(f, x) for f, x in zip(fields, v))
