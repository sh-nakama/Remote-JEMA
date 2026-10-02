# JEMA User Guide

> **Purpose.** This is the source-of-truth reference for how JEMA works, screen by
> screen and workflow by workflow. It is written so that (a) a new user can learn
> the tool, and (b) the in-app **"i" info guide** can be kept accurate and simple.
>
> **Relationship to the in-app guide.** The "i" icon on the Policy Deep Dive top
> bar opens a *simplified* version of the "Policy Deep Dive" section below. That
> panel is authored in [`web/src/lib/menus.tsx`](../web/src/lib/menus.tsx) as the
> `GuidePanel` component (a bilingual `GUIDE` data array). **When a policy workflow
> changes, update this document first, then mirror the short version into
> `GuidePanel`.**

---

## Contents

- [Orientation](#orientation)
- [Policy Deep Dive](#policy-deep-dive) — the main subject of this guide
  - [What it is](#what-it-is)
  - [Layout](#layout)
  - [Core concepts](#core-concepts)
  - [Everyday workflows](#everyday-workflows)
  - [Behind the scenes: the data pipeline](#behind-the-scenes-the-data-pipeline)
  - [CLI reference](#cli-reference)
  - [Known constraints & troubleshooting](#known-constraints--troubleshooting)
- [Other screens (brief)](#other-screens-brief)
- [Maintaining this guide](#maintaining-this-guide)

---

## Orientation

**JEMA — Japan Energy Market Analytics** is a scraper + dashboard for the Japanese
power market. Data is scraped into a local **SQLite** database, synced to a private
**Hugging Face dataset**, and refreshed by a **daily GitHub Actions cron**. The
React frontend (`web/`) reads that data — either **live** from a local backend
(`repower web-api`) when you run it yourself, or from **static snapshots** on the
read-only public deployment.

There are four screens, switched from the left nav rail:

| Screen | What it covers |
| --- | --- |
| **Market Overview** | Cross-market landing page: headline prices, mix, and status. |
| **Market Data** | Wholesale (JEPX day-ahead spot) + supply/demand per TSO area, with time-range and granularity controls. |
| **Capacity & Auctions** | Capacity market / auction results. |
| **Policy Deep Dive** | Government policy committees (METI/OCCTO/EGC): meetings, materials, AI briefings & digests. **This guide focuses here.** |

Shared chrome on every screen: a **⌘K search** palette, a **theme** toggle
(light/dark), a **language** toggle (English / 日本語), a **Watchlist**, and a
**Settings** panel. Preferences are saved in the browser (localStorage).

---

## Policy Deep Dive

### What it is

The Policy Deep Dive tracks Japanese energy-policy **committees** (審議会・検討会)
run by METI, OCCTO, and EGC. For each committee it collects every **meeting**
(第N回), the **source materials** published for that meeting (agenda, minutes,
handouts), and — for tracked committees — an AI-generated **briefing** and
bilingual **digest** of what was discussed, plus a rolling committee-level
**synthesis**.

### Layout

Three panes under a top bar:

1. **Committee Explorer (left).** The full catalog of committees — both the ones
   you **track** and ones the tool **discovered** but you don't track yet (shown
   with an *UNTRACKED / 未追跡* tag). Includes a name search, a "recommended to
   follow" ranking, and per-committee **follow** toggles.
2. **Meeting Feed (center).** A reverse-chronological feed of meetings as cards.
   Each card shows the committee, meeting number, date, source org, a status, and
   a one-line summary. Above the feed: a **search** box, **date filters**, a
   **Topic** filter (see [Topic tags](#topic-tags)), a **Tracked / All** coverage
   toggle, and a **Followed-only** toggle.
3. **Detail pane (right).** Selecting a **committee** shows its high-level
   **synthesis** (the running document). Selecting a **meeting** shows that
   session's **digest** — themed sections in English and Japanese — plus its
   **source documents** and citations.

The top bar has the bilingual title, the ⌘K search box, the **"i" info guide**
(this guide), the theme toggle, notifications, and the language toggle.

### Core concepts

**Committee — tracked vs. discovered/untracked.**
- *Tracked* committees are the ones you care about; **tracking gates
  summarisation** — only tracked committees get AI briefings/digests generated.
- *Discovered/untracked* committees are ones the tool found (via discovery or the
  energy-board cross-check) but you haven't opted into. Their **meetings are still
  detected and visible**, they just aren't summarised until you track them.

**Follow vs. Track — they are different.**
- **Follow** is a *client-side* preference stored in your browser. It only drives
  the **Followed** filter and personal highlighting. It does **not** change what
  the backend does.
- **Track** is a *server-side* setting. It adds the committee to the catch-up and
  the summarisation worklist. Toggle it from the **Manage committees** modal.

**Meeting status (lifecycle).**

| Status | Meaning |
| --- | --- |
| **detected / pending** | The meeting is known and has materials, but no AI digest yet — it's queued for summarisation. |
| **downloading / ingesting / generating** | Mid-flight through the summarisation pipeline. A run that crashed leaves meetings parked here; **Resume** drains them. The feed shows these as *pending*; the Manage → **Status** view shows the real stage. |
| **done** | Summarised: it has a briefing + bilingual digest, and it feeds the committee synthesis. |
| **error** | Summarisation failed; it's retried up to a cap, then dropped from the worklist. The reason is recorded per meeting and shown in the Manage → **Status** view. |

> A meeting with **zero materials** is hidden from the feed (there's nothing to
> show yet). Materials are what make a detected meeting appear. See
> [self-heal](#self-heal-material-backfill) below.

**Materials (source documents).** The PDFs published for a meeting, classified by
kind: **議事次第** (agenda), **議事録** (minutes), **資料** (handouts), and
**とりまとめ** (torimatome / summary reports). Citations in a digest deep-link back
to the source PDF.

**Topic tags.** What a committee or meeting is *about* — see [Topic tags](#topic-tags).

**Digest & briefing.** The AI output for a summarised meeting: a *briefing*
(the raw structured markdown) rendered as a bilingual *digest* of themed sections.

**Synthesis (running document).** A rolling, committee-level narrative assembled
from that committee's `done` meetings — the "where this committee is now" view
shown when you select a committee (rather than a single meeting).

**Upcoming meetings.** Scheduled future meetings pulled from the METI committee
calendar. This list is **empty whenever the METI calendar feed is down** (see
[constraints](#known-constraints--troubleshooting)).

### Everyday workflows

**Find a committee.** Type in the Explorer's search box. Untracked/discovered
committees appear inline with a dashed *UNTRACKED* tag. The *recommended* list
surfaces high-priority committees you already track.

**Read a meeting.** Click a meeting card in the feed. The detail pane shows the
digest sections (EN + JA), the source documents, and citations. Click a citation
or document to open the original METI/OCCTO PDF.

**Follow / unfollow.** Use the follow toggle on a committee (or the ⌘K palette).
This is a personal filter only.

**Track / untrack.** Open **Manage committees** (the Manage button, or the
committee "gear"). Toggling *Track* here changes what the backend summarises; the
screen behind refetches so the change is reflected immediately.

**See what the pipeline actually did (Status view).** Manage has two views,
switched from the toggle in its header:

- **Cards** — the three-org grid. This is where you *manage the tracked set*.
- **Status** — a table, one row per committee, **tracked first and most recently
  updated first**. It answers the questions the cards can't: what did the pipeline
  last do here (which meeting, what state), how long ago, how many meetings are
  summarised / pending / errored, and whether the committee's pages could be
  fetched at all. Click any row to expand it into that committee's individual
  meetings — each with its raw lifecycle state, **the message it failed with**, its
  document count and when it was last written.

Two independent kinds of failure show up there, and it's worth keeping them apart:
the **Fetch** column is whether we could *reach* the committee's pages (`blocked_403`,
`circuit_open`, `not_found`…, same diagnosis as `repower policy doctor`), while the
**error** count and the per-meeting rows are whether we could *summarise* what we
fetched. A committee can be perfectly fetchable with every meeting failing, or
unreachable with a clean summarisation record. Use the **Needs attention** filter to
see only committees with either problem.

> A meeting's failure message is recorded from the moment it fails, so meetings
> that errored before this was added show only their coarse reason (e.g.
> *download blocked*) with no message. Expanding a committee lists its most recent
> ~20 meetings plus **every** errored or mid-flight one; a footer says how many
> quiet pending meetings were left out.

**Check for updates (catch-up).** The **Check for updates** button (in Manage) —
or the catch-up action — starts the auth-free refresh job. Progress is shown in
the **progress panel** (bottom-left) with one line per stage. See
[the pipeline](#behind-the-scenes-the-data-pipeline) for what each stage does.
*(This button only appears when a local `repower web-api` is running — the public
deployment is read-only.)*

**Add a committee by URL.** In Manage, paste a METI `/shingikai/…` committee page
URL. The backend fetches the committee name and auto-tracks it. This is the escape
hatch for committees the org indexes don't list.

**Generate a summary for one meeting.** For a pending meeting, the *Generate
summary* action flags it so the summarisation pipeline processes it first on the
next run (user-requested meetings jump the queue).

**Summarise one meeting (Run now / Latest / Queue).** From Manage → **Status**:

- **LATEST** on a committee row summarises that committee's *newest pending meeting
  and stops*. This is the "just bring this one committee up to date" button.
- **▶ Run now** on an individual meeting (expand a row) summarises exactly that
  meeting, bypassing the queue. It also works on an already-summarised meeting —
  that is the repair path when a briefing was written from an incomplete source set;
  the corrected briefing is folded back into the committee synthesis.
- **↑ Queue** on an individual meeting moves it to the *front* of the summarisation
  queue without re-prioritising its whole committee. Queued meetings outrank
  committee priority and everything else, and the flag clears once the meeting has
  been processed. CLI equivalent: `repower policy queue --committee <key> --meeting N`.

**Why a meeting can stay pending after a run (all-or-nothing sources).** A meeting is
summarised only when **every** selected document downloads and reaches NotebookLM. If
any is missing, the meeting is left alone rather than summarised from what arrived —
a briefing written from a subset reads exactly like a complete one, and the case that
forced this rule produced a fluent summary of nothing but a table of contents. A host
that blocked us leaves the meeting **pending** with no retry burned (try again on a
calm day); a document that is genuinely gone (404) counts a retry and the meeting
eventually drops off the worklist.

The **DOCS IN** column shows `ingested/total` per meeting. A summarised meeting
reading `0/13` or `3/12` was written before this rule and did **not** see all its
papers — use ▶ Run now to redo it.

**Large meetings are fetched slowly, and progress is kept.** A meeting's documents are
requested further apart the more of them there are (a 12-document meeting takes ~2
minutes to fetch), because the source sites challenge rapid bursts. If a fetch is
blocked partway, the documents already downloaded are **kept** — the next attempt only
asks for the missing ones, so a large meeting completes over a couple of passes instead
of restarting from zero each time. When a host does turn us away, the remaining
documents aren't requested at all: those requests can't succeed and only push the host
into a 5-minute block that would stall every other committee on it.

**A blocked host no longer eats the run.** If a source host's circuit breaker is open,
its committees are skipped without a request (they stay pending) and committees on
other hosts keep going, so a METI outage no longer stops OCCTO and EGC work. The run
reports `skipped=N` with a line per host.

**Summarise all vs. Resume.** The **Summarise ⚿** controls in Manage both run the
summarisation pipeline and both need NotebookLM auth (`notebooklm login`), but they
target different work:

- **Summarise all** starts *new* work — it summarises **pending** (not-yet-done)
  meetings **breadth-first** (the newest pending meeting of each tracked committee,
  in priority order, rather than draining one committee's backlog), capped at **8
  meetings** per run as a rate/cost guard, then refreshes each touched committee's
  synthesis.
- **Resume** only drains meetings left **mid-flight** — stuck in `downloading` /
  `ingesting` / `generating` after a previous run crashed, was interrupted, or hit a
  rate limit. Because the pipeline commits each state transition *before* the next
  network call, Resume picks up exactly where it left off instead of restarting a
  meeting. If nothing is stuck partway, Resume has nothing to do.

Rule of thumb: **Summarise all** to make forward progress on the backlog; **Resume**
to finish an interrupted or rate-limited run before starting more.

**Search.** The feed search covers meeting titles, committees, briefings, and
digests — including untracked committees. (Full-text search inside the source PDFs
is proposed, not yet enabled.)

**Filter.** Combine the **Tracked / All** coverage toggle, the **date** filter
(all / 30d / 90d / year / upcoming), and **Followed-only** to narrow the feed. The
coverage toggle filters by *committee*: `All` shows every committee's meetings;
`Tracked` hides untracked committees' meetings from the combined feed (selecting a
specific committee still shows its meetings either way).

### Behind the scenes: the data pipeline

Everything above is fed by two backend flows: **catch-up** (find & fetch) and
**summarisation** (understand & write).

#### Catch-up job — ordered stages

Triggered by *Check for updates* (`POST /api/policy/catchup`), the job
(`_run_catchup_job` in [`web_api.py`](../src/repower/web_api.py)) runs these stages
in order, reporting live progress to the panel:

1. **detect** — scan **every** catalog committee (tracked *and* discovered) for new
   meetings (第N回). Each new meeting is recorded as `state="detected"`. Materials
   are enumerated only for genuinely *new* meetings (newest few).
2. **materials** — *self-heal.* Fetch materials for meetings that were detected
   **without any** (e.g. first seen while a committee page was temporarily down).
   Bounded to a handful per committee per run so it fills in incrementally.
3. **dates** — backfill missing meeting dates.
4. **schedule** — refresh **upcoming** meetings from the METI calendar. This stage
   is best-effort: if the feed is down it's marked unavailable but the job still
   completes (and the existing upcoming list is **not** wiped).
5. **discover** — find new **committees** you don't track yet (METI/OCCTO/EGC
   indexes plus the energy-board cross-check backup feed).

> **Detection is decoupled from tracking.** `detect` and `discover` scan the whole
> catalog; `tracked` only decides what gets *summarised*. So you always see new
> meetings/committees even for things you don't track.

<a id="self-heal-material-backfill"></a>
**Why the "materials" stage exists (self-heal).** `detect` only enumerates
materials for brand-new meetings. A meeting first recorded while its committee
page was unreachable ends up with **zero materials** and is therefore **hidden**
from the feed. The `materials` stage re-fetches such meetings and records whatever
is now published, so tracked committees stop showing "no meetings." Because the
source site throttles rapid requests, this heals **incrementally** across runs (see
constraints). For a full one-committee backfill, use the CLI:
`repower policy materials --committee <key> --limit 0`.

#### Summarisation pipeline (NotebookLM)

Separate from catch-up, the summarisation run (`repower policy run`) processes the
worklist of **pending, tracked** meetings:

1. Take pending meetings (user-requested "Generate summary" ones first).
2. Generate a **briefing** (structured markdown) from the meeting's materials.
3. Render the bilingual **digest** sections and mark the meeting **done**.
4. Fold the new briefing into the committee-level **synthesis** (running doc).

On the hosted setup this runs on the **daily 06:10 JST** cron; locally you can run
it on demand.

#### Data source & sync

The frontend's interactive mode calls `GET /api/policy/deepdive`, which builds the
snapshot **live from the SQLite DB** (`build_policy_snapshot`). The read-only
deployment instead reads static `policy/committees.json` + `policy/meetings.json`
exported by `repower export-web`. The DB itself is synced to a private HF dataset
and refreshed by the daily cron.

### Topic tags

Tags slice the Deep Dive by subject instead of by committee — useful because one
committee often touches several subjects, and one subject (offshore wind) is spread
over several committees. The first pass covers **renewable technology and grid
infrastructure**:

| Group | Tags |
| --- | --- |
| 発電 Generation | 事業用太陽光 · 屋根置き・住宅用太陽光 · 次世代太陽電池 · 洋上風力 · 陸上風力 · 水力・地熱 · バイオマス |
| 蓄電・調整力 Storage & flexibility | 系統用蓄電池 · 揚水・長期貯蔵 · 分散リソース・VPP・DR |
| 系統設備 Grid infrastructure | 広域系統整備・直流送電 · 系統接続・ノンファーム · 出力制御・混雑管理 · 託送料金・費用負担 · 配電・レジリエンス |
| 支援制度 Support schemes | FIT/FIP・調達価格 · 長期脱炭素電源オークション |
| その他の脱炭素電源 Other low-carbon | 水素・アンモニア · 原子力 |

**Using it.** The **Topic ▾** chip in the filter bar is multi-select and matches *any*
of the chosen topics. It narrows the meeting feed, the *newly summarised* banner,
upcoming meetings and the committee explorer together. Tag pills appear on feed cards
and in both detail headers; clicking one in a detail header toggles that topic. The
dropdown's counts are meetings per topic. The chip is hidden when the export carries
no tag vocabulary (a snapshot older than this feature).

**Committee tags vs. meeting tags.** They are different things and do not inherit:

- A **committee's tags** are its *standing mandate*. Where the mandate is
  unambiguous they are curated in `policy/committees.py`; otherwise they come from
  the committee's name plus any topic that recurs across its meetings (at least two
  meetings and a fifth of those with content). A committee also appears under a topic
  if any of its meetings carries it.
- A **meeting's tags** are what *that meeting* discussed — so a broad committee's
  offshore-wind-only meeting is filed under 洋上風力 alone, not under everything the
  committee ever covers. An upcoming (not-yet-held) meeting shows its committee's tags,
  since there is nothing else to go on.

**How a meeting gets tagged (daily).** Two stages, both automatic:

1. **Rules, the same day it is detected.** Keyword rules over the meeting's document
   titles (a title hit is enough) and, once summarised, its Japanese briefing (a topic
   needs repeated mention — a passing line about 太陽光 is not a topic). DB-only: no
   NotebookLM, no network, so it runs in `run-all`, `policy detect`, `policy run` and
   the web catch-up, and re-evaluates as documents and briefings arrive.
2. **NotebookLM check at summarisation.** While a meeting's notebook exists, one extra
   question classifies it against the closed vocabulary and its answer replaces the
   rule tags. If that fails (rate limit, unusable answer) the rule tags stand.

A tag set records who decided it, and a higher source is never overwritten by a lower
one: **manual > curated config / NotebookLM > rules.**

**Reviewing and correcting tags (CLI).**

```bash
repower policy tags                      # the vocabulary (keys, JA / EN labels)
repower policy tag                       # DRY RUN: what the rules would change
repower policy tag --apply               # write it (the daily run does this itself)
repower policy tag --committee yojo_fuuryoku --scope meetings
repower policy tag-set <committee> wind_offshore grid_planning   # pin a committee's tags
repower policy tag-set <committee> --meeting 12 storage_grid     # pin one meeting's tags
repower policy tag-set <committee> --none          # pin "no topic"
repower policy tag-set <committee> --auto          # drop the pin; rules own it again
```

Meetings that were summarised before this feature get **rule tags only** (their
notebooks are deleted after summarisation, so there is nothing left to ask). Re-run a
meeting with `repower policy run --committee <key> --meeting <N>` to get a NotebookLM
classification for it. The tags live in the DB, so a backfill reaches production through
the Hugging Face dataset push, not git.

### CLI reference

Run with the installed console script (`repower …`) from the project root:

| Command | What it does |
| --- | --- |
| `repower policy detect` | Detect new meetings across all committees. |
| `repower policy discover` | Discover new committees (incl. energy-board backup). |
| `repower policy crosscheck` | Show committees the energy-board feed has that we don't. |
| `repower policy schedule` | Refresh upcoming meetings from the METI calendar (safe if feed is down). |
| `repower policy materials --committee <key\|all> --limit <n>` | Backfill materials for meetings detected without any. `--limit 0` = unbounded (full heal); omit/`all` = every committee. |
| `repower policy run` | Run the summarisation pipeline over pending tracked meetings. |
| `repower policy run --committee <key> --meeting <N>` | Summarise exactly that one meeting, bypassing the queue. Works on an already-summarised meeting (re-run / repair). |
| `repower policy run --committee <key> --max-per-run 1` | "Latest only": the newest pending meeting of one committee, then stop. |
| `repower policy queue --committee <key> --meeting <N>` | Move one meeting to the front of the summarisation queue (`--clear` to take it off). |
| `repower policy tags` / `tag` / `tag-set` | List the topic-tag vocabulary; apply rule-based tags (dry run unless `--apply`); pin tags by hand. See [Topic tags](#topic-tags). |
| `repower policy doctor` | Explain why committees failed to fetch (blocked, WAF challenge, moved page …) and what to do about each. Add `--all` to include healthy ones, `--history` for recent attempts. |
| `repower export-web` | Rebuild the static JSON snapshots the read-only site serves. |
| `repower web-api` | Start the local backend that powers the interactive frontend. |

### Known constraints & troubleshooting

- **A committee looks stuck / hasn't updated in ages.** Run `repower policy doctor`.
  Each detection pass now records per committee whether its pages could be fetched
  and, if not, why — so a blocked committee is distinguishable from a quiet one.
  The Deep Dive Committee Explorer shows the same thing as a **FETCH FAILED /
  取得失敗** badge (hover it for the cause and how long it has been failing).
  Note this is separate from the "errored" count next to a committee, which counts
  meetings whose *summarisation* failed rather than pages that could not be reached.
- **Upcoming list is empty.** The METI committee calendar sometimes serves an
  HTTP-200 "アクセスが集中" overload page instead of the calendar. The tool detects
  this and **skips** the schedule refresh without wiping existing data, so the
  upcoming list simply stays empty until the feed recovers. Re-run
  `repower policy schedule` (or catch-up) during a good window.
- **A tracked committee shows no meetings / materials heal slowly.** The source
  site (meti.go.jp) throttles bursts: after a few rapid requests it returns
  HTTP 202 and blocks the rest. Each meeting costs two requests, so one catch-up
  run only heals the newest few meetings per committee. Healing is **incremental** —
  spaced runs (the throttle resets between them) fill in the backlog. To force a
  single committee through, run `repower policy materials --committee <key>
  --limit 0` a few times, spaced apart.
- **Write controls are missing (Track / Check for updates).** Those require a local
  `repower web-api`. The public GitHub Pages deployment is read-only.
- **New catch-up stages/progress don't appear.** `repower web-api` is long-running;
  after backend edits it must be **restarted** to pick up new code.

---

## Other screens (brief)

- **Market Overview** — cross-market landing page: headline JEPX prices, the
  supply/demand mix, and overall status. The default screen (configurable in
  Settings).
- **Market Data** — wholesale spot prices and per-TSO-area supply/demand. Controls
  for area focus, time range, and **granularity** (Native / Daily / Weekly /
  Monthly). The ⌘K palette and Watchlist can ask this screen to focus a specific
  area.
- **Capacity & Auctions** — capacity market / auction results and their latest
  publication date.

All three share the same top-bar chrome (⌘K search, theme, language, Watchlist,
Settings) and read from the same synced dataset.

---

## Maintaining this guide

- **This document is the reference.** The in-app "i" guide is a *simplified* mirror
  of the [Policy Deep Dive](#policy-deep-dive) section, authored as the `GuidePanel`
  component's `GUIDE` array in
  [`web/src/lib/menus.tsx`](../web/src/lib/menus.tsx).
- **When a policy workflow changes:** update this document first, then update the
  short bilingual copy in `GuidePanel` so the two stay in sync.
- **Terminology must match the UI.** Use the same labels the buttons use (Follow,
  Track, Check for updates, Generate summary) so users can map guide → screen.
