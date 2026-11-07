"""Abertura de links externos no navegador padrão do sistema.

Regras de segurança:
- só abre após uma ação do usuário (clique ou botão), nunca automaticamente;
- aceita apenas http e https, com endereço válido (sem espaços nem caracteres de controle);
- um endereço sem esquema que pareça um domínio (“exemplo.com/x”) é tratado como https;
- usa QDesktopServices.openUrl(QUrl), que entrega ao navegador padrão do Windows.
O resto do aplicativo continua offline: só o link clicado sai do computador.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget

ALLOWED_SCHEMES = ("http", "https")
_DOMAIN_LIKE = re.compile(r"^[\w.-]+\.[a-z]{2,}(?::\d+)?(?:[/?#].*)?$", re.IGNORECASE | re.UNICODE)


def safe_http_url(text: str | None) -> str | None:
    """Devolve a URL normalizada se for http/https válida; senão, None."""
    raw = (text or "").strip()
    if not raw or any(ch.isspace() or ord(ch) < 32 for ch in raw):
        return None
    if "://" not in raw:
        if not _DOMAIN_LIKE.match(raw):
            return None
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        return None
    return raw


def open_external_link(url: str | None, parent: QWidget | None = None) -> bool:
    """Abre o link no navegador padrão. Mostra um aviso amigável se for inválido."""
    from nexus_intel.ui.design.components import notify

    safe = safe_http_url(url)
    qurl = QUrl(safe or "", QUrl.ParsingMode.StrictMode)
    if safe is None or not qurl.isValid() or qurl.scheme().lower() not in ALLOWED_SCHEMES:
        notify(parent, f"Link inválido: “{(url or '').strip()[:80]}”. Só endereços http:// ou https:// "
                       "podem ser abertos.", "warning")
        return False
    if not QDesktopServices.openUrl(qurl):
        notify(parent, "Não foi possível abrir o navegador padrão. Copie o link e abra manualmente.", "danger")
        return False
    return True


def link_html(url: str | None, label: str | None = None) -> str:
    """Trecho HTML seguro para QLabel com linkActivated (texto e endereço escapados)."""
    safe = safe_http_url(url)
    text = html.escape(label or (url or ""))
    if safe is None:
        return text
    return f'<a href="{html.escape(safe, quote=True)}">{text}</a>'
