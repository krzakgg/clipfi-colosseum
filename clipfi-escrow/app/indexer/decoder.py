import base64
import json

from app.indexer.borsh import Codec, Reader
from app.settings import settings

PREFIX = "Program data: "


class EventDecoder:
    def __init__(self, idl):
        self.idl = idl
        self.codec = Codec(idl)
        self.by_disc = {bytes(e["discriminator"]): e["name"] for e in idl.get("events", [])}

    @classmethod
    def from_file(cls, path=None):
        with open(path or settings.idl_path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def decode_payload(self, raw):
        if len(raw) < 8:
            return None
        name = self.by_disc.get(bytes(raw[:8]))
        if name is None:
            return None
        r = Reader(raw)
        r.pos = 8
        return name, self.codec.decode_fields(self.codec.types[name]["fields"], r)

    def decode_log_line(self, line):
        if not line.startswith(PREFIX):
            return None
        try:
            raw = base64.b64decode(line[len(PREFIX):].strip())
            return self.decode_payload(raw)
        except (ValueError, KeyError, IndexError):
            return None

    def decode_logs(self, lines):
        out = []
        for line in lines or []:
            ev = self.decode_log_line(line)
            if ev:
                out.append(ev)
        return out

    def encode_event(self, name, fields):
        disc = next(bytes(e["discriminator"]) for e in self.idl["events"] if e["name"] == name)
        return disc + self.codec.encode_fields(self.codec.types[name]["fields"], fields)

    def build_log_line(self, name, fields):
        return PREFIX + base64.b64encode(self.encode_event(name, fields)).decode()
