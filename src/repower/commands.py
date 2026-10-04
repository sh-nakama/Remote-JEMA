"""The CLI commands the local app can run, in one place.

This registry is the single source for three things that used to drift apart: the
``web-api`` allowlist (which commands may run, and what each argument may be), the
Commands pane in the web app (titles, safety levels, order, forms) and the guide text
shown beside each button. Add a command here and it exists in all three; a test
resolves every entry against the real Typer app, so a renamed CLI command fails CI
instead of becoming a dead button.

**Safety levels** (``Command.level``):

* ``safe`` — read-only or sign-in only; run it as often as you like.
* ``writes`` — changes local data (the DB, Parquet files, snapshots). Idempotent
  and re-runnable, but the change stays on this machine until pushed.
* ``dangerous`` — overwrites a whole database. ``pull-hf`` replaces the local copy
  with Hugging Face's; ``push-hf`` replaces the shared dataset with the local copy.
  Both are last-write-wins with no locking, so *order matters*: see :data:`RECIPES`.

**Groups** (``Command.group``): ``backflow`` is the back-catalogue workflow, listed in
the order it should be run (``order``); ``inspect`` is read-only diagnostics;
``automated`` are things the daily GitHub Actions already do, so there is normally no
reason to run them by hand.

Not exposed on purpose: ``notify`` / ``run-all`` (they post to the webhook),
``init-db-cmd``, the top-level market ``backfill``, and the per-committee admin
commands (``enable``/``archive``/``priority``… — the Manage modal already has those).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

SAFE = "safe"
WRITES = "writes"
DANGEROUS = "dangerous"

BACKFLOW = "backflow"
INSPECT = "inspect"
AUTOMATED = "automated"

Bilingual = tuple[str, str]


@dataclass(frozen=True)
class Param:
    """One argument a button can pass. ``flag`` is the CLI option it becomes."""

    name: str
    kind: str  # committee | int | bool | choice
    flag: str
    label: Bilingual
    default: Any = None
    lo: int = 0
    hi: int = 0
    required: bool = False
    choices: tuple[str, ...] = ()
    # Bool only: when set, the flag is emitted for *False* (e.g. ``--all`` for failing_only=False).
    off_flag: str | None = None
    ui: bool = True  # False: accepted by the API, but not offered as a form field


@dataclass(frozen=True)
class Command:
    id: str
    argv: tuple[str, ...]  # what follows ``python -m repower.cli``
    group: str
    level: str
    order: int
    title: Bilingual
    summary: Bilingual  # what it does
    when: Bilingual  # when to reach for it, and anything to know first
    params: tuple[Param, ...] = ()
    fixed: tuple[str, ...] = ()  # always appended (e.g. --dry-run for a UI click)
    needs_notebooklm: bool = False
    timeout_s: int = 600
    warning: Bilingual | None = None  # shown in the confirm dialog of a dangerous command


_COMMITTEE = Param("committee", "committee", "--committee", ("Committee", "委員会"), default="all")
_COMMITTEE_REQ = Param("committee", "committee", "--committee", ("Committee", "委員会"), required=True)
_COMMITTEE_OPT = Param("committee", "committee", "--committee", ("Committee (optional)", "委員会（任意）"))

_NBLM_TIMEOUT = 5400  # 1.5h; a meeting can block ~20 min on one report; see web_api._NOTEBOOKLM_TIMEOUT_S

COMMANDS: tuple[Command, ...] = (
    # ── Backflow: the back-catalogue workflow, in the order to run it ─────────────
    Command(
        "pull-hf", ("pull-hf",), BACKFLOW, DANGEROUS, 1,
        ("Pull from Hugging Face", "Hugging Faceから取得"),
        ("Replaces your local database and Parquet files with the shared dataset's.",
         "ローカルのDBとParquetを、共有データセットの内容で置き換えます。"),
        ("Start every working session here, so you build on what the daily runs added. Push first if "
         "you have local work you want to keep.",
         "作業の最初に実行し、日次実行の更新を取り込みます。残したいローカルの変更がある場合は先にpushしてください。"),
        timeout_s=1800,
        warning=("This REPLACES your local database with the Hugging Face copy. Anything you changed "
                 "locally and have not pushed is lost.",
                 "ローカルのDBがHugging Face上のコピーで置き換えられます。pushしていないローカルの変更は失われます。"),
    ),
    Command(
        "detect", ("policy", "detect"), BACKFLOW, WRITES, 2,
        ("Detect new meetings", "新規会合を検出"),
        ("Finds meetings that have appeared on the committee pages (also records their dates).",
         "委員会ページに新しく掲載された会合を検出します（開催日も記録）。"),
        ("Auth-free. Safe to repeat; the source site throttles bursts, so a bad day just finds less.",
         "認証不要。繰り返し実行できます。配信元は集中アクセスを制限するため、混雑時は検出が少なくなります。"),
        (_COMMITTEE,),
    ),
    Command(
        "dates", ("policy", "dates"), BACKFLOW, WRITES, 3,
        ("Fill missing dates", "開催日を補完"),
        ("Repairs meetings that have no meeting date yet.", "開催日が未取得の会合を補完します。"),
        ("Without a date a meeting shows as 検出 (detected) with its detection day.",
         "開催日が無い会合は「検出」日付で表示されます。"),
        (_COMMITTEE,),
    ),
    Command(
        "materials", ("policy", "materials"), BACKFLOW, WRITES, 4,
        ("Fetch missing materials", "未取得の資料を取得"),
        ("Fetches the PDFs list for meetings detected without any, which is what makes them visible.",
         "資料が未取得の会合の資料一覧を取得します。取得できて初めて画面に表示されます。"),
        ("`limit` 0 means unbounded (a full heal); use a small limit if the host has been blocking.",
         "limit が0の場合は無制限（全件修復）。ブロックされている場合は小さい値にしてください。"),
        (_COMMITTEE,
         Param("limit", "int", "--limit", ("Max per committee (0 = all)", "委員会あたりの上限（0=無制限）"),
               default=0, lo=0, hi=500)),
    ),
    Command(
        "auth", ("policy", "auth"), BACKFLOW, SAFE, 5,
        ("Check NotebookLM login", "NotebookLMのログイン確認"),
        ("Checks that the NotebookLM session is valid (a live test, not just a file check).",
         "NotebookLMのセッションが有効か確認します（ファイルの有無ではなく実際に通信して確認）。"),
        ("Run before the summarising steps below. If it fails, use Sign in to NotebookLM.",
         "以下の要約ステップの前に実行します。失敗したら「NotebookLMにログイン」を実行してください。"),
        needs_notebooklm=True, timeout_s=180,
    ),
    Command(
        "login", ("policy", "login"), BACKFLOW, SAFE, 6,
        ("Sign in to NotebookLM", "NotebookLMにログイン"),
        ("Opens a browser window on this machine for Google sign-in and saves the session.",
         "この端末でブラウザを開き、Googleにログインしてセッションを保存します。"),
        ("Only needed when the check above fails. Finish signing in within 5 minutes; no terminal input "
         "is needed. This refreshes the LOCAL session only — the daily GitHub Action uses the "
         "NOTEBOOKLM_AUTH_JSON secret, which you update separately. While it waits, other commands are blocked.",
         "上のログイン確認が失敗したときのみ。5分以内にログインを完了してください（ターミナル入力は不要）。"
         "更新されるのはローカルのセッションのみで、日次のGitHub Actionが使うNOTEBOOKLM_AUTH_JSONシークレットは別途更新が必要です。"
         "待機中は他のコマンドは実行できません。"),
        (Param("browser", "choice", "--browser", ("Browser", "ブラウザ"), default="chromium",
               choices=("chromium", "chrome", "msedge")),),
        needs_notebooklm=True, timeout_s=420,
    ),
    Command(
        "backfill", ("policy", "backfill"), BACKFLOW, WRITES, 7,
        ("Backfill older meetings", "過去の会合を遡及要約"),
        ("Summarises one committee's older meetings, newest first, from a meeting number onwards.",
         "1つの委員会の過去の会合を、指定の回以降について新しい順に要約します。"),
        ("The main backflow step. Needs a NotebookLM login. Budget-limited per run — re-run to continue.",
         "遡及フローの中心。NotebookLMのログインが必要。1回あたり上限があるため、続きは再実行します。"),
        (_COMMITTEE_REQ,
         Param("since_meeting", "int", "--since-meeting", ("From meeting no.", "開始回"),
               required=True, lo=1, hi=100000),
         Param("max_per_run", "int", "--max-per-run", ("Max this run", "今回の上限"), default=10, lo=1, hi=30)),
        needs_notebooklm=True, timeout_s=_NBLM_TIMEOUT,
    ),
    Command(
        "resume", ("policy", "resume"), BACKFLOW, WRITES, 8,
        ("Resume stuck meetings", "中断した会合を再開"),
        ("Finishes meetings left mid-flight by an interrupted or rate-limited run.",
         "中断やレート制限で途中のまま残った会合を完了させます。"),
        ("Does nothing if none are stuck. Needs a NotebookLM login.",
         "対象が無ければ何もしません。NotebookLMのログインが必要。"),
        needs_notebooklm=True, timeout_s=_NBLM_TIMEOUT,
    ),
    Command(
        "run", ("policy", "run"), BACKFLOW, WRITES, 9,
        ("Summarise pending meetings", "未要約の会合を要約"),
        ("Summarises pending meetings of tracked committees, then refreshes each committee's synthesis.",
         "追跡中の委員会の未要約の会合を要約し、委員会の総括を更新します。"),
        ("The daily run already does this, so use it for a specific committee or to catch up faster. "
         "Needs a NotebookLM login.",
         "日次実行でも行われます。特定の委員会や追い上げに使います。NotebookLMのログインが必要。"),
        (_COMMITTEE,
         Param("max_per_run", "int", "--max-per-run", ("Max this run", "今回の上限"), default=5, lo=1, hi=20),
         Param("breadth", "bool", "--breadth", ("Spread across committees", "委員会に分散"), default=False),
         # "Run now" on one meeting (the Manage modal's ▶): needs a real committee.
         Param("meeting", "int", "--meeting", ("Meeting no.", "回"), lo=1, hi=100000, ui=False)),
        needs_notebooklm=True, timeout_s=_NBLM_TIMEOUT,
    ),
    Command(
        "resolve-citations", ("policy", "resolve-citations"), BACKFLOW, WRITES, 10,
        ("Resolve citation pages", "引用ページを解決"),
        ("Finds the document and page behind each digest citation, for meetings summarised before pages "
         "were tracked.",
         "ページ追跡の導入前に要約された会合について、各引用の資料とページを特定します。"),
        ("Auth-free and resumable; re-download of PDFs is paced and stops when the host's budget is spent. "
         "Needs PyMuPDF (`pip install -e \".[pdf]\"`). Push afterwards to sync it.",
         "認証不要で再開可能。PDFの再取得は間隔を空け、配信元の上限に達すると停止します。PyMuPDFが必要。結果の反映にはpushが必要です。"),
        (Param("max_meetings", "int", "--max-meetings", ("Max meetings", "最大会合数"), default=5, lo=1, hi=50),
         _COMMITTEE_OPT,
         Param("keep_pdfs", "bool", "--keep-pdfs", ("Keep downloaded PDFs", "PDFを保持"), default=False)),
        timeout_s=1800,
    ),
    Command(
        "tag", ("policy", "tag"), BACKFLOW, WRITES, 11,
        ("Apply topic tags", "トピックタグを適用"),
        ("Applies the rule-based topic tags to committees and meetings.",
         "ルールベースのトピックタグを委員会と会合に適用します。"),
        ("Untick Apply for a dry run that only prints what would change. Hand-set and NotebookLM tags are never overwritten.",
         "「適用」を外すと変更内容の表示のみ（ドライラン）。手動設定やNotebookLMのタグは上書きされません。"),
        (Param("apply", "bool", "--apply", ("Apply (otherwise dry run)", "適用（外すとドライラン）"), default=True),
         _COMMITTEE),
    ),
    Command(
        "export-web", ("export-web",), BACKFLOW, WRITES, 12,
        ("Rebuild web snapshots", "Webスナップショットを再生成"),
        ("Rewrites the static JSON the read-only site serves from the current database.",
         "現在のDBから、閲覧専用サイトが読む静的JSONを再生成します。"),
        ("The local app reads the live API, so this matters only for what gets published. The daily deploy rebuilds it too.",
         "ローカルのアプリはライブAPIを読むため、影響するのは公開内容のみ。日次デプロイでも再生成されます。"),
        timeout_s=900,
    ),
    Command(
        "push-hf", ("push-hf",), BACKFLOW, DANGEROUS, 13,
        ("Push to Hugging Face", "Hugging Faceへ送信"),
        ("Replaces the shared dataset with your local database and Parquet files.",
         "共有データセットを、ローカルのDBとParquetで置き換えます。"),
        ("Do this last. The daily runs write to the same dataset, so pull first (a stale local copy "
         "overwrites what they added). Pushing is what makes your backflow reach production.",
         "必ず最後に実行します。日次実行も同じデータセットに書き込むため、先にpullしてください（古いローカルコピーは更新を上書きします）。"),
        timeout_s=1800,
        warning=("This REPLACES the shared Hugging Face dataset — what the daily runs read and write — with your "
                 "local database. Last write wins; nothing is merged.",
                 "共有のHugging Faceデータセット（日次実行が読み書きするもの）が、ローカルのDBで置き換えられます。"
                 "最後の書き込みが優先され、マージはされません。"),
    ),
    # ── Inspect: read-only diagnostics ───────────────────────────────────────────
    Command(
        "status", ("policy", "status"), INSPECT, SAFE, 1,
        ("Committee status", "委員会の状態"),
        ("Per-committee state: tracked flag, priority, latest meeting, pending counts.",
         "委員会ごとの状態（追跡・優先度・最新会合・未処理件数）。"),
        ("A quick read on where the backlog is.", "未処理の状況を素早く確認できます。"),
    ),
    Command(
        "doctor", ("policy", "doctor"), INSPECT, SAFE, 2,
        ("Diagnose fetch failures", "取得失敗を診断"),
        ("Explains why committees failed to fetch (WAF challenge, block, moved page…) and what to do.",
         "委員会ページの取得に失敗した理由（WAF・ブロック・移転など）と対処を説明します。"),
        ("Run when detect or materials finds less than expected.", "detectや資料取得の結果が少ないときに実行します。"),
        (Param("failing_only", "bool", "--failing-only", ("Failing only", "失敗のみ"), default=True, off_flag="--all"),
         Param("history", "bool", "--history", ("Show recent attempts", "直近の試行を表示"), default=False)),
    ),
    Command(
        "coverage", ("policy", "coverage"), INSPECT, SAFE, 3,
        ("Topic coverage", "トピックの網羅度"),
        ("How much each committee covers each topic (0–100%), the numbers behind the topic ranking.",
         "各委員会が各トピックをどの程度扱っているか（0〜100%）。トピック順位の元の数値です。"),
        ("Read-only.", "読み取り専用。"),
        (_COMMITTEE_OPT,),
    ),
    Command(
        "tags", ("policy", "tags"), INSPECT, SAFE, 4,
        ("List topic tags", "トピックタグ一覧"),
        ("Lists the topic-tag vocabulary.", "トピックタグの語彙を一覧表示します。"),
        ("Read-only.", "読み取り専用。"),
    ),
    Command(
        "notebooks", ("policy", "notebooks"), INSPECT, SAFE, 5,
        ("Audit NotebookLM notebooks", "NotebookLMノートブック監査"),
        ("Compares the NotebookLM account against the database and lists notebooks nothing refers to.",
         "NotebookLMアカウントとDBを突き合わせ、どこからも参照されていないノートブックを一覧表示します。"),
        ("Read-only; it never deletes. Needs a NotebookLM login.", "読み取り専用で削除は行いません。NotebookLMのログインが必要。"),
        needs_notebooklm=True,
    ),
    Command(
        "check-freshness", ("check-freshness",), INSPECT, SAFE, 6,
        ("Check data freshness", "データの鮮度を確認"),
        ("Fails if any market-data source has fallen behind its limit.",
         "市場データのいずれかが許容の遅れを超えていないか確認します（超過時は失敗）。"),
        ("The daily run's outage alarm; handy after a pull.", "日次実行の障害検知と同じ確認です。pullの後に便利です。"),
    ),
    Command(
        "cache-status", ("cache", "status"), INSPECT, SAFE, 7,
        ("HTTP cache status", "HTTPキャッシュの状態"),
        ("Per-host cache entries, last success and failures — which hosts are still answering.",
         "ホストごとのキャッシュ件数・最終成功・失敗数。どのホストが応答しているか分かります。"),
        ("Useful when diagnosing WAF blocks.", "WAFによるブロックの調査に役立ちます。"),
    ),
    # ── Automated: already run by the daily GitHub Actions ───────────────────────
    Command(
        "scrape", ("scrape",), AUTOMATED, WRITES, 1,
        ("Scrape market data", "市場データを取得"),
        ("Re-fetches recent TSO area data, JEPX spot, fuels, news and EPRX.",
         "直近のTSOエリアデータ・JEPXスポット・燃料・ニュース・EPRXを再取得します。"),
        ("The daily cron does this. Run by hand only to catch up after an outage.",
         "日次cronで実行されます。障害後の追い上げにのみ手動で使います。"),
        (Param("months_back", "int", "--months-back", ("Months back", "遡る月数"), default=1, lo=1, hi=12),),
        timeout_s=1800,
    ),
    Command(
        "schedule", ("policy", "schedule"), AUTOMATED, WRITES, 2,
        ("Refresh upcoming meetings", "今後の会合を更新"),
        ("Refreshes upcoming meetings from the METI calendar.", "METIのカレンダーから今後の会合を更新します。"),
        ("Part of the catch-up; safe if the feed is down.", "差分取得に含まれます。フィード停止時も安全です。"),
    ),
    Command(
        "discover", ("policy", "discover"), AUTOMATED, WRITES, 3,
        ("Discover committees", "委員会を発見"),
        ("Looks for committees we do not track yet.", "未追跡の新しい委員会を探します。"),
        ("Part of the catch-up.", "差分取得に含まれます。"),
    ),
    Command(
        "crosscheck", ("policy", "crosscheck"), AUTOMATED, SAFE, 4,
        ("Cross-check the energy board", "エネルギー庁フィードと照合"),
        ("Lists committees the energy-board feed has that we do not.",
         "エネルギー庁のフィードにあって当方に無い委員会を一覧表示します。"),
        ("Never posts a notification from here.", "ここからは通知を送信しません。"),
    ),
    Command(
        "digest", ("policy", "digest"), AUTOMATED, SAFE, 5,
        ("Preview the weekly digest", "週次ダイジェストをプレビュー"),
        ("Assembles the digest of recently summarised meetings, as a dry run.",
         "最近要約された会合のダイジェストを、ドライランで作成します。"),
        ("Always a dry run from here — it never posts to the webhook.", "ここからは常にドライランで、Webhookには送信しません。"),
        (Param("since_days", "int", "--since-days", ("Days", "日数"), default=7, lo=1, hi=90),),
        fixed=("--dry-run",),
    ),
    Command(
        "cache-prune", ("cache", "prune"), AUTOMATED, WRITES, 6,
        ("Prune the HTTP cache", "HTTPキャッシュを整理"),
        ("Evicts stale cache entries so the synced database stops growing.",
         "古いキャッシュを削除し、同期されるDBの肥大化を防ぎます。"),
        ("The daily run does this. Safe: a missing entry only costs one re-fetch. Dry run by default.",
         "日次実行でも行われます。安全（削除しても再取得が1回増えるだけ）。既定はドライラン。"),
        (Param("days", "int", "--days", ("Older than (days)", "経過日数"), default=90, lo=1, hi=3650),
         Param("dry_run", "bool", "--dry-run", ("Dry run", "ドライラン"), default=True)),
    ),
)

BY_ID: dict[str, Command] = {c.id: c for c in COMMANDS}
assert len(BY_ID) == len(COMMANDS), "duplicate command id"


@dataclass(frozen=True)
class Recipe:
    """An ordered flow through the commands, with the reason for the order."""

    id: str
    title: Bilingual
    summary: Bilingual
    steps: tuple[str, ...]
    optional: tuple[str, ...] = ()  # steps that can be skipped, e.g. a pull from a copy that is already fresh


RECIPES: tuple[Recipe, ...] = (
    Recipe(
        "backflow", ("Backflow — full", "遡及 — フル"),
        ("Pull, find what is missing, summarise it, resolve citations, then push. Pull first and push last: both "
         "overwrite a whole database and the daily runs write to the same one.",
         "pull → 不足の検出 → 要約 → 引用解決 → push。pullは最初、pushは最後。どちらもDB全体を上書きし、日次実行も同じDBに書き込むためです。"),
        ("pull-hf", "detect", "dates", "materials", "auth", "login", "backfill", "resume", "run",
         "resolve-citations", "tag", "export-web", "push-hf"),
        optional=("auth", "login", "resume", "run", "tag", "export-web"),
    ),
    Recipe(
        "citations", ("Citations only", "引用の解決のみ"),
        ("Resolve citation pages and push. Pull first unless this copy was pulled recently — a push from a stale "
         "copy overwrites what the daily runs added since.",
         "引用ページを解決してpush。このコピーが最近pull済みでなければ先にpullしてください。古いコピーのpushは、その後の日次実行の更新を上書きします。"),
        ("pull-hf", "resolve-citations", "push-hf"),
        optional=("pull-hf",),
    ),
)


# ── Argument validation → argv ────────────────────────────────────────────────
def _int(p: Param, raw: Any) -> int | None:
    if raw is None or raw == "":
        raw = p.default
    if raw is None or raw == "":
        if p.required:
            raise ValueError(f"{p.name} is required")
        return None
    try:
        return max(p.lo, min(p.hi, int(raw)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{p.name} must be an integer") from exc


def build_argv(cmd_id: str, params: dict, known_committees: Callable[[], set[str]]) -> list[str]:
    """Validate a UI request into a safe CLI argv (allowlist; no shell).

    ``known_committees`` is called only when a committee key needs checking. Numbers are
    clamped to the parameter's range, choices must be listed, and a parameter the command
    does not declare is ignored — so a request can name only what the registry allows.
    """
    cmd = BY_ID.get(cmd_id)
    if cmd is None:
        raise ValueError(f"unsupported command: {cmd_id}")

    # A single-meeting run (the Manage modal's ▶) targets exactly one meeting of one real
    # committee and nothing else — the CLI forces its own budget of 1.
    if cmd.id == "run" and params.get("meeting") not in (None, ""):
        spec = next(p for p in cmd.params if p.name == "meeting")
        committee = next(p for p in cmd.params if p.kind == "committee")
        key = _committee(committee, params.get("committee"), known_committees, required=True)
        number = _int(replace(spec, required=True), params.get("meeting"))
        return [*cmd.argv, "--committee", str(key), "--meeting", str(number)]

    argv = [*cmd.argv]
    for p in cmd.params:
        if p.name == "meeting":
            continue  # only meaningful in the single-meeting form above
        if p.kind == "committee":
            key = _committee(p, params.get(p.name), known_committees)
            if key is not None:
                argv += [p.flag, key]
        elif p.kind == "int":
            n = _int(p, params.get(p.name))
            if n is not None:
                argv += [p.flag, str(n)]
        elif p.kind == "bool":
            on = bool(params.get(p.name, p.default))
            if on:
                argv.append(p.flag)
            elif p.off_flag:
                argv.append(p.off_flag)
        elif p.kind == "choice":
            val = params.get(p.name) or p.default
            if val not in p.choices:
                raise ValueError(f"{p.name} must be one of {', '.join(p.choices)}")
            argv += [p.flag, str(val)]
        else:  # pragma: no cover - a registry typo, caught by tests
            raise ValueError(f"unknown parameter kind: {p.kind}")
    return [*argv, *cmd.fixed]


def _committee(p: Param, raw: Any, known: Callable[[], set[str]], *, required: bool = False) -> str | None:
    value = (raw or "").strip() if isinstance(raw, str) else ""
    if not value or value == "all":
        if required or p.required:
            raise ValueError("committee is required")
        return "all" if p.default == "all" else None
    if value not in known():
        raise ValueError(f"unknown committee: {value}")
    return value


def catalog() -> dict:
    """The registry as JSON for the web app (no CLI flags — the browser never builds argv)."""
    def param(p: Param) -> dict:
        d: dict[str, Any] = {"name": p.name, "kind": p.kind, "label": list(p.label), "required": p.required}
        if p.default is not None:
            d["default"] = p.default
        if p.kind == "int":
            d.update(lo=p.lo, hi=p.hi)
        if p.choices:
            d["choices"] = list(p.choices)
        return d

    return {
        "commands": [
            {
                "id": c.id, "group": c.group, "level": c.level, "order": c.order,
                "title": list(c.title), "summary": list(c.summary), "when": list(c.when),
                "params": [param(p) for p in c.params if p.ui],
                "needsNotebooklm": c.needs_notebooklm,
                "warning": list(c.warning) if c.warning else None,
                "cli": "repower " + " ".join(c.argv),
            }
            for c in COMMANDS
        ],
        "recipes": [
            {"id": r.id, "title": list(r.title), "summary": list(r.summary),
             "steps": list(r.steps), "optional": list(r.optional)}
            for r in RECIPES
        ],
    }


def timeout_for(cmd_id: str, default: int = 600) -> int:
    cmd = BY_ID.get(cmd_id)
    return cmd.timeout_s if cmd else default
