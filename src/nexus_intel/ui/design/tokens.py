"""Design tokens do NEXUS INTEL: a ÚNICA fonte de cores, tipografia e medidas.

Nenhum outro módulo da interface escreve cores literais; todos leem `current()`.
Um teste automático (tests/unit/test_design_tokens.py) garante isso.

Fluxo: `Appearance` (preferências do usuário) → `resolve()` → `Tokens` (valores
finais, já com variações de hover/active/subtle e contraste WCAG AA garantido).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from nexus_intel.ui.design.color import (
    auto_color,
    best_on,
    contrast,
    ensure_contrast,
    is_hex,
    luminance,
    mix,
    shift_lightness,
)

# --------------------------------------------------------------- temas base
# Cada tema define só o essencial; o restante é derivado em resolve().


@dataclass(frozen=True)
class BaseTheme:
    key: str
    label: str
    bg: str
    surface: str
    surface_elevated: str
    surface_sunken: str
    border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    success: str
    warning: str
    danger: str
    info: str
    high_contrast: bool = False

    @property
    def dark(self) -> bool:
        return luminance(self.bg) < 0.4


THEMES: dict[str, BaseTheme] = {
    t.key: t
    for t in (
        BaseTheme("escuro", "Escuro", bg="#0b1020", surface="#10172a", surface_elevated="#162036",
                  surface_sunken="#0d1426", border="#222d45", text_primary="#e8edf6",
                  text_secondary="#b3bdcf", text_muted="#8794ab", accent="#2dd4bf",
                  success="#34d399", warning="#fbbf24", danger="#f87171", info="#60a5fa"),
        BaseTheme("claro", "Claro", bg="#f4f5f8", surface="#ffffff", surface_elevated="#ffffff",
                  surface_sunken="#f7f8fa", border="#e1e4ea", text_primary="#0f172a",
                  text_secondary="#334155", text_muted="#5a6577", accent="#0f766e",
                  success="#047857", warning="#a15c07", danger="#b91c1c", info="#1d4ed8"),
        BaseTheme("oled", "OLED preto", bg="#000000", surface="#060607", surface_elevated="#101012",
                  surface_sunken="#000000", border="#1e1e22", text_primary="#f4f4f5",
                  text_secondary="#c4c4cc", text_muted="#9a9aa4", accent="#2dd4bf",
                  success="#34d399", warning="#fbbf24", danger="#f87171", info="#60a5fa"),
        BaseTheme("alto_contraste", "Alto contraste", bg="#000000", surface="#000000",
                  surface_elevated="#0d0d0d", surface_sunken="#000000", border="#9a9a9a",
                  text_primary="#ffffff", text_secondary="#f0f0f0", text_muted="#d6d6d6",
                  accent="#ffd60a", success="#5ef08a", warning="#ffd60a", danger="#ff7b7b",
                  info="#8cc8ff", high_contrast=True),
        BaseTheme("midnight_blue", "Midnight Blue", bg="#0a1022", surface="#0f1830",
                  surface_elevated="#15213f", surface_sunken="#0c142b", border="#22325c",
                  text_primary="#e7ecff", text_secondary="#b7c3e8", text_muted="#8a99c6",
                  accent="#8aa4ff", success="#4ade80", warning="#facc15", danger="#fb7185",
                  info="#7dd3fc"),
        BaseTheme("graphite", "Graphite", bg="#151517", surface="#1b1b1e", surface_elevated="#232327",
                  surface_sunken="#18181b", border="#2e2e34", text_primary="#ededf0",
                  text_secondary="#bfbfc8", text_muted="#9696a2", accent="#f5a524",
                  success="#4ade80", warning="#f5a524", danger="#f87171", info="#7cb7ff"),
    )
}
DEFAULT_THEME = "escuro"
LEGACY_THEME_KEYS = {"nexus": "escuro", "clean": "claro", "midnight": "alto_contraste"}

ACCENT_PRESETS = {
    "Turquesa": "#2dd4bf", "Azul": "#60a5fa", "Índigo": "#8aa4ff", "Violeta": "#a78bfa",
    "Rosa": "#f472b6", "Âmbar": "#f5a524", "Verde": "#4ade80", "Vermelho": "#f87171",
}

# Paletas de base para status e tipos; resolve() garante contraste no tema escolhido.
STATUS_BASE = {
    "verified": "#22c55e",
    "reported": "#38bdf8",
    "unverified": "#94a3b8",
    "hypothesis": "#a78bfa",
    "conflicting": "#ef4444",
    "refuted": "#71717a",
}

TYPE_BASE = {
    "person": "#38bdf8", "company": "#a78bfa", "organization": "#c084fc", "website": "#22d3ee",
    "domain": "#06b6d4", "ip": "#0ea5e9", "subject": "#f59e0b", "project": "#eab308",
    "object": "#a3a3a3", "vehicle": "#fb923c", "location": "#34d399", "event": "#fb7185",
    "document": "#a3e635", "account": "#f472b6", "other": "#94a3b8",
}

# --------------------------------------------------------------- medidas
FONT_UI = "Inter"
FONT_MONO = "JetBrains Mono"
FONT_FALLBACK_UI = ("Segoe UI", "Helvetica Neue", "Arial")
FONT_FALLBACK_MONO = ("Cascadia Mono", "Consolas", "Menlo", "monospace")

TYPE_SCALE = {"xs": 12, "sm": 13, "md": 14, "lg": 16, "xl": 20, "xxl": 24, "display": 32}
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 4, "md": 6, "lg": 10, "xl": 14, "full": 999}
# (desfoque, deslocamento vertical, opacidade) para QGraphicsDropShadowEffect
SHADOW = {"sm": (10, 2, 0.22), "md": (24, 8, 0.32), "lg": (48, 16, 0.42)}
DURATION = {"fast": 120, "base": 160, "slow": 200}

DENSITY = {"compacta": 0.8, "confortavel": 1.0, "espacosa": 1.25}
MOTION = ("completas", "reduzidas", "desligadas")


@dataclass(frozen=True)
class Appearance:
    """Preferências visuais do usuário (persistidas). Fase 3 amplia a tela de edição."""

    theme: str = DEFAULT_THEME
    accent: str | None = None
    scale: float = 1.0
    density: str = "confortavel"
    motion: str = "completas"
    rounded: bool = True
    type_colors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Appearance:
        data = dict(data or {})
        theme = LEGACY_THEME_KEYS.get(data.get("theme", ""), data.get("theme", DEFAULT_THEME))
        if theme not in THEMES:
            theme = DEFAULT_THEME
        accent = data.get("accent")
        density = data.get("density", "confortavel")
        motion = data.get("motion", "completas")
        return cls(
            theme=theme,
            accent=accent if isinstance(accent, str) and is_hex(accent) else None,
            scale=max(0.9, min(1.25, float(data.get("scale", data.get("font_scale", 1.0)) or 1.0))),
            density=density if density in DENSITY else "confortavel",
            motion=motion if motion in MOTION else "completas",
            rounded=bool(data.get("rounded", True)),
            type_colors={k: v for k, v in dict(data.get("type_colors") or {}).items() if is_hex(v)},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"theme": self.theme, "accent": self.accent, "scale": self.scale, "density": self.density,
                "motion": self.motion, "rounded": self.rounded, "type_colors": dict(self.type_colors)}


@dataclass(frozen=True)
class Tokens:
    """Valores finais consumidos pela interface."""

    key: str
    label: str
    dark: bool
    high_contrast: bool
    # superfícies
    bg: str
    surface: str
    surface_elevated: str
    surface_hover: str
    surface_active: str
    surface_sunken: str
    overlay: str
    # bordas e foco
    border: str
    border_strong: str
    input_border: str
    focus: str
    # texto
    text_primary: str
    text_secondary: str
    text_muted: str
    text_disabled: str
    # destaque
    accent: str
    accent_hover: str
    accent_active: str
    accent_subtle: str
    accent_fg: str
    accent_text: str
    # semânticas (texto) e fundos sutis correspondentes
    success: str
    warning: str
    danger: str
    info: str
    success_subtle: str
    warning_subtle: str
    danger_subtle: str
    info_subtle: str
    danger_fg: str
    # seleção em listas: fundo sutil + texto normal (sempre legível)
    selection: str
    selection_text: str
    # mapas de status e tipos
    status: dict[str, str]
    types: dict[str, str]
    # grafo
    graph_bg: str
    graph_edge: str
    graph_label: str
    # medidas efetivas
    scale: float
    density: float
    motion: str
    rounded: bool

    # ---- auxiliares
    def font_px(self, step: str) -> int:
        return round(TYPE_SCALE[step] * self.scale)

    def space(self, step: str) -> int:
        return max(2, round(SPACE[step] * self.density))

    def radius(self, step: str) -> int:
        return RADIUS[step] if self.rounded else (2 if step != "full" else 999)

    def duration(self, step: str) -> int:
        if self.motion == "desligadas":
            return 0
        return DURATION[step] // (2 if self.motion == "reduzidas" else 1)

    @property
    def animate(self) -> bool:
        return self.motion == "completas"

    def type_color(self, type_key: str | None) -> str:
        if type_key and type_key in self.types:
            return self.types[type_key]
        return auto_color(type_key or "other", self.surface)

    def status_color(self, status: str) -> str:
        return self.status.get(status, self.text_muted)

    def subtle(self, color: str, amount: float | None = None) -> str:
        """Fundo sutil derivado de uma cor, para chips e avatares."""
        t = amount if amount is not None else (0.18 if self.dark else 0.12)
        return mix(self.surface, color, t)


def _derive_accent(accent: str, surface: str, bg: str, dark: bool) -> dict[str, str]:
    # O botão primário precisa de 3:1 contra o fundo (componente) e texto 4.5:1 sobre ele.
    acc = ensure_contrast(accent, bg, 3.0)
    fg = best_on(acc)
    if contrast(fg, acc) < 4.5:
        acc = ensure_contrast(acc, fg, 4.5)
    direction = 1 if dark else -1
    return {
        "accent": acc,
        "accent_hover": shift_lightness(acc, 0.06 * direction),
        "accent_active": shift_lightness(acc, -0.06 * direction),
        "accent_subtle": mix(surface, acc, 0.20 if dark else 0.12),
        "accent_fg": fg,
        "accent_text": ensure_contrast(acc, surface, 4.5),
        "focus": ensure_contrast(shift_lightness(acc, 0.08 * direction), bg, 3.0),
    }


def resolve(app: Appearance | None = None) -> Tokens:
    app = app or Appearance()
    base = THEMES.get(app.theme, THEMES[DEFAULT_THEME])
    dark = base.dark
    surf = base.surface
    acc = _derive_accent(app.accent or base.accent, surf, base.bg, dark)

    def text_on_surfaces(color: str) -> str:
        # Garante 4.5:1 sobre todas as superfícies em que o texto aparece.
        for bg in (base.bg, base.surface, base.surface_elevated, base.surface_sunken):
            color = ensure_contrast(color, bg, 4.5)
        return color

    hover = mix(base.surface, base.text_primary, 0.06 if dark else 0.04)
    active = mix(base.surface, base.text_primary, 0.10 if dark else 0.07)
    border_strong = mix(base.border, base.text_primary, 0.18 if dark else 0.14)
    status = {k: text_on_surfaces(v) for k, v in STATUS_BASE.items()}
    types = {k: text_on_surfaces(app.type_colors.get(k, v)) for k, v in TYPE_BASE.items()}
    for k, v in app.type_colors.items():
        types.setdefault(k, text_on_surfaces(v))
    semantic = {k: text_on_surfaces(getattr(base, k)) for k in ("success", "warning", "danger", "info")}
    selection = mix(base.surface, acc["accent"], 0.24 if dark else 0.16)
    return Tokens(
        key=base.key, label=base.label, dark=dark, high_contrast=base.high_contrast,
        bg=base.bg, surface=surf, surface_elevated=base.surface_elevated,
        surface_hover=hover, surface_active=active, surface_sunken=base.surface_sunken,
        overlay=base.bg,
        border=base.border, border_strong=border_strong,
        input_border=ensure_contrast(border_strong, base.surface_sunken, 3.0),
        focus=acc["focus"],
        text_primary=text_on_surfaces(base.text_primary),
        text_secondary=text_on_surfaces(base.text_secondary),
        text_muted=text_on_surfaces(base.text_muted),
        text_disabled=mix(base.surface, base.text_muted, 0.6),
        accent=acc["accent"], accent_hover=acc["accent_hover"], accent_active=acc["accent_active"],
        accent_subtle=acc["accent_subtle"], accent_fg=acc["accent_fg"], accent_text=acc["accent_text"],
        **semantic,
        success_subtle=mix(surf, semantic["success"], 0.16),
        warning_subtle=mix(surf, semantic["warning"], 0.16),
        danger_subtle=mix(surf, semantic["danger"], 0.16),
        info_subtle=mix(surf, semantic["info"], 0.16),
        danger_fg=best_on(ensure_contrast(semantic["danger"], base.bg, 3.0)),
        selection=selection,
        selection_text=ensure_contrast(base.text_primary, selection, 4.5),
        status=status, types=types,
        graph_bg=base.bg,
        graph_edge=ensure_contrast(mix(base.bg, base.text_muted, 0.55), base.bg, 2.0),
        graph_label=text_on_surfaces(base.text_secondary),
        scale=app.scale, density=DENSITY.get(app.density, 1.0), motion=app.motion, rounded=app.rounded,
    )


# --------------------------------------------------------------- estado global
_current: Tokens = resolve()
_appearance: Appearance = Appearance()


def current() -> Tokens:
    return _current


def appearance() -> Appearance:
    return _appearance


def set_appearance(app: Appearance) -> Tokens:
    """Só atualiza os valores; quem aplica na tela é o ThemeManager (design.manager)."""
    global _current, _appearance
    _appearance = app
    _current = resolve(app)
    return _current


def preview(app: Appearance, **changes: Any) -> Tokens:
    return resolve(replace(app, **changes))
