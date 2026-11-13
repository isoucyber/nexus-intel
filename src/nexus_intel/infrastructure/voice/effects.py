"""Timbre de "assistente digital" para a voz sintetizada (NumPy, sem dependências).

Não imita a voz de ninguém: aplica um tratamento genérico sobre a voz neural escolhida.
1. Voz mais grave sem ficar lenta: a síntese é feita um pouco mais rápida (`length_scale`
   menor) e depois esticada por reamostragem; a duração volta ao normal e a altura cai.
2. Brilho metálico discreto: dois ecos muito curtos (filtro pente estático).
3. Sala pequena: poucas reflexões curtas, decrescentes.
4. Presença: realce leve dos agudos (pré-ênfase misturada).
"""

from __future__ import annotations

import numpy as np


def to_float(pcm: np.ndarray) -> np.ndarray:
    return pcm.astype(np.float32) / 32768.0 if pcm.dtype == np.int16 else pcm.astype(np.float32)


def to_int16(x: np.ndarray) -> np.ndarray:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)


def stretch(x: np.ndarray, factor: float) -> np.ndarray:
    """Estica o áudio por `factor` (>1 = mais longo e mais grave) com interpolação linear."""
    if x.size == 0 or abs(factor - 1.0) < 1e-3:
        return x
    n = int(round(x.size * factor))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def _delayed(x: np.ndarray, samples: int) -> np.ndarray:
    out = np.zeros_like(x)
    if 0 < samples < x.size:
        out[samples:] = x[:-samples]
    return out


def assistant_timbre(pcm: np.ndarray, sample_rate: int, *, deepen: float = 0.94, amount: float = 1.0) -> np.ndarray:
    """Aplica o timbre e devolve int16. `deepen` < 1 deixa a voz mais grave (0.94 ≈ 1 semitom).

    Para manter a duração, sintetize com `length_scale * deepen` antes de chamar esta função."""
    x = to_float(pcm)
    if x.size == 0:
        return to_int16(x)
    x = stretch(x, 1.0 / deepen)
    a = float(np.clip(amount, 0.0, 1.5))
    sr = sample_rate
    y = x + a * (0.28 * _delayed(x, int(0.0045 * sr)) + 0.16 * _delayed(x, int(0.0105 * sr)))
    for ms, gain in ((23, 0.11), (37, 0.07), (53, 0.045), (71, 0.03)):
        y = y + a * gain * _delayed(x, int(ms / 1000 * sr))
    y = y + a * 0.18 * np.concatenate([[0.0], np.diff(y)]).astype(np.float32)
    peak = float(np.max(np.abs(y))) or 1.0
    return to_int16(y * (0.89 / peak))


def estimate_pitch(pcm: np.ndarray, sample_rate: int) -> float:
    """Frequência fundamental mediana (Hz), por autocorrelação. Usada nos testes e no diagnóstico."""
    x = to_float(pcm)
    n, hop = int(0.04 * sample_rate), int(0.01 * sample_rate)
    lo, hi = int(sample_rate / 400), int(sample_rate / 60)
    f0 = []
    for i in range(0, max(0, x.size - n), hop):
        fr = x[i:i + n] - x[i:i + n].mean()
        if float(np.sqrt((fr ** 2).mean())) < 0.015:
            continue
        ac = np.correlate(fr, fr, "full")[n - 1:]
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.4 * ac[0]:
            f0.append(sample_rate / k)
    return float(np.median(f0)) if f0 else 0.0
