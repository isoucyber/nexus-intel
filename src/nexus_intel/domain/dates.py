"""Datas com precisão (seção 8.4): "março de 1998" = 1998-03-01 a 1998-03-31.

Formatos aceitos na entrada (pt-BR e ISO):
  2024 · 1990s / década de 1990 · 03/1998 · 1998-03 · 15/03/1998 · 1998-03-15
  prefixo "c." / "aprox." / "~" marca a data como aproximada.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

PRECISIONS = ("day", "month", "year", "decade", "approximate")

_MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


@dataclass(frozen=True)
class FuzzyDate:
    start: date
    end: date
    precision: str

    def __post_init__(self) -> None:
        if self.precision not in PRECISIONS:
            raise ValueError(f"precisão desconhecida: {self.precision}")
        if self.end < self.start:
            raise ValueError("fim antes do início")

    @property
    def sort_key(self) -> str:
        return self.start.isoformat()

    def overlaps(self, other: FuzzyDate) -> bool:
        return self.start <= other.end and other.start <= self.end

    def display(self) -> str:
        s = self.start
        match self.precision:
            case "day":
                return s.strftime("%d/%m/%Y")
            case "month":
                return f"{_MONTHS_PT[s.month - 1]}/{s.year}"
            case "year":
                return str(s.year)
            case "decade":
                return f"década de {s.year}"
            case _:
                return f"c. {s.year}"


def _month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def parse_fuzzy_date(text: str) -> FuzzyDate:
    raw = text.strip().lower()
    if not raw:
        raise ValueError("data vazia")
    approx = False
    for prefix in ("c.", "ca.", "aprox.", "aprox", "~", "cerca de"):
        if raw.startswith(prefix):
            approx, raw = True, raw[len(prefix) :].strip()
            break

    if m := re.fullmatch(r"d[ée]cada de (\d{3})0|(\d{3})0s", raw):
        y = int(m.group(1) or m.group(2)) * 10
        return FuzzyDate(date(y, 1, 1), date(y + 9, 12, 31), "decade")
    if m := re.fullmatch(r"(\d{4})", raw):
        y = int(m.group(1))
        if approx:
            return FuzzyDate(date(max(1, y - 2), 1, 1), date(y + 2, 12, 31), "approximate")
        return FuzzyDate(date(y, 1, 1), date(y, 12, 31), "year")
    if m := re.fullmatch(r"(\d{1,2})[/.-](\d{4})", raw) or re.fullmatch(r"(\d{4})-(\d{1,2})", raw):
        a, b = int(m.group(1)), int(m.group(2))
        y, mo = (b, a) if a <= 12 and b > 31 else (a, b)
        return FuzzyDate(*_month_range(y, mo), "month")
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw):
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return FuzzyDate(d, d, "day")
    if m := re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", raw):
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return FuzzyDate(d, d, "day")
    raise ValueError(f"Data não reconhecida: {text!r}. Use 1998, 03/1998 ou 15/03/1998.")


def from_storage(start: str | None, end: str | None, precision: str | None) -> FuzzyDate | None:
    if not start:
        return None
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return FuzzyDate(s, e, precision or "day")
