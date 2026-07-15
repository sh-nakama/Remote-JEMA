"""Tests for the committee catalog + tracked-set management:

- ``catalog.parse_*`` committee-index parsers (pure, inline HTML fixtures).
- ``store`` tracked-set helpers (enabled flag, config round-trip, discovery upsert).
- the shared ``export_web.build_committees_payload`` tracked/discovered flags and a
  fresh-DB ``export_policy`` (guards the enabled/priority schema regression).

Network-free: parsers run on inline fixtures; DB helpers use a temporary SQLite path.
"""

from __future__ import annotations

from repower.dashboard import export_web
from repower.policy import catalog, store
from repower.policy.committees import committee_keys

# ── Catalog parsers (no network) ──────────────────────────────────────────────
OCCTO_INDEX = """
<html><body>
  <a href="/iinkai/chousei_jukyu/index.html">調整力及び需給バランス評価等に関する委員会</a>
  <a href="/iinkai/jukyuchousei/index.html">需給調整市場検討小委員会</a>
  <a href="/iinkai/unei/index.html">運営委員会</a>
  <a href="https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/index.html">同時市場の在り方等に関する検討会</a>
  <a href="/iinkai/">委員会・検討会 一覧</a>
</body></html>
"""

EGC_INDEX = """
<html><body>
  <a href="/activity/index_system.html">制度設計専門会合</a>
  <a href="/activity/index_electricity.html">料金制度専門会合</a>
  <a href="/committee/">委員会について</a>
</body></html>
"""

METI_INDEX = """
<html><body>
  <a href="/shingikai/enecho/denryoku_gas/saisei_kano/index.html">再生可能エネルギー大量導入・次世代電力ネットワーク小委員会</a>
  <a href="/shingikai/enecho/shigen_nenryo/kogyo/index.html">鉱業小委員会</a>
  <a href="https://www.enecho.meti.go.jp/committee/council/basic_policy_subcommittee/index.html#x">2050年カーボンニュートラル小委員会</a>
  <a href="/shingikai/enecho/index.html">審議会トップ</a>
</body></html>
"""


def test_parse_occto_committees_slugs_and_skips_external():
    out = {c["key"]: c for c in catalog.parse_occto_committees(OCCTO_INDEX)}
    # slugs become keys; OCCTO is not keyword-filtered (運営委員会 kept), external + index skipped
    assert set(out) == {"chousei_jukyu", "jukyuchousei", "unei"}
    assert out["chousei_jukyu"]["source"] == "OCCTO"
    assert out["chousei_jukyu"]["prefix"] == "chousei_jukyu"
    assert out["chousei_jukyu"]["url"].endswith("/iinkai/chousei_jukyu/index.html")


def test_parse_egc_committees_keys_prefixed():
    out = {c["key"]: c for c in catalog.parse_egc_committees(EGC_INDEX)}
    assert set(out) == {"emsc_system", "emsc_electricity"}
    assert out["emsc_system"]["source"] == "EGC"


def test_parse_meti_enecho_committees_filters_and_normalises():
    out = {c["key"]: c for c in catalog.parse_meti_enecho_committees(METI_INDEX)}
    # 鉱業 dropped (not energy), enecho.meti.go.jp anchor link skipped, index self skipped
    assert set(out) == {"saisei_kano"}
    assert out["saisei_kano"]["source"] == "METI"
    # URL normalised to the config's trailing-slash form (no index.html)
    assert out["saisei_kano"]["url"].endswith("/denryoku_gas/saisei_kano/")


# ── Tracked-set store helpers ─────────────────────────────────────────────────
def test_sync_seeds_enabled_and_config_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    keys = store.enabled_committee_keys(db_path=db)
    assert set(keys) == set(committee_keys())  # all config committees tracked by default
    # EGC scraper config round-trips through the DB (log_pages JSON, min_meeting)
    c = store.committee_or_config("emsc_system", db_path=db)
    assert c.source == "EGC" and c.min_meeting == 30 and len(c.log_pages) == 6


def test_set_enabled_and_sync_preserves_user_toggle(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    assert store.set_committee_enabled("system_review", False, db_path=db) is True
    assert "system_review" not in store.enabled_committee_keys(db_path=db)
    # re-syncing config must NOT re-enable a committee the user untracked
    store.sync_committees(db_path=db)
    assert "system_review" not in store.enabled_committee_keys(db_path=db)
    # unknown key → False, no crash
    assert store.set_committee_enabled("does_not_exist", True, db_path=db) is False


def test_set_priority_persists_across_sync(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    # a discovered committee starts at priority 100; bump it ahead of chousei_jukyu (3)
    store.upsert_discovered_committees(
        [{"key": "newcom", "name_ja": "新", "source": "OCCTO", "url": "https://www.occto.or.jp/iinkai/newcom/index.html"}],
        db_path=db,
    )
    assert store.set_committee_enabled("newcom", True, db_path=db) is True
    assert store.set_committee_priority("newcom", 2, db_path=db) is True
    # re-syncing config must NOT reset a user-set priority (permanent queue jump)
    store.sync_committees(db_path=db)
    row = {r["key"]: r for r in store.list_committees(db_path=db)}["newcom"]
    assert row["priority"] == 2
    assert store.set_committee_priority("nope", 1, db_path=db) is False


def test_committee_or_config_db_first_then_config_then_none(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    assert store.committee_or_config("system_review", db_path=db).key == "system_review"
    assert store.committee_or_config("totally_unknown", db_path=db) is None


def test_upsert_discovered_dedup_by_url_and_key_collision(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    config_url = store.committee_or_config("saisei_kano", db_path=db).url
    inserted = store.upsert_discovered_committees(
        [
            # same committee as config (URL matches modulo index.html) → skipped
            {"key": "saisei_kano", "name_ja": "x", "source": "METI", "url": config_url + "index.html"},
            # different committee sharing the slug → key disambiguated, inserted untracked
            {"key": "saisei_kano", "name_ja": "別委員会", "source": "METI",
             "url": "https://www.meti.go.jp/shingikai/enecho/kihon_seisaku/saisei_kano/"},
            # brand-new committee → inserted untracked
            {"key": "newcom", "name_ja": "新委員会", "source": "OCCTO", "url": "https://www.occto.or.jp/iinkai/newcom/index.html"},
        ],
        db_path=db,
    )
    assert inserted == 2
    rows = {r["key"]: r for r in store.list_committees(db_path=db)}
    assert rows["saisei_kano"]["enabled"] is True  # config one untouched
    assert rows["saisei_kano_2"]["enabled"] is False  # collision → suffixed, untracked
    assert rows["newcom"]["enabled"] is False
    # re-running discovery is idempotent (nothing new the second time)
    assert store.upsert_discovered_committees(
        [{"key": "newcom", "name_ja": "新委員会", "source": "OCCTO", "url": "https://www.occto.or.jp/iinkai/newcom/index.html"}],
        db_path=db,
    ) == 0


# ── Manual add-by-URL ─────────────────────────────────────────────────────────
def test_parse_meti_committee_url_validates_and_normalises():
    ok = catalog.parse_meti_committee_url(
        "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/stable_power_supply_wg/index.html?x=1#top"
    )
    assert ok == {
        "key": "stable_power_supply_wg",
        "url": "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/stable_power_supply_wg/",
        "dir": "enecho/denryoku_gas/jisedai_kiban/stable_power_supply_wg",
    }
    # trailing-slash and bare forms normalise identically
    assert catalog.parse_meti_committee_url(
        "https://www.meti.go.jp/shingikai/enecho/santeii"
    )["url"].endswith("/shingikai/enecho/santeii/")
    # non-METI / non-shingikai / meeting-page URLs rejected
    assert catalog.parse_meti_committee_url("https://www.occto.or.jp/iinkai/chousei_jukyu/index.html") is None
    assert catalog.parse_meti_committee_url("https://www.meti.go.jp/press/2026/07/foo.html") is None
    assert catalog.parse_meti_committee_url("https://www.meti.go.jp/shingikai/enecho/santeii/004.html") is None
    assert catalog.parse_meti_committee_url("") is None


def test_parse_meti_page_title_h1_then_title_boilerplate_stripped():
    assert catalog.parse_meti_page_title("<html><body><h1>電力安定供給ワーキンググループ</h1></body></html>") \
        == "電力安定供給ワーキンググループ"
    assert catalog.parse_meti_page_title(
        "<html><head><title>電力安定供給ワーキンググループ（METI/経済産業省）</title></head></html>"
    ) == "電力安定供給ワーキンググループ"
    assert catalog.parse_meti_page_title("<html><body><p>x</p></body></html>") is None


def test_add_user_committee_tracked_and_dedup(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    res = store.add_user_committee(
        {"key": "some_wg", "name_ja": "某WG", "source": "METI",
         "url": "https://www.meti.go.jp/shingikai/enecho/foo/some_wg/"},
        db_path=db,
    )
    assert res == {"key": "some_wg", "existing": False}
    rows = {r["key"]: r for r in store.list_committees(db_path=db)}
    assert rows["some_wg"]["enabled"] is True  # auto-tracked (unlike discovery)
    # same URL again (index.html form) → existing row returned, no duplicate
    res2 = store.add_user_committee(
        {"key": "renamed", "name_ja": "x", "source": "METI",
         "url": "https://www.meti.go.jp/shingikai/enecho/foo/some_wg/index.html"},
        db_path=db,
    )
    assert res2 == {"key": "some_wg", "existing": True}
    # config-committee URL → its existing key, untouched
    config_url = store.committee_or_config("saisei_kano", db_path=db).url
    res3 = store.add_user_committee(
        {"key": "saisei_kano", "name_ja": "x", "source": "METI", "url": config_url},
        db_path=db,
    )
    assert res3 == {"key": "saisei_kano", "existing": True}


def test_add_committee_by_url_end_to_end(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    monkeypatch.setattr(
        catalog, "_fetch",
        lambda url, db_path=None: b"<html><head><title>\xe9\x9b\xbb\xe5\x8a\x9b\xe5\xae\x89\xe5\xae\x9a\xe4\xbe\x9b\xe7\xb5\xa6\xef\xbc\xb7\xef\xbc\xa7\xef\xbc\x88METI/\xe7\xb5\x8c\xe6\xb8\x88\xe7\x94\xa3\xe6\xa5\xad\xe7\x9c\x81\xef\xbc\x89</title></head></html>",
    )
    res = catalog.add_committee_by_url(
        "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/some_new_wg/index.html",
        db_path=db,
    )
    assert res["ok"] is True and res["existing"] is False and res["key"] == "some_new_wg"
    assert res["name_ja"]  # page title extracted
    rows = {r["key"]: r for r in store.list_committees(db_path=db)}
    assert rows["some_new_wg"]["enabled"] is True
    # name fallback when METI is unreachable (WAF-challenged): slug-only row, still added
    monkeypatch.setattr(catalog, "_fetch", lambda url, db_path=None: None)
    res2 = catalog.add_committee_by_url(
        "https://www.meti.go.jp/shingikai/enecho/other_wg/", db_path=db, track=False
    )
    assert res2["ok"] is True and res2["key"] == "other_wg" and res2["name_ja"] == ""
    rows = {r["key"]: r for r in store.list_committees(db_path=db)}
    assert rows["other_wg"]["enabled"] is False
    # invalid URL raises
    import pytest

    with pytest.raises(ValueError):
        catalog.add_committee_by_url("https://example.com/shingikai/x/", db_path=db)


# ── Export payload flags + fresh-DB safety ────────────────────────────────────
def test_build_committees_payload_flags():
    committees = [
        {"committee_key": "system_review", "name_ja": "制度検討", "name_en": "System Review",
         "url": "u", "source": "METI", "latest_meeting": 114, "source_count": 12, "enabled": 1, "priority": 1},
        {"committee_key": "some_discovered", "name_ja": "発見", "name_en": "Discovered",
         "url": "u2", "source": "OCCTO", "latest_meeting": None, "source_count": 0, "enabled": 0, "priority": 100},
    ]
    meetings = [{"committee_key": "system_review", "meeting_date": "2026-05-08"}]
    payload = {c["key"]: c for c in export_web.build_committees_payload(committees, meetings)}
    assert payload["system_review"]["tracked"] is True
    assert payload["system_review"]["discovered"] is False  # in config
    assert payload["some_discovered"]["tracked"] is False
    assert payload["some_discovered"]["discovered"] is True  # not in config


def test_export_policy_on_fresh_db(tmp_path):
    # Regression guard: a fresh DB built from the model must export policy without
    # the old "no such column: enabled" failure.
    db = str(tmp_path / "fresh.db")
    store.sync_committees(db_path=db)
    res = export_web.export_policy(tmp_path / "web", db_path=db)
    assert res.get("error") is None
    assert res["committees"] == len(committee_keys())
