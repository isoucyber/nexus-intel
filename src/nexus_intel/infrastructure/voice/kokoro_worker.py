"""Processo de voz Kokoro (roda no ambiente Python SEPARADO criado por tools/baixar_voz.py).

Não importa nada do NEXUS: é executado pelo Python do ambiente do Kokoro, que tem o
`kokoro-onnx` (e o espeak-ng, GPL) instalados à parte. O NEXUS só conversa com ele por
entrada e saída padrão, como com qualquer programa externo.

Protocolo (uma linha JSON por pedido, na entrada padrão):
    {"text": "...", "voice": "pm_alex", "speed": 1.0}
Resposta na saída padrão, para cada pedido:
    4 bytes (little-endian) com o tamanho N, depois N bytes de PCM int16 mono a 24 kHz.
O modelo é carregado uma vez; cada frase sai em uma fração de segundo.

Uso: python kokoro_worker.py MODELO.onnx VOZES.npz
"""

import json
import struct
import sys


def main() -> int:
    import numpy as np
    from kokoro_onnx import Kokoro

    model, voices = sys.argv[1], sys.argv[2]
    tts = Kokoro(model, voices)
    out = sys.stdout.buffer
    out.write(struct.pack("<I", 0))  # sinal de pronto
    out.flush()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            text = str(req.get("text", ""))[:2000]
            samples, _rate = tts.create(text, voice=str(req.get("voice", "pm_alex")),
                                        speed=float(req.get("speed", 1.0)), lang="pt-br") if text.strip() else ([], 24000)
            pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()
        except Exception:  # noqa: BLE001 - uma frase com problema não derruba o processo
            pcm = b""
        out.write(struct.pack("<I", len(pcm)))
        out.write(pcm)
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
