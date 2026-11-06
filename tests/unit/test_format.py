from datetime import UTC, datetime, timedelta

from nexus_intel.ui.format import number, percent, relative

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


def test_relative_times():
    assert relative(ago(seconds=10), NOW) == "agora"
    assert relative(ago(minutes=5), NOW) == "há 5 min"
    assert relative(ago(hours=2), NOW) == "há 2 h"
    assert relative(ago(days=3, hours=1), NOW) == "há 3 dias"
    assert relative("2020-01-15T10:00:00+00:00", NOW) == "15 jan 2020"
    assert relative(None) == "" and relative("lixo") == "lixo"


def test_numbers():
    assert number(12345) == "12.345"
    assert number(1234.5) == "1.234,5"
    assert percent(1, 3) == "33%" and percent(1, 0) == "0%"
