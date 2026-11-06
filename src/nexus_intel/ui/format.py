"""Formatação de datas e números para exibição (pt-BR).

Todos os textos visíveis de data passam por aqui, para facilitar a tradução futura.
"""

from __future__ import annotations

from datetime import UTC, datetime

_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def absolute(iso: str | None) -> str:
    dt = _parse(iso)
    return dt.astimezone().strftime("%d/%m/%Y %H:%M") if dt else (iso or "")


def relative(iso: str | None, now: datetime | None = None) -> str:
    """“agora”, “há 5 min”, “há 2 h”, “ontem”, “há 3 dias”, ou “12 mar 2025”."""
    dt = _parse(iso)
    if dt is None:
        return iso or ""
    now = now or datetime.now(UTC)
    seconds = (now - dt).total_seconds()
    if seconds < 45:
        return "agora"
    if seconds < 3600:
        return f"há {max(1, round(seconds / 60))} min"
    if seconds < 86400:
        return f"há {round(seconds / 3600)} h"
    local, today = dt.astimezone(), now.astimezone()
    days = (today.date() - local.date()).days
    if days == 1:
        return "ontem"
    if days < 7:
        return f"há {days} dias"
    if local.year == today.year:
        return f"{local.day} {_MONTHS[local.month - 1]}"
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"


def number(n: int | float) -> str:
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(n):,}".replace(",", ".")


def percent(part: float, total: float) -> str:
    return f"{round(100 * part / total)}%" if total else "0%"
