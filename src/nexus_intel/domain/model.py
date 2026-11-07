"""Vocabulário do domínio: status epistêmico, normalização, identificadores."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

from nexus_intel.domain.errors import NexusError


class Epistemic(StrEnum):
    VERIFIED = "verified"
    REPORTED = "reported"
    UNVERIFIED = "unverified"
    HYPOTHESIS = "hypothesis"
    CONFLICTING = "conflicting"
    REFUTED = "refuted"

    @property
    def label(self) -> str:
        return EPISTEMIC_LABELS[self]


EPISTEMIC_LABELS = {
    Epistemic.VERIFIED: "Verificado",
    Epistemic.REPORTED: "Relatado",
    Epistemic.UNVERIFIED: "Não verificado",
    Epistemic.HYPOTHESIS: "Hipótese",
    Epistemic.CONFLICTING: "Conflitante",
    Epistemic.REFUTED: "Refutado",
}

RELIABILITY_LABELS = {
    "A": "A — Totalmente confiável",
    "B": "B — Normalmente confiável",
    "C": "C — Razoavelmente confiável",
    "D": "D — Normalmente não confiável",
    "E": "E — Não confiável",
    "F": "F — Confiabilidade não avaliável",
}

CREDIBILITY_LABELS = {
    1: "1 — Confirmada por outras fontes",
    2: "2 — Provavelmente verdadeira",
    3: "3 — Possivelmente verdadeira",
    4: "4 — Duvidosa",
    5: "5 — Improvável",
    6: "6 — Veracidade não avaliável",
}

SOURCE_KINDS = {
    "official": "Documento oficial",
    "news": "Notícia",
    "website": "Site",
    "social_public": "Rede social (pública)",
    "interview": "Entrevista",
    "received": "Documento recebido",
    "own": "Observação própria",
    "other": "Outro",
}

_TITLES = {"dr", "dra", "sr", "sra", "prof", "profa", "eng", "me", "mr", "mrs", "ms"}
_SPACES = re.compile(r"\s+")


def require_name(value: object, what: str = "O nome") -> str:
    """Nome obrigatório: remove espaços das pontas e recusa vazio ou só espaços."""
    name = str(value or "").strip()
    if not name:
        raise NexusError(f"{what} não pode ficar vazio.")
    return name


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação e sem títulos ("Dr.")."""
    base = strip_accents(text).lower()
    base = re.sub(r"[^\w\s]", " ", base)
    words = [w for w in _SPACES.split(base) if w and w not in _TITLES]
    return " ".join(words)


def normalize_identifier(scheme: str, value: str) -> str:
    v = value.strip()
    if scheme in {"cpf", "cnpj", "phone"}:
        return re.sub(r"\D", "", v)
    if scheme == "plate":
        return re.sub(r"[^A-Z0-9]", "", v.upper())
    if scheme in {"domain", "email"}:
        v = v.lower().rstrip(".")
        if scheme == "domain":
            v = re.sub(r"^[a-z]+://", "", v).split("/")[0]
            v = v.removeprefix("www.")
        return v
    return v.lower()


def valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(digits[i]) * (n + 1 - i) for i in range(n))
        if (total * 10 % 11) % 10 != int(digits[n]):
            return False
    return True


def valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for n in (12, 13):
        w = weights if n == 12 else [6, *weights]
        total = sum(int(digits[i]) * w[i] for i in range(n))
        rest = total % 11
        if (0 if rest < 2 else 11 - rest) != int(digits[n]):
            return False
    return True


IDENTIFIER_SCHEMES = {
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "domain": "Domínio",
    "email": "E-mail",
    "phone": "Telefone",
    "plate": "Placa",
    "ip": "Endereço IP",
    "registry": "Número de registro",
}
