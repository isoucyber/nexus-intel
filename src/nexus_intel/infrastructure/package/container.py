"""Contêiner criptográfico do arquivo `.nexus` (formato 1).

Nada aqui é criptografia própria: só primitivas da biblioteca `cryptography`
(AES-256-GCM, Argon2id, X25519, HKDF-SHA256), combinadas de forma padrão.

Layout do arquivo
-----------------
    MAGIC  b"NEXUSPKG"            8 bytes
    FORMAT 0x01                   1 byte
    HLEN   uint32 big-endian      tamanho do cabeçalho (≤ 64 KiB)
    HEADER JSON UTF-8             parâmetros públicos (sem dados do projeto)
    FRAMES repetidos:
        CLEN uint32 big-endian    tamanho do bloco cifrado (≤ CHUNK + 16)
        CT   AES-256-GCM(K, nonce_i, bloco_i, aad_i)
    fim do arquivo exatamente após o bloco marcado como final

- K (chave de conteúdo, 256 bits) é sorteada com `secrets` para CADA pacote.
- nonce_i = prefixo aleatório (4 bytes, no cabeçalho) || contador i (8 bytes).
  Como K é nova a cada pacote e i nunca se repete, nenhum nonce é reutilizado.
- aad_i = b"NXPKG1" || SHA-256(cabeçalho) || i (8 bytes) || final (1 byte):
  alterar o cabeçalho, trocar a ordem, remover ou truncar blocos invalida a tag
  GCM. Bytes depois do bloco final são recusados.

Como K é protegida (campo `key_wrap` do cabeçalho)
- modo "password": KEK = Argon2id(senha, sal, m, t, p); K embrulhada com
  AES-256-GCM (AAD fixa do modo). Parâmetros têm piso E teto (anti-DoS).
- modo "recipients" (preparado para compartilhamento por identidade): para cada
  destinatário, X25519(chave efêmera, chave pública do destinatário) →
  HKDF-SHA256(sal = pub efêmera || pub destinatário) → KEK; K embrulhada com
  AES-256-GCM. Esquema ECIES padrão.

Dentro do fluxo decifrado há registros: uint16 tamanho do nome, nome UTF-8,
uint64 tamanho, dados. Um nome vazio encerra a lista. Os nomes são validados
por expressão regular (sem barras invertidas, sem "..", sem caminhos), e cada
registro tem limite de tamanho.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from nexus_intel.domain.errors import PackageAuthError, PackageError, PackageIncompatible
from nexus_intel.infrastructure.crypto import identity
from nexus_intel.infrastructure.crypto.keys import (
    KEY_LEN,
    KdfParams,
    SecretKey,
    b64d,
    b64e,
    derive_password_kek,
)

MAGIC = b"NEXUSPKG"
FORMAT = 1
CHUNK = 1024 * 1024
MAX_HEADER = 64 * 1024
TAG = 16
MAX_KDF_MEMORY_KIB = 1024 * 1024  # 1 GiB: um cabeçalho malicioso não trava a máquina
MAX_KDF_ITERATIONS = 10
MAX_KDF_LANES = 16
MAX_RECIPIENTS = 64
MAX_TOTAL_PLAINTEXT = 8 * 1024**3  # soma de tudo que for decifrado
MAX_RECORDS = 200_000

NAME_RE = re.compile(r"^(manifest\.json|signature\.json|tables/[a-z_][a-z0-9_]{0,62}\.json|files/[0-9a-f]{64})$")
# Cada item é lido inteiro na memória: limites mantêm um pacote malicioso longe de esgotar a RAM.
RECORD_LIMITS = {"manifest.json": 8 * 1024**2, "signature.json": 64 * 1024, "tables/": 256 * 1024**2,
                 "files/": 64 * 1024**2}

_WRAP_AAD_PASSWORD = b"nexus-intel/package/v1/password"


def _wrap_aad_recipient(kid: str) -> bytes:
    return b"nexus-intel/package/v1/x25519/" + kid.encode()


def record_limit(name: str) -> int:
    for prefix, limit in RECORD_LIMITS.items():
        if name == prefix or (prefix.endswith("/") and name.startswith(prefix)):
            return limit
    return 0


def check_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise PackageError("O arquivo .nexus contém um nome de arquivo interno inválido. Nada foi importado.")
    return name


# =================================================================== chave
@dataclass
class KeyWrap:
    content_key: SecretKey
    header: dict[str, Any]


def wrap_with_password(password: str, params: KdfParams) -> KeyWrap:
    if not password:
        raise PackageError("Defina uma senha para proteger o arquivo.")
    params.check_floor()
    k = SecretKey(secrets.token_bytes(KEY_LEN))
    salt = os.urandom(16)
    kek = derive_password_kek(password, salt, params)
    try:
        nonce = os.urandom(12)
        ct = AESGCM(kek.bytes()).encrypt(nonce, k.bytes(), _WRAP_AAD_PASSWORD)
    finally:
        kek.wipe()
    return KeyWrap(k, {"mode": "password", "kdf": {"alg": "argon2id", **params.to_json(), "salt": b64e(salt)},
                       "nonce": b64e(nonce), "ct": b64e(ct)})


def _recipient_kek(shared: bytes, epk: bytes, rpk: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LEN, salt=epk + rpk,
                info=b"nexus-intel/package/v1/x25519").derive(shared)


def wrap_for_recipients(recipient_publics: list[bytes]) -> KeyWrap:
    """Modo por identidade: só quem tem a chave privada X25519 de um destinatário abre."""
    if not recipient_publics or len(recipient_publics) > MAX_RECIPIENTS:
        raise PackageError("Escolha de 1 a 64 destinatários.")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    k = SecretKey(secrets.token_bytes(KEY_LEN))
    entries = []
    for rpk in recipient_publics:
        eph = X25519PrivateKey.generate()
        epk = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        kek = _recipient_kek(eph.exchange(identity.x25519_public(rpk)), epk, rpk)
        kid = identity.fingerprint(rpk)
        nonce = os.urandom(12)
        ct = AESGCM(kek).encrypt(nonce, k.bytes(), _wrap_aad_recipient(kid))
        entries.append({"kid": kid, "epk": b64e(epk), "nonce": b64e(nonce), "ct": b64e(ct)})
    return KeyWrap(k, {"mode": "recipients", "recipients": entries})


def _kdf_from_header(kdf: dict[str, Any]) -> KdfParams:
    try:
        if kdf.get("alg") != "argon2id":
            raise ValueError
        params = KdfParams(memory_kib=int(kdf["m"]), iterations=int(kdf["t"]), lanes=int(kdf["p"]))
        params.check_floor()
    except (KeyError, TypeError, ValueError) as exc:
        raise PackageError("Parâmetros de proteção do arquivo .nexus inválidos.") from exc
    if (params.memory_kib > MAX_KDF_MEMORY_KIB or params.iterations > MAX_KDF_ITERATIONS
            or not 1 <= params.lanes <= MAX_KDF_LANES):
        raise PackageError("Parâmetros de proteção do arquivo .nexus fora dos limites aceitos.")
    return params


def unwrap_with_password(header: dict[str, Any], password: str) -> SecretKey:
    wrap = header.get("key_wrap") or {}
    if wrap.get("mode") != "password":
        raise PackageError("Este arquivo .nexus não é protegido por senha.")
    params = _kdf_from_header(wrap.get("kdf") or {})
    try:
        salt, nonce, ct = b64d(wrap["kdf"]["salt"]), b64d(wrap["nonce"]), b64d(wrap["ct"])
    except (KeyError, ValueError, TypeError) as exc:
        raise PackageError() from exc
    kek = derive_password_kek(password, salt, params)
    try:
        raw = AESGCM(kek.bytes()).decrypt(nonce, ct, _WRAP_AAD_PASSWORD)
    except (InvalidTag, ValueError):
        raise PackageAuthError() from None
    finally:
        kek.wipe()
    if len(raw) != KEY_LEN:
        raise PackageError()
    return SecretKey(raw)


def unwrap_with_identity(header: dict[str, Any], x25519_private_raw: bytes) -> SecretKey:
    wrap = header.get("key_wrap") or {}
    if wrap.get("mode") != "recipients":
        raise PackageError("Este arquivo .nexus não foi enviado para identidades.")
    priv = identity.x25519_private(x25519_private_raw)
    from cryptography.hazmat.primitives import serialization

    my_pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kid = identity.fingerprint(my_pub)
    for entry in (wrap.get("recipients") or [])[:MAX_RECIPIENTS]:
        if entry.get("kid") != kid:
            continue
        try:
            epk = b64d(entry["epk"])
            kek = _recipient_kek(priv.exchange(identity.x25519_public(epk)), epk, my_pub)
            raw = AESGCM(kek).decrypt(b64d(entry["nonce"]), b64d(entry["ct"]), _wrap_aad_recipient(kid))
        except (InvalidTag, KeyError, ValueError, TypeError):
            raise PackageAuthError() from None
        return SecretKey(raw)
    raise PackageAuthError("Este arquivo .nexus não foi enviado para o seu perfil.")


# =================================================================== escrita
def _nonce(prefix: bytes, i: int) -> bytes:
    return prefix + struct.pack(">Q", i)


def _aad(header_digest: bytes, i: int, final: bool) -> bytes:
    return b"NXPKG1" + header_digest + struct.pack(">QB", i, 1 if final else 0)


class PackageWriter:
    def __init__(self, out: BinaryIO, wrap: KeyWrap, app_version: str, min_app_version: str) -> None:
        self.out = out
        self._key = wrap.content_key
        self._aes = AESGCM(self._key.bytes())
        self._prefix = os.urandom(4)
        header = {"format": FORMAT, "app_version": app_version, "min_app_version": min_app_version,
                  "cipher": "AES-256-GCM", "chunk_size": CHUNK, "nonce_prefix": b64e(self._prefix),
                  "key_wrap": wrap.header}
        self.header_bytes = json.dumps(header, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._digest = hashlib.sha256(self.header_bytes).digest()
        self._buf = bytearray()
        self._i = 0
        self._closed = False
        out.write(MAGIC + bytes([FORMAT]) + struct.pack(">I", len(self.header_bytes)) + self.header_bytes)

    def _emit(self, chunk: bytes, final: bool) -> None:
        ct = self._aes.encrypt(_nonce(self._prefix, self._i), chunk, _aad(self._digest, self._i, final))
        self.out.write(struct.pack(">I", len(ct)) + ct)
        self._i += 1

    def _pump(self) -> None:
        while len(self._buf) > CHUNK:  # sempre sobra algo para o bloco final
            self._emit(bytes(self._buf[:CHUNK]), False)
            del self._buf[:CHUNK]

    def add(self, name: str, data: bytes) -> str:
        check_name(name)
        if len(data) > record_limit(name):
            raise PackageError(f"Item grande demais para o pacote: {name}")
        raw = name.encode("utf-8")
        self._buf += struct.pack(">H", len(raw)) + raw + struct.pack(">Q", len(data))
        self._pump()
        view = memoryview(data)
        for start in range(0, len(data), CHUNK):
            self._buf += view[start:start + CHUNK]
            self._pump()
        return hashlib.sha256(data).hexdigest()

    def close(self) -> None:
        if self._closed:
            return
        self._buf += struct.pack(">H", 0)  # fim dos registros
        while len(self._buf) > CHUNK:
            self._emit(bytes(self._buf[:CHUNK]), False)
            del self._buf[:CHUNK]
        self._emit(bytes(self._buf), True)
        self._buf.clear()
        self._closed = True
        self._key.wipe()


# =================================================================== leitura
def read_header(inp: BinaryIO) -> tuple[dict[str, Any], bytes]:
    head = inp.read(len(MAGIC) + 1 + 4)
    if len(head) != len(MAGIC) + 5 or head[:len(MAGIC)] != MAGIC:
        raise PackageError("Este arquivo não é um pacote .nexus.")
    if head[len(MAGIC)] != FORMAT:
        raise PackageIncompatible()
    (hlen,) = struct.unpack(">I", head[-4:])
    if not 0 < hlen <= MAX_HEADER:
        raise PackageError()
    header_bytes = inp.read(hlen)
    if len(header_bytes) != hlen:
        raise PackageError()
    try:
        header = json.loads(header_bytes.decode("utf-8"))
        if not isinstance(header, dict) or header.get("format") != FORMAT:
            raise ValueError
        if header.get("cipher") != "AES-256-GCM" or header.get("chunk_size") != CHUNK:
            raise ValueError
        if len(b64d(header["nonce_prefix"])) != 4 or not isinstance(header.get("key_wrap"), dict):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise PackageError() from exc
    return header, header_bytes


class _PlainStream:
    """Decifra bloco a bloco; só entrega bytes cuja tag GCM já foi verificada."""

    def __init__(self, inp: BinaryIO, header: dict[str, Any], header_bytes: bytes, key: SecretKey) -> None:
        self.inp = inp
        self._aes = AESGCM(key.bytes())
        key.wipe()
        self._prefix = b64d(header["nonce_prefix"])
        self._digest = hashlib.sha256(header_bytes).digest()
        self._i = 0
        self._buf = bytearray()
        self.finished = False
        self.total = 0

    def _next_chunk(self) -> None:
        if self.finished:
            raise PackageError("O arquivo .nexus termina antes do esperado.")
        lenb = self.inp.read(4)
        if len(lenb) != 4:
            raise PackageAuthError("O arquivo .nexus está incompleto ou foi alterado. Nada foi importado.")
        (clen,) = struct.unpack(">I", lenb)
        if not TAG <= clen <= CHUNK + TAG:
            raise PackageAuthError()
        ct = self.inp.read(clen)
        if len(ct) != clen:
            raise PackageAuthError("O arquivo .nexus está incompleto ou foi alterado. Nada foi importado.")
        nonce = _nonce(self._prefix, self._i)
        for final in (False, True):
            try:
                pt = self._aes.decrypt(nonce, ct, _aad(self._digest, self._i, final))
            except InvalidTag:
                continue
            self._i += 1
            self.total += len(pt)
            if self.total > MAX_TOTAL_PLAINTEXT:
                raise PackageError("O conteúdo do arquivo .nexus passa do tamanho máximo aceito.")
            self._buf += pt
            if final:
                self.finished = True
                if self.inp.read(1):
                    raise PackageAuthError("Há dados extras depois do fim do arquivo .nexus. Nada foi importado.")
            return
        raise PackageAuthError()

    def read(self, n: int) -> bytes:
        while len(self._buf) < n:
            self._next_chunk()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def at_end(self) -> bool:
        while not self.finished and not self._buf:
            self._next_chunk()
        while not self.finished:  # consome blocos restantes (devem estar vazios)
            self._next_chunk()
        return not self._buf


def iter_records(inp: BinaryIO, header: dict[str, Any], header_bytes: bytes,
                 key: SecretKey) -> Iterator[tuple[str, bytes]]:
    """Registros (nome, dados) na ordem gravada. Lança PackageError/PackageAuthError."""
    stream = _PlainStream(inp, header, header_bytes, key)
    seen: set[str] = set()
    count = 0
    while True:
        (nlen,) = struct.unpack(">H", stream.read(2))
        if nlen == 0:
            break
        try:
            name = stream.read(nlen).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PackageError() from exc
        check_name(name)
        if name in seen:
            raise PackageError("O arquivo .nexus contém itens repetidos. Nada foi importado.")
        seen.add(name)
        count += 1
        if count > MAX_RECORDS:
            raise PackageError("O arquivo .nexus contém itens demais.")
        (dlen,) = struct.unpack(">Q", stream.read(8))
        if dlen > record_limit(name):
            raise PackageError(f"Item grande demais no arquivo .nexus: {name}")
        yield name, stream.read(dlen)
    if not stream.at_end():
        raise PackageError("Há dados inesperados depois do último item do arquivo .nexus.")
