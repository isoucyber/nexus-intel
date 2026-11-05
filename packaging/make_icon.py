"""Gera o ícone (.ico) sem dependências: fundo azul-ardósia com três nós ligados.

Uso: python packaging/make_icon.py saida.ico
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

BG = (11, 18, 32)
ACCENT = (45, 212, 191)
NODES = [(0.30, 0.34, 0.11), (0.70, 0.30, 0.085), (0.52, 0.72, 0.10)]
EDGES = [(0, 1), (1, 2), (2, 0)]


def _seg_dist(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int) -> bytes:
    rows = []
    radius = 0.2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = (x + 0.5) / size, (y + 0.5) / size
            # Quadrado arredondado
            qx, qy = max(abs(u - 0.5) - (0.5 - radius), 0), max(abs(v - 0.5) - (0.5 - radius), 0)
            inside = math.hypot(qx, qy) <= radius
            if not inside:
                row += bytes((0, 0, 0, 0))
                continue
            color = BG
            line = min(_seg_dist(u, v, NODES[a][:2], NODES[b][:2]) for a, b in EDGES)
            if line < 0.022:
                color = tuple(int(c * 0.75) for c in ACCENT)  # type: ignore[assignment]
            for nx, ny, r in NODES:
                d = math.hypot(u - nx, v - ny)
                if d <= r:
                    color = ACCENT if d <= r - 0.02 else (230, 255, 250)
            row += bytes((*color, 255))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def make_ico(path: str) -> None:
    sizes = [16, 32, 48, 256]
    images = [render(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, img in zip(sizes, images, strict=True):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(images))


if __name__ == "__main__":
    make_ico(sys.argv[1] if len(sys.argv) > 1 else "nexus.ico")
