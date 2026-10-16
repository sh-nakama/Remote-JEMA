"""The weekly summary email: what counts as "held this week", the brief, rendering and sending."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from repower import cli
from repower.db import PolicyMeeting
from repower.notify import mail
from repower.policy import schedule as sched
from repower.policy import store, weekly
from repower.policy.energy_board import BoardEntry

TODAY = date(2026, 10, 9)  # a Friday
NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)  # 17:00 JST, when the cron fires

DIGEST = """### **Key decisions**

* **Black start tender**: Confirmed the FY2030 tender proceeded without issues [1-5].
* **Alpha values**: Approved the revised alpha (\\\\(\\\\alpha\\\\)) values [6, 7, 10].
* **Shortages:**
  * Agreed to evaluate a discretionary contract for unprocured systems [11].
* **Fourth point**: Never shown, the brief stops at three.

---

### **Points of disagreement**

* **Fairness**: A member raised concerns [16].
"""


def _meeting(db, key, num, day, *, state="detected", digest=None, summarised_at=None, detected_at=None):
    store.record_meeting(key, num, None, db_path=db)
    with store.session_scope(db) as s:
        m = s.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=num).one()
        m.meeting_date = day
        m.state = state
        m.digest_en_json = json.dumps({"answer": digest}) if digest else None
        m.summarised_at = summarised_at
        if detected_at is not None:
            m.detected_at = detected_at


def _build(db, **kw):
    return weekly.build_report(db, today=TODAY, now=NOW, **kw)


# ── The brief ────────────────────────────────────────────────────────────────
def test_brief_takes_the_first_key_decisions_and_cleans_them():
    brief = weekly.extract_brief(DIGEST)
    assert brief == [
        ("Black start tender", "Confirmed the FY2030 tender proceeded without issues."),
        ("Alpha values", "Approved the revised alpha (α) values."),
        ("Shortages", "Agreed to evaluate a discretionary contract for unprocured systems."),
    ]


def test_brief_falls_back_to_any_bullets_then_the_first_paragraph():
    assert weekly.extract_brief("Intro\n\n- **A**: one [1]\n- two") == [("A", "one"), ("", "two")]
    assert weekly.extract_brief("### Heading\nJust prose here [3].\n\nMore.") == [("", "Just prose here.")]
    assert weekly.extract_brief("") == []


def test_brief_truncates_long_bullets_on_a_word_boundary():
    (t, body), = weekly.extract_brief("### Key decisions\n* **T**: " + "word " * 100)
    assert len(body) <= weekly.BRIEF_CHARS + 1 and body.endswith("…") and not body.endswith(" …")


# ── What goes in which section ───────────────────────────────────────────────
def test_sections_are_keyed_on_when_the_meeting_was_held(policy_db):
    db = policy_db
    store.set_committee_enabled("santeii", False, db_path=db)
    _meeting(db, "chousei_jukyu", 122, TODAY - timedelta(days=3), state="done", digest=DIGEST,
             summarised_at=NOW - timedelta(days=1))
    _meeting(db, "system_review", 50, TODAY, state="detected")  # held today, not summarised yet
    _meeting(db, "doji_shijo", 26, TODAY - timedelta(days=6), state="error")  # first day of the window
    _meeting(db, "santeii", 115, TODAY - timedelta(days=2), state="done", digest=DIGEST,
             summarised_at=NOW)  # summarised, but the committee is not tracked
    # Backlog: summarised this week but held long ago → never listed.
    _meeting(db, "emissions_trading", 3, TODAY - timedelta(days=200), state="done", digest=DIGEST,
             summarised_at=NOW - timedelta(hours=2))
    # Held the day before the window opened, summarised this week → "now available".
    _meeting(db, "saisei_kano", 80, TODAY - timedelta(days=7), state="done", digest=DIGEST,
             summarised_at=NOW - timedelta(days=2))
    # Held in the catch-up window but summarised before the last email → already sent.
    _meeting(db, "yojo_fuuryoku", 38, TODAY - timedelta(days=14), state="done", digest=DIGEST,
             summarised_at=NOW - timedelta(days=8))
    # Held tomorrow (a calendar mistake or a detection of a future date) → not this week.
    _meeting(db, "santeii", 116, TODAY + timedelta(days=1))

    r = _build(db)
    assert (r.start, r.end) == (TODAY - timedelta(days=6), TODAY)
    assert [(i.committee_key, i.meeting_num) for i in r.summarised] == [("chousei_jukyu", 122)]
    assert r.summarised[0].brief[0][0] == "Black start tender"
    assert [(i.committee_key, i.meeting_num) for i in r.late] == [("saisei_kano", 80)]
    held = {(i.committee_key, i.meeting_num): i.status for i in r.held}
    assert held == {
        ("system_review", 50): weekly.PENDING,
        ("doji_shijo", 26): weekly.FAILED,
        ("santeii", 115): weekly.SUMMARISED,
    }
    assert {i.committee_key: i.tracked for i in r.held}["santeii"] is False
    assert r.total_held == 4


def test_calendar_history_and_board_add_meetings_detection_never_saw(policy_db):
    db = policy_db
    _meeting(db, "chousei_jukyu", 122, TODAY - timedelta(days=3), state="done", digest=DIGEST,
             summarised_at=NOW)
    rows = [
        # Same meeting as the detected one → not repeated.
        sched.Upcoming(TODAY - timedelta(days=3), "調整力及び需給バランス評価等に関する委員会（第122回）",
                       "OCCTO", "meti", "http://cal", 122, "chousei_jukyu"),
        # A tracked committee whose materials are not out yet.
        sched.Upcoming(TODAY - timedelta(days=1), "制度検討作業部会（第51回）", "METI", "meti", "http://cal",
                       51, "system_review"),
        # A committee nobody tracks, listed by both the calendar and the board.
        sched.Upcoming(TODAY - timedelta(days=2), "電力・ガス取引監視等委員会（第620回）", "METI", "meti",
                       "http://cal", 620, None),
        # Outside the window.
        sched.Upcoming(TODAY - timedelta(days=9), "古い会合（第1回）", "METI", "meti", "http://cal", 1, None),
    ]
    store.replace_upcoming(rows, db_path=db, today=TODAY - timedelta(days=10))
    board = [
        BoardEntry("電力・ガス取引監視等委員会", "第620回 電力・ガス取引監視等委員会", None,
                   "https://www.meti.go.jp/x/620.html", 620, TODAY - timedelta(days=2)),
        # Matched to a tracked committee through its METI directory.
        BoardEntry("同時市場の在り方等に関する検討会", "第27回", "energy_environment/doji_shijo_kento",
                   "https://www.meti.go.jp/shingikai/energy_environment/doji_shijo_kento/027.html", 27,
                   TODAY - timedelta(days=4)),
        BoardEntry("無関係", "第1回", None, "https://x", 1, None),  # undated → skipped
    ]
    r = _build(db, board=board)
    held = {(i.committee_key, i.meeting_num, i.status) for i in r.held}
    assert held == {
        ("system_review", 51, weekly.NOT_PUBLISHED),
        (None, 620, weekly.UNTRACKED),
        ("doji_shijo", 27, weekly.NOT_PUBLISHED),
    }
    assert [i.meeting_num for i in r.summarised] == [122]


def test_a_detected_but_undated_meeting_on_the_calendar_reads_as_pending(policy_db):
    db = policy_db
    store.record_meeting("system_review", 51, None, db_path=db)  # detected, no date yet
    store.replace_upcoming(
        [sched.Upcoming(TODAY, "制度検討作業部会（第51回）", "METI", "meti", "http://cal", 51, "system_review")],
        db_path=db, today=TODAY - timedelta(days=1),
    )
    r = _build(db)
    assert [(i.meeting_num, i.status) for i in r.held] == [(51, weekly.PENDING)]
    assert r.undated == 1


# ── Calendar history (policy_upcoming keeps its past) ───────────────────────
def test_replace_upcoming_keeps_past_rows_and_prunes_old_ones(tmp_path):
    db = str(tmp_path / "u.db")
    day = date(2026, 7, 1)
    old = sched.Upcoming(day - timedelta(days=200), "古い（第1回）", "METI", "meti", "u", 1, None)
    held = sched.Upcoming(day - timedelta(days=2), "開催済み（第2回）", "METI", "meti", "u", 2, None)
    soon = sched.Upcoming(day + timedelta(days=3), "予定（第3回）", "METI", "meti", "u", 3, None)
    assert store.replace_upcoming([old, held, soon], db_path=db, today=day) == 1
    # The next refresh no longer lists the held meeting nor the future one: the past
    # row survives, the future snapshot is rewritten, the 200-day-old row never landed.
    later = sched.Upcoming(day + timedelta(days=5), "別の予定（第4回）", "METI", "meti", "u", 4, None)
    assert store.replace_upcoming([later], db_path=db, today=day) == 1
    assert [u["meeting_num"] for u in store.list_upcoming(db_path=db, today=day)] == [4]
    hist = store.calendar_entries(day - timedelta(days=30), day + timedelta(days=30), db_path=db)
    assert [u["meeting_num"] for u in hist] == [2, 4]
    # Re-sending an already-stored past row neither duplicates nor fails.
    store.replace_upcoming([held, later], db_path=db, today=day)
    assert len(store.calendar_entries(day - timedelta(days=30), day, db_path=db)) == 1


def test_migration_adds_summarised_at_without_backfilling(tmp_path):
    from repower import db as db_mod

    db = str(tmp_path / "old.db")
    store.sync_committees(db_path=db)
    _meeting(db, "chousei_jukyu", 1, TODAY, state="done")
    _meeting(db, "chousei_jukyu", 2, TODAY, state="detected")
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE policy_meeting DROP COLUMN summarised_at")
    con.commit()
    con.close()
    db_mod._INITIALIZED.discard(db)
    db_mod._ENGINES.pop(db, None)
    store.sync_committees(db_path=db)  # init_db → migrate

    con = sqlite3.connect(db)
    got = dict(con.execute("SELECT meeting_num, summarised_at IS NOT NULL FROM policy_meeting"))
    con.close()
    # The column is restored; old rows stay NULL rather than guessing from updated_at.
    assert got == {1: 0, 2: 0}


# ── Rendering ────────────────────────────────────────────────────────────────
def _report(**kw):
    item = weekly.WeeklyItem(
        date=TODAY, name="Committee <A>", name_ja="委員会", org="OCCTO", status=weekly.SUMMARISED,
        tracked=True, committee_key="k", meeting_num=5, url="https://x/?a=1&b=2",
        brief=[("Title", "Body & more")],
    )
    base = dict(start=TODAY - timedelta(days=6), end=TODAY, summarised=[item], late=[], held=[])
    base.update(kw)
    return weekly.WeeklyReport(**base)


def test_html_escapes_scraped_text_and_skips_an_empty_catch_up_section():
    out = weekly.render_html(_report())
    assert "Committee &lt;A&gt; 第5回" in out and "Body &amp; more" in out
    assert 'href="https://x/?a=1&amp;b=2"' in out
    assert "Summaries now available" not in out
    assert "Also held this week (0)" in out


def test_text_and_subject():
    r = _report()
    assert weekly.subject(r) == "JEMA weekly policy summary — 3–9 Oct 2026 (1 meeting held)"
    text = weekly.render_text(r)
    assert "- Fri 9 Oct · Committee <A> 第5回 [OCCTO]" in text
    assert "  • Title: Body & more" in text
    empty = _report(summarised=[])
    assert "no meetings held" in weekly.subject(empty)
    assert "No tracked meeting held this week has a summary yet." in weekly.render_text(empty)


def test_label_does_not_repeat_a_number_already_in_a_raw_name():
    it = weekly.WeeklyItem(date=TODAY, name="会合（第7回）", name_ja=None, org="METI",
                           status=weekly.UNTRACKED, tracked=False, meeting_num=7)
    assert weekly._label(it) == "会合（第7回）"


@pytest.mark.parametrize("start,end,want", [
    (date(2026, 10, 3), date(2026, 10, 9), "3–9 Oct 2026"),
    (date(2026, 9, 28), date(2026, 10, 4), "28 Sep – 4 Oct 2026"),
    (date(2026, 12, 27), date(2027, 1, 2), "27 Dec 2026 – 2 Jan 2027"),
])
def test_fmt_range(start, end, want):
    assert weekly.fmt_range(start, end) == want


# ── Sending ──────────────────────────────────────────────────────────────────
def _configure(monkeypatch, **kw):
    vals = dict(SMTP_HOST="smtp.example.test", SMTP_PORT=465, SMTP_USER="bot@example.test",
                SMTP_PASSWORD="pw", MAIL_FROM="", MAIL_TO="a@example.test; b@example.test")
    vals.update(kw)
    for k, v in vals.items():
        monkeypatch.setattr(mail.config, k, v)


def test_send_is_a_no_op_when_unconfigured(monkeypatch):
    _configure(monkeypatch, SMTP_PASSWORD="")
    assert mail.send_email("s", "t", "<p>h</p>") is False


def test_send_logs_in_and_sends_a_multipart_message(monkeypatch):
    _configure(monkeypatch)
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    assert mail.send_email("Subject", "plain", "<p>rich</p>") is True
    msg = sent["msg"]
    assert sent["host"] == ("smtp.example.test", 465) and sent["login"] == ("bot@example.test", "pw")
    assert msg["To"] == "a@example.test, b@example.test" and "bot@example.test" in msg["From"]
    assert {p.get_content_type() for p in msg.iter_parts()} == {"text/plain", "text/html"}


def test_send_failure_raises_without_leaking_the_password(monkeypatch):
    _configure(monkeypatch, SMTP_PASSWORD="hunter2")

    def boom(*a, **k):
        raise mail.smtplib.SMTPAuthenticationError(535, b"bad credentials hunter2")

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", boom)
    with pytest.raises(mail.EmailError) as e:
        mail.send_email("s", "t", "h")
    assert "hunter2" not in str(e.value) and "535" in str(e.value)


def test_dropped_connection_is_retried_then_names_the_stage(monkeypatch):
    _configure(monkeypatch, SMTP_PASSWORD="hunter2")
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    calls = []

    def dropped(*a, **k):
        calls.append(1)
        raise mail.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", dropped)
    with pytest.raises(mail.EmailError) as e:
        mail.send_email("s", "t", "h")
    assert len(calls) == mail.ATTEMPTS
    assert "at connect" in str(e.value) and "Connection unexpectedly closed" in str(e.value)


def test_a_transient_disconnect_then_success_sends(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(mail.time, "sleep", lambda s: None)
    state = {"n": 0, "sent": False}

    class Flaky:
        def __init__(self, *a, **k):
            state["n"] += 1
            if state["n"] == 1:
                raise mail.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            state["sent"] = True

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", Flaky)
    assert mail.send_email("s", "t", "h") is True and state["sent"] and state["n"] == 2


def test_a_smtp_reply_is_not_retried_and_is_redacted(monkeypatch):
    _configure(monkeypatch, SMTP_PASSWORD="hunter2")
    calls = []

    def refused(*a, **k):
        calls.append(1)
        raise mail.smtplib.SMTPAuthenticationError(535, b"bad credentials hunter2 for bot@example.test")

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", refused)
    with pytest.raises(mail.EmailError) as e:
        mail.send_email("s", "t", "h")
    assert len(calls) == 1 and "hunter2" not in str(e.value) and "bot@example.test" not in str(e.value)


def test_a_non_465_port_uses_starttls_and_strips_pasted_whitespace(monkeypatch):
    _configure(monkeypatch, SMTP_PORT=587, SMTP_PASSWORD="pw\n", SMTP_USER=" bot@example.test ")
    steps = []

    class Plain:
        def __init__(self, host, port, **kw):
            steps.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            steps.append("ehlo")

        def starttls(self, context=None):
            steps.append("starttls")

        def login(self, user, pw):
            steps.append(("login", user, pw))

        def send_message(self, msg):
            steps.append("send")

    monkeypatch.setattr(mail.smtplib, "SMTP", Plain)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", lambda *a, **k: pytest.fail("587 must not be implicit TLS"))
    assert mail.send_email("s", "t", "h") is True
    assert steps == [("connect", "smtp.example.test", 587), "ehlo", "starttls", "ehlo",
                     ("login", "bot@example.test", "pw"), "send"]


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_cli_dry_run_prints_and_writes_html_without_sending(monkeypatch, tmp_path):
    monkeypatch.setattr(weekly, "build_report", lambda **k: _report())
    monkeypatch.setattr(mail, "send_email", lambda *a: pytest.fail("dry run must not send"))
    out = tmp_path / "w.html"
    res = CliRunner().invoke(cli.app, ["policy", "weekly", "--dry-run", "--no-board", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "JEMA weekly policy summary — 3–9 Oct 2026" in res.output
    assert "Committee &lt;A&gt;" in out.read_text(encoding="utf-8")


def test_cli_fails_when_email_is_not_configured(monkeypatch):
    monkeypatch.setattr(weekly, "build_report", lambda **k: _report())
    _configure(monkeypatch, MAIL_TO="")
    res = CliRunner().invoke(cli.app, ["policy", "weekly", "--no-board"])
    assert res.exit_code == 1
