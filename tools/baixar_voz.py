"""Instala a voz do assistente NEXUS (uma vez, com internet). Depois, tudo roda offline.

Uso:
    python tools/baixar_voz.py                  # vozes pt-BR (cadu e jeff) + modelo de fala (Whisper small)
    python tools/baixar_voz.py --instalar-piper # também cria um ambiente separado com o Piper
    python tools/baixar_voz.py --destino PASTA  # outra pasta (padrão: pasta de dados do NEXUS / voz)

Segurança:
- Baixa só de huggingface.co, por HTTPS, numa revisão FIXA (commit) de cada repositório.
- Confere o SHA-256 de cada arquivo antes de colocá-lo no lugar (grava em .part e renomeia).
- O Piper (GPL-3.0) é instalado num ambiente Python SEPARADO e roda como programa externo;
  o NEXUS (Apache-2.0) não o embute.

Licenças: vozes Piper pt-BR cadu e jeff (dados CC0); Whisper small convertido (MIT).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess  # noqa: S404
import sys
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PIPER_VOICES_REV = "2f358b6a560e3a913ebf509b2f3344f20b367f94"
WHISPER_REV = "536b0662742c02347bc0e980a01041f333bce120"
PIPER_VERSION = "1.8.0"

VOICES = {  # nome do arquivo: SHA-256
    "pt_BR-cadu-medium.onnx": "d5a662e3f606d5a49dd29ba9ce90c304ae45dd9543f8b0c773bcb0de282499de",
    "pt_BR-cadu-medium.onnx.json": "9fa837b7c1237ea5978bcd7be38c130798e8faa064f754873bb4ce5fc498bd88",
    "pt_BR-jeff-medium.onnx": "82ddcdb01a0342f078bd89ce2815eda27185818d15e15f06fb9a72ac3bce94e1",
    "pt_BR-jeff-medium.onnx.json": "078ea4e42a680ca3cb662a8929237c32e2c0d581f5363f2f55f09bc266497bf6",
}
WHISPER = {
    "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
}


def voice_url(name: str) -> str:
    who = name.split("-")[1]
    return (f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_VOICES_REV}"
            f"/pt/pt_BR/{who}/medium/{name}")


def whisper_url(name: str) -> str:
    return f"https://huggingface.co/Systran/faster-whisper-small/resolve/{WHISPER_REV}/{name}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, expected: str) -> None:
    if dest.is_file() and sha256(dest) == expected:
        print(f"  já instalado: {dest.name}")
        return
    if not url.startswith("https://huggingface.co/"):
        raise SystemExit(f"origem não permitida: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"  baixando {dest.name} …", flush=True)
    with urllib.request.urlopen(url, timeout=60) as resp, part.open("wb") as out:  # noqa: S310 - HTTPS fixo
        while block := resp.read(1 << 20):
            out.write(block)
    got = sha256(part)
    if got != expected:
        part.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 não confere para {dest.name}: {got} (esperado {expected}). Nada foi instalado.")
    os.replace(part, dest)


def install_piper(dest: Path) -> Path:
    env_dir = dest / "piper-venv"
    if not env_dir.exists():
        print("  criando ambiente separado para o Piper …")
        venv.EnvBuilder(with_pip=True).create(env_dir)
    py = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", f"piper-tts=={PIPER_VERSION}"], check=True)  # noqa: S603
    exe = env_dir / ("Scripts/piper.exe" if os.name == "nt" else "bin/piper")
    print(f"  Piper instalado: {exe}")
    return exe


def main() -> int:
    from nexus_intel.infrastructure.paths import default_paths

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, default=default_paths().data / "voz")
    ap.add_argument("--instalar-piper", action="store_true")
    ap.add_argument("--sem-whisper", action="store_true", help="não baixa o modelo de reconhecimento de fala")
    args = ap.parse_args()
    dest: Path = args.destino.resolve()
    print(f"Pasta de voz: {dest}")
    print("Vozes pt-BR (Piper):")
    for name, digest in VOICES.items():
        fetch(voice_url(name), dest / "vozes" / name, digest)
    if not args.sem_whisper:
        print("Modelo de reconhecimento de fala (Whisper small, ~480 MB):")
        for name, digest in WHISPER.items():
            fetch(whisper_url(name), dest / "modelos" / "whisper-small" / name, digest)
    if args.instalar_piper:
        install_piper(dest)
    print("Pronto. No NEXUS: IA e análises → Configurar → Voz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
