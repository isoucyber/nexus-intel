"""Par de chaves de identidade de cada perfil (biblioteca `cryptography`).

- X25519: acordo de chaves, para enviar projetos a destinatários específicos.
- Ed25519: assinatura digital dos pacotes .nexus exportados pelo perfil.

As chaves privadas nunca ficam em claro no disco: são cifradas com AES-256-GCM
por uma subchave HKDF da chave mestra do perfil (AAD = tipo da chave). A chave
pública é identificada por uma impressão digital SHA-256.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from nexus_intel.infrastructure.crypto.keys import SecretKey, b64d, b64e, hkdf, unwrap, wrap

KINDS = ("x25519", "ed25519")
_RAW = serialization.Encoding.Raw


def _aad(kind: str) -> bytes:
    return f"nexus-intel/identity/{kind}/v1".encode()


def fingerprint(public_raw: bytes) -> str:
    """16 bytes do SHA-256 da chave pública, em grupos de 4 hex: fácil de conferir por telefone."""
    h = hashlib.sha256(public_raw).hexdigest()[:32].upper()
    return " ".join(h[i:i + 4] for i in range(0, 32, 4))


@dataclass(frozen=True)
class StoredKey:
    kind: str
    public_b64: str
    wrapped: dict[str, str]


def generate(kind: str, master: SecretKey) -> StoredKey:
    if kind == "x25519":
        priv_x = X25519PrivateKey.generate()
        priv_raw = priv_x.private_bytes(_RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        pub_raw = priv_x.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    elif kind == "ed25519":
        priv_e = Ed25519PrivateKey.generate()
        priv_raw = priv_e.private_bytes(_RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        pub_raw = priv_e.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    else:
        raise ValueError("tipo de chave desconhecido")
    kek = hkdf(master, "nexus-intel/identity-kek/v1")
    try:
        return StoredKey(kind, b64e(pub_raw), wrap(kek, priv_raw, _aad(kind)))
    finally:
        kek.wipe()


def unwrap_private(stored: StoredKey, master: SecretKey) -> bytes:
    kek = hkdf(master, "nexus-intel/identity-kek/v1")
    try:
        return unwrap(kek, stored.wrapped, _aad(stored.kind))
    finally:
        kek.wipe()


def ed25519_private(raw: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(raw)


def ed25519_public(raw: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(raw)


def x25519_private(raw: bytes) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(raw)


def x25519_public(raw: bytes) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(raw)


def public_raw(stored: StoredKey) -> bytes:
    return b64d(stored.public_b64)
