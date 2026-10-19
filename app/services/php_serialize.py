"""Serialisation PHP minimale (listes, dictionnaires, chaines, nombres, booleens, null).

Le champ `services.s_options` est ecrit en PHP serialise par le backend Node (`phpSerialize`) et relu par les apps
Trankyl (`phpUnserialize`). L'Academy ecrit donc le MEME format, et sait lire ce format comme du JSON."""
from __future__ import annotations

import json
from typing import Any


def dumps(val: Any) -> str:
    if val is None:
        return "N;"
    if isinstance(val, bool):
        return f"b:{int(val)};"
    if isinstance(val, int):
        return f"i:{val};"
    if isinstance(val, float):
        return f"d:{val};"
    if isinstance(val, str):
        return f's:{len(val.encode("utf-8"))}:"{val}";'
    if isinstance(val, (list, tuple)):
        return f"a:{len(val)}:{{" + "".join(dumps(i) + dumps(v) for i, v in enumerate(val)) + "}"
    if isinstance(val, dict):
        return f"a:{len(val)}:{{" + "".join(dumps(int(k) if isinstance(k, str) and k.isdigit() else k) + dumps(v) for k, v in val.items()) + "}"
    return "N;"


def loads(raw: str | None) -> Any:
    """PHP serialise -> objets Python. None si illisible."""
    if not raw:
        return None
    data = raw.encode("utf-8")
    pos = 0

    def read_until(ch: bytes) -> bytes:
        nonlocal pos
        end = data.index(ch, pos)
        out = data[pos:end]
        pos = end + 1
        return out

    def parse() -> Any:
        nonlocal pos
        t = data[pos:pos + 1]
        pos += 1
        if t == b"N":
            pos += 1
            return None
        if t == b"b":
            pos += 1
            v = data[pos:pos + 1] == b"1"
            pos += 2
            return v
        if t in (b"i", b"d"):
            pos += 1
            num = read_until(b";").decode()
            return int(num) if t == b"i" else float(num)
        if t == b"s":
            pos += 1
            n = int(read_until(b":"))
            pos += 1  # guillemet ouvrant
            s = data[pos:pos + n].decode("utf-8", "replace")
            pos += n + 2  # chaine + '";'
            return s
        if t == b"a":
            pos += 1
            n = int(read_until(b":"))
            pos += 1  # '{'
            items = []
            for _ in range(n):
                k = parse()
                items.append((k, parse()))
            pos += 1  # '}'
            if all(k == i for i, (k, _) in enumerate(items)):
                return [v for _, v in items]
            return {k: v for k, v in items}
        raise ValueError("type PHP inconnu")

    try:
        return parse()
    except (ValueError, IndexError):
        return None


def load_list(raw: str | None) -> list:
    """Liste a partir d'un champ stocke soit en JSON, soit en PHP serialise."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        data = loads(raw)
    if isinstance(data, dict):
        data = list(data.values())
    return data if isinstance(data, list) else []
