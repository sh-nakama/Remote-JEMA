"""Tests for repower.scrapers.jepx_spot CSV parsing.

Network-free: exercises the pure ``parse_jepx_csv`` on synthetic cp932 bytes.
"""

from __future__ import annotations

from repower.scrapers.jepx_spot import parse_jepx_csv

# JEPX CSV header. We deliberately include エリアプライス東京 (tepco) and
# エリアプライス関西 (kansai) but OMIT エリアプライス北海道 (hokkaido) so we can
# assert the missing area is NOT silently filled from another column.
_HEADER = "年月日,時刻コード,col2,col3,col4,システムプライス,エリアプライス東京,エリアプライス関西"

# period 1 -> 00:00, period 2 -> 00:30, period 48 -> 23:30
_ROWS = [
    "2025/01/01,1,x,x,x,10.0,11.5,12.5",
    "2025/01/01,2,x,x,x,20.0,21.5,22.5",
    "2025/01/01,48,x,x,x,30.0,31.5,32.5",
]

_CONTENT = (_HEADER + "\n" + "\n".join(_ROWS) + "\n").encode("cp932")


def test_period_to_time_mapping():
    """period 1 -> 00:00, 2 -> 00:30, 48 -> 23:30 (via parse_jepx_csv output)."""
    df = parse_jepx_csv(_CONTENT)
    assert df["time"].tolist() == ["00:00", "00:30", "23:30"]


def test_present_areas_populated_correctly():
    """tepco_price and kansai_price carry the right numbers; tokyo alias matches."""
    df = parse_jepx_csv(_CONTENT)

    assert df["tepco_price"].tolist() == [11.5, 21.5, 31.5]
    assert df["kansai_price"].tolist() == [12.5, 22.5, 32.5]
    assert df["system_price"].tolist() == [10.0, 20.0, 30.0]

    # Legacy alias must equal tepco_price.
    assert df["tokyo_area_price"].tolist() == df["tepco_price"].tolist()


def test_missing_area_is_all_na_not_filled():
    """The #1 fix: a missing area column must NOT be silently filled from another."""
    df = parse_jepx_csv(_CONTENT)

    assert "hokkaido_price" in df.columns
    # Every value for the absent area column must be NA/NaN.
    assert df["hokkaido_price"].isna().all()
    # And it must not coincidentally equal any populated area.
    assert not df["hokkaido_price"].equals(df["tepco_price"])
