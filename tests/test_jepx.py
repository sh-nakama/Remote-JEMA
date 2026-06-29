"""Tests for repower.scrapers.jepx_spot.

Network-free: httpx.get is monkeypatched to return a synthetic cp932 CSV.
"""

from __future__ import annotations

from repower.scrapers import jepx_spot


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

_FAKE_CSV = _HEADER + "\n" + "\n".join(_ROWS) + "\n"


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:  # no-op
        return None


def _make_fake_get(csv_text: str):
    encoded = csv_text.encode("cp932")

    def _fake_get(url, *args, **kwargs):
        return _FakeResponse(encoded)

    return _fake_get


def test_period_to_time_mapping(monkeypatch):
    """period 1 -> 00:00, 2 -> 00:30, 48 -> 23:30 (via fetch_jepx_csv output)."""
    monkeypatch.setattr(jepx_spot.httpx, "get", _make_fake_get(_FAKE_CSV))

    df = jepx_spot.fetch_jepx_csv(2025)
    times = df["time"].tolist()

    assert times == ["00:00", "00:30", "23:30"]


def test_present_areas_populated_correctly(monkeypatch):
    """tepco_price and kansai_price carry the right numbers; tokyo alias matches."""
    monkeypatch.setattr(jepx_spot.httpx, "get", _make_fake_get(_FAKE_CSV))

    df = jepx_spot.fetch_jepx_csv(2025)

    assert df["tepco_price"].tolist() == [11.5, 21.5, 31.5]
    assert df["kansai_price"].tolist() == [12.5, 22.5, 32.5]
    assert df["system_price"].tolist() == [10.0, 20.0, 30.0]

    # Legacy alias must equal tepco_price.
    assert df["tokyo_area_price"].tolist() == df["tepco_price"].tolist()


def test_missing_area_is_all_na_not_filled(monkeypatch):
    """The #1 fix: a missing area column must NOT be silently filled from another."""
    monkeypatch.setattr(jepx_spot.httpx, "get", _make_fake_get(_FAKE_CSV))

    df = jepx_spot.fetch_jepx_csv(2025)

    assert "hokkaido_price" in df.columns
    # Every value for the absent area column must be NA/NaN.
    assert df["hokkaido_price"].isna().all()
    # And it must not coincidentally equal any populated area.
    assert not df["hokkaido_price"].equals(df["tepco_price"])
