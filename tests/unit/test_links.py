"""Validação de links externos (só http/https, nada de esquemas perigosos)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from nexus_intel.ui.links import link_html, safe_http_url  # noqa: E402


@pytest.mark.parametrize(("raw", "expected"), [
    ("https://exemplo.com/a?b=1", "https://exemplo.com/a?b=1"),
    ("http://exemplo.com", "http://exemplo.com"),
    ("  https://exemplo.com  ", "https://exemplo.com"),
    ("exemplo.com.br/noticia", "https://exemplo.com.br/noticia"),
    ("www.exemplo.com", "https://www.exemplo.com"),
])
def test_valid_links(raw, expected):
    assert safe_http_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "", None, "   ", "javascript:alert(1)", "file:///C:/Windows/system32", "ftp://exemplo.com",
    "https://", "não é link", "https://exem plo.com", "data:text/html,oi", "C:\\pasta\\arquivo.exe",
    "mailto:a@b.com", "https://exemplo.com/\nlinha",
])
def test_invalid_links(raw):
    assert safe_http_url(raw) is None


def test_link_html_escapes():
    assert link_html('https://x.com/"><script>', "<b>") == (
        '<a href="https://x.com/&quot;&gt;&lt;script&gt;">&lt;b&gt;</a>')
    assert link_html("javascript:alert(1)") == "javascript:alert(1)"
