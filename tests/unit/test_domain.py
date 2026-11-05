from __future__ import annotations

from datetime import date

import pytest

from nexus_intel.domain.dates import parse_fuzzy_date
from nexus_intel.domain.ids import is_ulid, new_ulid, ulid_timestamp_ms
from nexus_intel.domain.model import normalize_identifier, normalize_name, valid_cnpj, valid_cpf
from nexus_intel.domain.rules import find_conflicts, score_duplicate


def test_ulid_sortable_and_valid():
    a = new_ulid(1_700_000_000_000)
    b = new_ulid(1_700_000_000_001)
    assert is_ulid(a) and a < b
    assert ulid_timestamp_ms(a) == 1_700_000_000_000


@pytest.mark.parametrize(
    ("text", "start", "end", "prec"),
    [
        ("1998", date(1998, 1, 1), date(1998, 12, 31), "year"),
        ("1990", date(1990, 1, 1), date(1990, 12, 31), "year"),
        ("1990s", date(1990, 1, 1), date(1999, 12, 31), "decade"),
        ("03/1998", date(1998, 3, 1), date(1998, 3, 31), "month"),
        ("1998-02", date(1998, 2, 1), date(1998, 2, 28), "month"),
        ("15/03/1998", date(1998, 3, 15), date(1998, 3, 15), "day"),
        ("1998-03-15", date(1998, 3, 15), date(1998, 3, 15), "day"),
        ("década de 1990", date(1990, 1, 1), date(1999, 12, 31), "decade"),
        ("c. 1850", date(1848, 1, 1), date(1852, 12, 31), "approximate"),
    ],
)
def test_fuzzy_dates(text, start, end, prec):
    d = parse_fuzzy_date(text)
    assert (d.start, d.end, d.precision) == (start, end, prec)


def test_bad_date():
    with pytest.raises(ValueError):
        parse_fuzzy_date("ontem")


def test_normalize_name():
    assert normalize_name("Dr. João  da Silva") == "joao da silva"
    assert normalize_identifier("cpf", "123.456.789-09") == "12345678909"
    assert normalize_identifier("domain", "https://www.Exemplo.com.br/x") == "exemplo.com.br"
    assert normalize_identifier("plate", "abc-1d23") == "ABC1D23"


def test_document_checksums():
    assert valid_cpf("52998224725") and not valid_cpf("52998224724")
    assert valid_cnpj("11222333000181") and not valid_cnpj("11222333000182")


def _c(i, text, status="reported", vf=None, vt=None):
    return {"id": i, "value_text": text, "epistemic_status": status, "valid_from": vf, "valid_to": vt}


def test_conflict_rules():
    claims = [_c("a", "1985"), _c("b", "1986")]
    assert find_conflicts(claims, "single") == {"a", "b"}
    assert find_conflicts(claims, "multi") == set()
    refuted = [_c("a", "1985"), _c("b", "1986", status="refuted")]
    assert find_conflicts(refuted, "single") == set()
    periods = [_c("a", "Rua A", vf="2010", vt="2015"), _c("b", "Rua B", vf="2016")]
    assert find_conflicts(periods, "single_per_period") == set()
    overlap = [_c("a", "Rua A", vf="2010", vt="2017"), _c("b", "Rua B", vf="2016")]
    assert find_conflicts(overlap, "single_per_period") == {"a", "b"}
    same = [_c("a", "Itália"), _c("b", "itália")]
    assert find_conflicts(same, "single") == set()


def test_duplicate_scores():
    assert score_duplicate("joao silva", "joao silva")[0] >= 90
    assert score_duplicate("joao silva", "silva joao")[0] >= 70
    assert score_duplicate("joao silva", "maria souza")[0] < 70
    assert score_duplicate("a", "b", same_identifier=True)[0] == 100
