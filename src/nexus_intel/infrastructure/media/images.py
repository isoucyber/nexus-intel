"""Validação e miniaturas de imagens (Pillow).

O formato é decidido pelo CONTEÚDO: a assinatura inicial do arquivo (magic
bytes) tem de bater com o que o decodificador do Pillow reconhece, e a imagem
precisa decodificar de verdade. A extensão do nome do arquivo é ignorada.

Proteções: limite de tamanho do arquivo, limite de pixels (contra "bombas de
descompressão") e decodificação completa antes de aceitar.

Para acrescentar um formato: inclua a assinatura em `_SIGNATURES` e o nome do
Pillow em `FORMATS`.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from nexus_intel.domain.errors import AttachmentTooLarge, InvalidImage

MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 80_000_000  # ~ 10 000 x 8 000

# nome do Pillow -> (mime, rótulo)
FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "JPG"),
    "PNG": ("image/png", "PNG"),
    "WEBP": ("image/webp", "WEBP"),
    "GIF": ("image/gif", "GIF"),
    "BMP": ("image/bmp", "BMP"),
    "TIFF": ("image/tiff", "TIFF"),
}

# Formatos que o Qt abre sem plugins extras; os demais são convertidos para PNG na exibição.
QT_NATIVE = {"image/jpeg", "image/png", "image/gif", "image/bmp"}


def sniff(data: bytes) -> str | None:
    """Formato pela assinatura do arquivo, ou None."""
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:2] == b"BM":
        return "BMP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    return None


@dataclass(frozen=True)
class ImageInfo:
    mime: str
    label: str
    width: int
    height: int
    has_exif: bool
    has_gps: bool


def _open(data: bytes):  # type: ignore[no-untyped-def]
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            return Image.open(io.BytesIO(data))
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise InvalidImage("A imagem tem dimensões grandes demais para ser aberta com segurança.") from exc


def inspect_image(data: bytes) -> ImageInfo:
    """Valida a imagem inteira. Lança InvalidImage / AttachmentTooLarge."""
    if len(data) > MAX_IMAGE_BYTES:
        raise AttachmentTooLarge()
    fmt = sniff(data)
    if fmt is None:
        raise InvalidImage()
    try:
        im = _open(data)
        if im.format != fmt:
            raise InvalidImage("O conteúdo do arquivo não corresponde a um formato de imagem aceito.")
        width, height = im.size
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise InvalidImage("A imagem tem dimensões grandes demais para ser aberta com segurança.")
        exif = im.getexif()
        has_exif = bool(exif)
        has_gps = bool(exif.get_ifd(0x8825)) if has_exif else False
        im.load()  # decodifica de verdade: arquivo truncado/corrompido falha aqui
    except InvalidImage:
        raise
    except Exception as exc:  # noqa: BLE001 - qualquer falha do decodificador = imagem inválida
        raise InvalidImage() from exc
    mime, label = FORMATS[fmt]
    return ImageInfo(mime, label, width, height, has_exif, has_gps)


def render_png(data: bytes, max_side: int | None = None) -> bytes:
    """PNG (1º quadro, orientação EXIF aplicada), opcionalmente reduzido. Só em memória."""
    from PIL import ImageOps

    try:
        im = _open(data)
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA")
        if max_side:
            im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()
    except InvalidImage:
        raise
    except Exception as exc:  # noqa: BLE001
        raise InvalidImage() from exc


def display_bytes(data: bytes, mime: str, max_side: int = 4096) -> bytes:
    """Bytes que o Qt sabe exibir: o original quando nativo e com orientação normal, senão PNG."""
    if mime in QT_NATIVE and mime != "image/jpeg":
        return data
    return render_png(data, max_side)
