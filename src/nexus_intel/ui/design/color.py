"""Utilidades de cor sem Qt: contraste WCAG, mistura, ajuste de luminosidade.

Tudo trabalha com strings "#rrggbb" para que os tokens possam ser testados sem
interface gráfica.
"""

from __future__ import annotations

import colorsys
import hashlib


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"cor inválida: {color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in (r, g, b)))


def is_hex(color: str) -> bool:
    try:
        hex_to_rgb(color)
    except (ValueError, AttributeError):
        return False
    return True


def luminance(color: str) -> float:
    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """Interpola de `a` (t=0) até `b` (t=1)."""
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def rgba(color: str, alpha: float) -> str:
    """Formato aceito pelo QSS: rgba(r, g, b, a)."""
    r, g, b = hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {max(0, min(255, round(alpha * 255)))})"


def _hls(color: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(color)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def _from_hls(h: float, l: float, s: float) -> str:  # noqa: E741
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return rgb_to_hex(r * 255, g * 255, b * 255)


def shift_lightness(color: str, delta: float) -> str:
    h, l, s = _hls(color)  # noqa: E741
    return _from_hls(h, l + delta, s)


def ensure_contrast(fg: str, bg: str, ratio: float) -> str:
    """Clareia ou escurece `fg` (mantendo matiz) até atingir `ratio` sobre `bg`."""
    if contrast(fg, bg) >= ratio:
        return fg
    lighter_bg = luminance(bg) < 0.5
    h, l, s = _hls(fg)  # noqa: E741
    step = 0.02 if lighter_bg else -0.02
    candidate = fg
    for _ in range(60):
        l += step  # noqa: E741
        candidate = _from_hls(h, l, s)
        if contrast(candidate, bg) >= ratio:
            return candidate
        if l <= 0 or l >= 1:
            break
    # Último recurso: branco ou preto, o que contrastar mais.
    return "#ffffff" if contrast("#ffffff", bg) >= contrast("#000000", bg) else "#000000"


def best_on(bg: str) -> str:
    """Texto sobre um fundo colorido: o tom quase-branco ou quase-preto de maior contraste."""
    light, dark = "#ffffff", "#0b0f19"
    return light if contrast(light, bg) >= contrast(dark, bg) else dark


def auto_color(key: str, bg: str, ratio: float = 4.5) -> str:
    """Cor estável e acessível para um tipo novo, derivada do nome (ângulo áureo)."""
    digest = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    hue = (digest * 0.618033988749895) % 1.0
    dark_bg = luminance(bg) < 0.5
    base = _from_hls(hue, 0.66 if dark_bg else 0.38, 0.62)
    return ensure_contrast(base, bg, ratio)
