"""Garantias do design system que não dependem de Qt."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nexus_intel.ui.design.color import auto_color, contrast, ensure_contrast
from nexus_intel.ui.design.tokens import (
    ACCENT_PRESETS,
    THEMES,
    TYPE_BASE,
    Appearance,
    resolve,
)

UI = Path(__file__).resolve().parents[2] / "src" / "nexus_intel" / "ui"


@pytest.mark.parametrize("theme", list(THEMES))
def test_text_contrast_aa(theme):
    t = resolve(Appearance(theme=theme))
    for bg in (t.bg, t.surface, t.surface_elevated, t.surface_sunken):
        for fg in (t.text_primary, t.text_secondary, t.text_muted, t.accent_text,
                   t.success, t.warning, t.danger, t.info):
            assert contrast(fg, bg) >= 4.5, (theme, fg, bg)
    assert contrast(t.accent_fg, t.accent) >= 4.5
    assert contrast(t.selection_text, t.selection) >= 4.5
    assert contrast(t.danger_fg, ensure_contrast(t.danger, t.bg, 3.0)) >= 4.5


@pytest.mark.parametrize("theme", list(THEMES))
def test_status_type_and_focus(theme):
    t = resolve(Appearance(theme=theme))
    for c in list(t.status.values()) + list(t.types.values()):
        assert contrast(c, t.surface) >= 4.5, (theme, c)
    assert contrast(t.focus, t.bg) >= 3.0
    assert contrast(t.input_border, t.surface_sunken) >= 3.0
    assert set(TYPE_BASE) <= set(t.types)


@pytest.mark.parametrize("accent", [*ACCENT_PRESETS.values(), "#ffffff", "#000000", "#777777", "#ffff00",
                                    "#0000ff", "#123456"])
@pytest.mark.parametrize("theme", ["escuro", "claro", "alto_contraste"])
def test_any_accent_stays_accessible(theme, accent):
    t = resolve(Appearance(theme=theme, accent=accent))
    assert contrast(t.accent_fg, t.accent) >= 4.5
    assert contrast(t.accent_text, t.surface) >= 4.5
    assert contrast(t.accent, t.bg) >= 3.0
    assert contrast(t.focus, t.bg) >= 3.0


def test_auto_color_for_new_types_is_stable_and_accessible():
    for bg in ("#10172a", "#ffffff", "#000000"):
        a = auto_color("arma_branca", bg)
        assert a == auto_color("arma_branca", bg)
        assert contrast(a, bg) >= 4.5


def test_appearance_roundtrip_and_legacy_keys():
    a = Appearance.from_dict({"theme": "clean", "font_scale": 3, "accent": "nao-e-cor", "density": "x"})
    assert a.theme == "claro" and a.scale == 1.25 and a.accent is None and a.density == "confortavel"
    assert Appearance.from_dict(a.to_dict()) == a


def test_motion_and_density():
    t = resolve(Appearance(motion="desligadas", density="compacta", rounded=False))
    assert t.duration("base") == 0 and not t.animate
    assert t.space("lg") < 16 and t.radius("lg") == 2


_HEX = re.compile(r"""["']#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?["']""")
_RGB = re.compile(r"""\brgba?\(\s*\d""")
_QT_NAMED = re.compile(r"Qt\.GlobalColor\.(?!transparent)\w+|QColor\(\s*['\"][a-z]+['\"]\s*\)")
_ALLOWED = {"design/tokens.py", "design/color.py"}


def test_no_hardcoded_colors_outside_tokens():
    offenders = []
    for path in UI.rglob("*.py"):
        rel = path.relative_to(UI).as_posix()
        if rel in _ALLOWED:
            continue
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            code = line.split("#", 1)[0] if not _HEX.search(line) else line
            if _HEX.search(code) or _RGB.search(code) or _QT_NAMED.search(code):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, "Cores fixas fora dos tokens:\n" + "\n".join(offenders)
