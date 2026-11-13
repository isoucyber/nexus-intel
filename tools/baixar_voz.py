"""Instala a voz do assistente NEXUS (uma vez, com internet). Depois, tudo roda offline.

Uso:
    python tools/baixar_voz.py                  # voz humana Kokoro (pm_alex) + reconhecimento de fala (Whisper)
    python tools/baixar_voz.py --piper          # também a voz Piper (cadu/jeff), alternativa mais leve
    python tools/baixar_voz.py --destino PASTA  # outra pasta (padrão: pasta de dados do NEXUS / voz)

Segurança:
- Baixa só de huggingface.co, por HTTPS, numa revisão FIXA (commit) de cada repositório.
- Confere o SHA-256 de cada arquivo antes de colocá-lo no lugar (grava em .part e renomeia).
- Kokoro e Piper (que usam o espeak-ng, GPL-3.0) são instalados em ambientes Python SEPARADOS e
  rodam como programas externos; o NEXUS (Apache-2.0) não os embute.

Licenças: Kokoro-82M (Apache-2.0); vozes Piper pt-BR cadu e jeff (dados CC0); Whisper small (MIT).
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
KOKORO_REV = "1939ad2a8e416c0acfeecc08a694d14ef25f2231"  # onnx-community/Kokoro-82M-v1.0-ONNX
KOKORO_ONNX_VERSION = "0.6.1"
KOKORO = {  # arquivo no repositório: SHA-256
    "onnx/model.onnx": "8fbea51ea711f2af382e88c833d9e288c6dc82ce5e98421ea61c058ce21a34cb",
    "voices/pm_alex.bin": "0175c753f59c54e7fd5a995bedef0c5ff2fb67e0043dd3dcb2ae74ec2acbeb2a",
    "voices/pm_santa.bin": "8b012db3185778afe2e45a62cbad69db73021774fe68dda634bcc748a982eede",
    "voices/pf_dora.bin": "3da7b5b2d91847ebf5646f57631af6ececae3c29a89cd300f06edf9aa6cfe9ee",
}

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


def kokoro_url(path: str) -> str:
    return f"https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/{KOKORO_REV}/{path}"


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


def separate_env(env_dir: Path, package: str) -> Path:
    """Ambiente Python próprio para um programa de voz (fica fora do ambiente do NEXUS)."""
    if not env_dir.exists():
        print(f"  criando ambiente separado {env_dir.name} …")
        venv.EnvBuilder(with_pip=True).create(env_dir)
    py = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    print(f"  instalando {package} (pode levar alguns minutos) …")
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", package], check=True)  # noqa: S603
    return py


def install_piper(dest: Path) -> None:
    print("Voz Piper (alternativa):")
    for name, digest in VOICES.items():
        fetch(voice_url(name), dest / "vozes" / name, digest)
    separate_env(dest / "piper-venv", f"piper-tts=={PIPER_VERSION}")


def install_kokoro(dest: Path) -> None:
    print("Voz humana Kokoro (pm_alex, ~330 MB):")
    folder = dest / "kokoro"
    for path, digest in KOKORO.items():
        fetch(kokoro_url(path), folder / Path(path).name, digest)
    py = separate_env(dest / "kokoro-venv", f"kokoro-onnx=={KOKORO_ONNX_VERSION}")
    # As vozes vêm como vetores brutos; o kokoro-onnx lê um arquivo .npz com todas elas.
    script = ("import numpy as np, sys, pathlib; f = pathlib.Path(sys.argv[1]); "
              "np.savez(f / 'voices-ptbr.npz', **{n: np.fromfile(f / (n + '.bin'), dtype=np.float32)"
              ".reshape(-1, 1, 256) for n in ('pm_alex', 'pm_santa', 'pf_dora')})")
    subprocess.run([str(py), "-c", script, str(folder)], check=True)  # noqa: S603
    print("  Kokoro pronto.")


def main() -> int:
    from nexus_intel.infrastructure.paths import default_paths

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--destino", type=Path, default=default_paths().data / "voz")
    ap.add_argument("--piper", "--instalar-piper", dest="piper", action="store_true",
                    help="também instala a voz Piper (alternativa mais leve)")
    ap.add_argument("--sem-kokoro", action="store_true", help="não instala a voz Kokoro")
    ap.add_argument("--sem-whisper", action="store_true", help="não baixa o modelo de reconhecimento de fala")
    args = ap.parse_args()
    dest: Path = args.destino.resolve()
    print(f"Pasta de voz: {dest}")
    if not args.sem_kokoro:
        install_kokoro(dest)
    if not args.sem_whisper:
        print("Modelo de reconhecimento de fala (Whisper small, ~480 MB):")
        for name, digest in WHISPER.items():
            fetch(whisper_url(name), dest / "modelos" / "whisper-small" / name, digest)
    if args.piper:
        install_piper(dest)
    print("Pronto. No NEXUS: IA e análises → Configurar → Voz.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
