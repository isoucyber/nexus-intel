"""Armazenamento de arquivos anexados, endereçado pelo SHA-256 do conteúdo.

Layout: <projeto>/blobs/<2 primeiros hex>/<sha256>.blob

Formato do arquivo:
- cifrado:  b"NXB1" + nonce (12 bytes, aleatório) + AES-256-GCM(conteúdo)
  AAD = b"nexus-intel/blob/v1/" + sha256 (o arquivo não pode ser trocado por outro)
- sem cifragem (projeto em modo "só login"): b"NXB0" + conteúdo

A leitura sempre confere o SHA-256 do conteúdo. O nome do arquivo é validado
como 64 dígitos hexadecimais, então nenhum caminho externo é aceito.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexus_intel.domain.errors import BlobCorrupted
from nexus_intel.infrastructure.crypto.keys import NONCE_LEN, SecretKey
from nexus_intel.infrastructure.fsutil import atomic_write_bytes

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ENC, _PLAIN = b"NXB1", b"NXB0"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_sha(sha: str) -> str:
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        raise BlobCorrupted("Identificador de arquivo inválido.")
    return sha


class BlobStore:
    def __init__(self, root: Path, key: SecretKey | None) -> None:
        self.root = root
        self._key = key

    @property
    def encrypted(self) -> bool:
        return self._key is not None

    def close(self) -> None:
        if self._key is not None:
            self._key.wipe()
            self._key = None

    def path_for(self, sha: str) -> Path:
        check_sha(sha)
        return self.root / sha[:2] / f"{sha}.blob"

    def exists(self, sha: str) -> bool:
        return self.path_for(sha).exists()

    def put(self, data: bytes) -> str:
        sha = sha256_hex(data)
        path = self.path_for(sha)
        if path.exists():
            return sha  # mesmo conteúdo já guardado: deduplicação
        if self._key is not None:
            nonce = os.urandom(NONCE_LEN)  # chave fixa por projeto: nonce aleatório de 96 bits
            ct = AESGCM(self._key.bytes()).encrypt(nonce, data, b"nexus-intel/blob/v1/" + sha.encode())
            payload = _ENC + nonce + ct
        else:
            payload = _PLAIN + data
        atomic_write_bytes(path, payload)
        return sha

    def get(self, sha: str) -> bytes:
        path = self.path_for(sha)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobCorrupted("Um arquivo anexado não foi encontrado na pasta do projeto.") from exc
        head, body = raw[:4], raw[4:]
        if head == _ENC:
            if self._key is None:
                raise BlobCorrupted()
            try:
                data = AESGCM(self._key.bytes()).decrypt(
                    body[:NONCE_LEN], body[NONCE_LEN:], b"nexus-intel/blob/v1/" + sha.encode())
            except InvalidTag as exc:
                raise BlobCorrupted() from exc
        elif head == _PLAIN and self._key is None:
            data = body
        else:
            raise BlobCorrupted()
        if sha256_hex(data) != sha:
            raise BlobCorrupted()
        return data

    def list_shas(self) -> list[str]:
        if not self.root.exists():
            return []
        out = []
        for f in self.root.glob("*/*.blob"):
            sha = f.stem
            if SHA_RE.match(sha) and f.parent.name == sha[:2]:
                out.append(sha)
        return out

    def delete(self, sha: str) -> None:
        path = self.path_for(sha)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        with contextlib.suppress(OSError):
            path.parent.rmdir()  # só some se estiver vazia
