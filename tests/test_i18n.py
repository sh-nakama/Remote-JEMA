"""The Streamlit dashboard's translation table: every label it looks up resolves."""

from __future__ import annotations

import pathlib
import re

from repower.dashboard import i18n

DASHBOARD = pathlib.Path(__file__).resolve().parents[1] / "src" / "repower" / "dashboard"


def test_every_metric_has_a_japanese_label():
    # metric_labels() builds these keys as f"met_{key}", so no literal reference marks them used.
    missing = [k for k, v in i18n.metric_labels("ja").items() if v == f"met_{k}"]
    assert not missing


def test_every_literal_key_is_in_the_table():
    # T() falls back to the key itself, so a mistyped key renders its identifier instead of text.
    src = "\n".join(p.read_text(encoding="utf-8") for p in DASHBOARD.rglob("*.py"))
    keys = set(re.findall(r"""\bT\(\s*["']([a-z_]+)["']""", src))
    assert keys, "no T(...) calls found; has the helper been renamed?"
    assert keys <= i18n._STRINGS.keys(), sorted(keys - i18n._STRINGS.keys())
