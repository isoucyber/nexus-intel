"""Primitivas criptográficas (seção 12.2).

- Argon2id (da biblioteca `cryptography`) deriva a KEK da senha.
- HKDF-SHA256 deriva subchaves com rótulos distintos.
- AES-256-GCM cifra chaves (wrap) e blocos de arquivo.

Limitação registrada: o Python não garante ausência de cópias na memória.
`SecretKey` guarda o material num bytearray que é zerado em `wipe()`, mas
as bibliotecas podem fazer cópias internas. É mitigação, não garantia.
"""

from __future__ import annotations

import base64
import os
import secrets
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_LEN = 32
NONCE_LEN = 12

# Pisos contra rebaixamento: um vault.json editado com parâmetros fracos é recusado.
MIN_MEMORY_KIB = 64 * 1024
MIN_ITERATIONS = 2
DEFAULT_MEMORY_KIB = 256 * 1024
DEFAULT_ITERATIONS = 3
DEFAULT_LANES = 4


class SecretKey:
    """Chave de 256 bits em memória apagável."""

    __slots__ = ("_buf",)

    def __init__(self, material: bytes | bytearray) -> None:
        if len(material) != KEY_LEN:
            raise ValueError("chave deve ter 32 bytes")
        self._buf: bytearray | None = bytearray(material)

    @classmethod
    def generate(cls) -> SecretKey:
        return cls(secrets.token_bytes(KEY_LEN))

    @property
    def wiped(self) -> bool:
        return self._buf is None

    def bytes(self) -> bytes:
        if self._buf is None:
            raise RuntimeError("chave já apagada")
        return bytes(self._buf)

    def hex(self) -> str:
        return self.bytes().hex()

    def wipe(self) -> None:
        if self._buf is not None:
            for i in range(len(self._buf)):
                self._buf[i] = 0
            self._buf = None

    def __repr__(self) -> str:  # nunca vaza material em logs
        return "<SecretKey wiped>" if self.wiped else "<SecretKey ***>"

    def __del__(self) -> None:
        self.wipe()


@dataclass(frozen=True)
class KdfParams:
    memory_kib: int = DEFAULT_MEMORY_KIB
    iterations: int = DEFAULT_ITERATIONS
    lanes: int = DEFAULT_LANES

    def check_floor(self) -> None:
        if self.memory_kib < MIN_MEMORY_KIB or self.iterations < MIN_ITERATIONS:
            raise ValueError("parâmetros de derivação abaixo do mínimo de segurança")

    def to_json(self) -> dict[str, int]:
        return {"m": self.memory_kib, "t": self.iterations, "p": self.lanes}

    @classmethod
    def from_json(cls, data: dict[str, int]) -> KdfParams:
        return cls(memory_kib=int(data["m"]), iterations=int(data["t"]), lanes=int(data["p"]))


def derive_password_kek(password: str, salt: bytes, params: KdfParams) -> SecretKey:
    params.check_floor()
    kdf = Argon2id(
        salt=salt,
        length=KEY_LEN,
        iterations=params.iterations,
        lanes=params.lanes,
        memory_cost=params.memory_kib,
    )
    return SecretKey(kdf.derive(password.encode("utf-8")))


def calibrate_kdf(target_seconds: float = 1.0, max_memory_kib: int = DEFAULT_MEMORY_KIB) -> KdfParams:
    """Reduz a memória em máquinas lentas ou com pouca RAM, sem passar do piso."""
    memory = max_memory_kib
    while True:
        params = KdfParams(memory_kib=memory)
        start = time.perf_counter()
        try:
            derive_password_kek("calibracao", os.urandom(16), params).wipe()
        except MemoryError:
            elapsed = float("inf")
        else:
            elapsed = time.perf_counter() - start
        if elapsed <= target_seconds * 1.5 or memory // 2 < MIN_MEMORY_KIB:
            return params
        memory //= 2


def hkdf(key: SecretKey, info: str, salt: bytes | None = None) -> SecretKey:
    out = HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=salt, info=info.encode()).derive(
        key.bytes()
    )
    return SecretKey(out)


def wrap(kek: SecretKey, plaintext: bytes, aad: bytes) -> dict[str, str]:
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(kek.bytes()).encrypt(nonce, plaintext, aad)
    return {"nonce": b64e(nonce), "ct": b64e(ct)}


def unwrap(kek: SecretKey, blob: dict[str, str], aad: bytes) -> bytes:
    """Lança InvalidTag se a chave estiver errada ou o dado adulterado."""
    return AESGCM(kek.bytes()).decrypt(b64d(blob["nonce"]), b64d(blob["ct"]), aad)


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


# --- Chave de recuperação -------------------------------------------------
# 256 bits em Base32 sem preenchimento = 52 caracteres, agrupados de 4 em 4
# (13 grupos). Corrige a inconsistência "40 caracteres" da especificação.

_RECOVERY_GROUP = 4


def new_recovery_secret() -> bytes:
    return secrets.token_bytes(KEY_LEN)


def format_recovery_key(secret: bytes) -> str:
    text = base64.b32encode(secret).decode("ascii").rstrip("=")
    return "-".join(text[i : i + _RECOVERY_GROUP] for i in range(0, len(text), _RECOVERY_GROUP))


def parse_recovery_key(text: str) -> bytes:
    clean = "".join(ch for ch in text.upper() if ch.isalnum())
    # Erros comuns de digitação: O→0 não existe em Base32 RFC 4648; 0→O, 1→I, 8→B.
    clean = clean.translate(str.maketrans({"0": "O", "1": "I", "8": "B"}))
    if len(clean) != 52:
        raise ValueError("a chave de recuperação tem 52 caracteres")
    data = base64.b32decode(clean + "====")
    if len(data) != KEY_LEN:
        raise ValueError("chave de recuperação inválida")
    return data


__all__ = [
    "InvalidTag",
    "KdfParams",
    "SecretKey",
    "calibrate_kdf",
    "derive_password_kek",
    "format_recovery_key",
    "hkdf",
    "new_recovery_secret",
    "parse_recovery_key",
    "unwrap",
    "wrap",
]
