"""Identificadores ULID (seção 1.1, A9).

Implementação própria e pequena para não depender de pacote externo:
48 bits de tempo em ms + 80 bits aleatórios, codificados em Crockford Base32
(26 caracteres, ordenáveis lexicograficamente por tempo).
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}


def new_ulid(timestamp_ms: int | None = None) -> str:
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts < (1 << 48):
        raise ValueError("timestamp fora do intervalo de 48 bits")
    value = (ts << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def is_ulid(text: str) -> bool:
    return len(text) == 26 and all(c in _DECODE for c in text) and text[0] in "01234567"


def ulid_timestamp_ms(ulid: str) -> int:
    if not is_ulid(ulid):
        raise ValueError(f"ULID inválido: {ulid!r}")
    value = 0
    for c in ulid:
        value = (value << 5) | _DECODE[c]
    return value >> 80
