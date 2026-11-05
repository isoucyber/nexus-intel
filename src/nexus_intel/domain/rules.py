"""Regras puras: conflitos entre afirmações (9.2) e pontuação de duplicatas (9.4)."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

try:  # rapidfuzz é opcional; difflib é o substituto
    from rapidfuzz.fuzz import token_sort_ratio as _tsr
except ImportError:  # pragma: no cover
    _tsr = None

ACTIVE_CLAIM = {"verified", "reported", "unverified", "hypothesis", "conflicting"}


def token_sort_ratio(a: str, b: str) -> float:
    if _tsr is not None:
        return float(_tsr(a, b))
    sa, sb = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return 100.0 * SequenceMatcher(None, sa, sb).ratio()


def claim_value_key(c: dict[str, Any]) -> tuple[Any, ...]:
    return (
        (c.get("value_text") or "").strip().casefold(),
        c.get("value_num"),
        c.get("value_date_start"),
        c.get("value_date_end"),
        c.get("value_bool"),
        c.get("value_entity_id"),
    )


def _periods_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a0, a1 = a.get("valid_from") or "0000", a.get("valid_to") or "9999"
    b0, b1 = b.get("valid_from") or "0000", b.get("valid_to") or "9999"
    return a0 <= b1 and b0 <= a1


def find_conflicts(claims: list[dict[str, Any]], rule: str) -> set[str]:
    """IDs das afirmações em conflito, para afirmações de um mesmo campo e sujeito."""
    if rule == "multi":
        return set()
    active = [c for c in claims if c["epistemic_status"] in ACTIVE_CLAIM]
    out: set[str] = set()
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if claim_value_key(a) == claim_value_key(b):
                continue
            if rule == "single" or (rule == "single_per_period" and _periods_overlap(a, b)):
                out.update((a["id"], b["id"]))
    return out


@dataclass
class DuplicateCandidate:
    entity_id: str
    display_name: str
    score: int
    reasons: list[str]


def score_duplicate(
    name_norm: str,
    other_norm: str,
    *,
    same_identifier: bool = False,
    alias_match: bool = False,
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if same_identifier:
        return 100, ["mesmo identificador (CPF, CNPJ, domínio…)"]
    score = 0
    if name_norm and name_norm == other_norm:
        score = 90
        reasons.append("nome idêntico (ignorando acentos e maiúsculas)")
    else:
        sim = token_sort_ratio(name_norm, other_norm)
        if sim >= 85:
            score = int(50 + (sim - 85) * 2)
            reasons.append(f"nome semelhante ({sim:.0f}%)")
    if alias_match:
        score = max(score, 75)
        reasons.append("coincide com um nome alternativo")
    return min(score, 99), reasons


DUPLICATE_THRESHOLD = 70
