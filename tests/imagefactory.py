"""Imagens reais geradas em memória para os testes (Pillow)."""

from __future__ import annotations

import io


def make_image(fmt: str = "PNG", size: tuple[int, int] = (64, 48), color: tuple[int, int, int] = (200, 30, 30),
               gps: bool = False) -> bytes:
    from PIL import Image

    im = Image.new("RGB", size, color)
    out = io.BytesIO()
    kwargs = {}
    if gps:
        exif = Image.Exif()
        exif[0x010F] = "Camera Teste"
        exif[0x8825] = {1: "S", 2: (12.0, 58.0, 0.0)}
        kwargs["exif"] = exif.tobytes()
    im.save(out, fmt, **kwargs)
    return out.getvalue()
