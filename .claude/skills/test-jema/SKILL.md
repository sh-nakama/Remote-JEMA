---
name: test-jema
description: Repeatable browser-driven bug hunt for the local JEMA web app. Spins up the backend (repower web-api :8787) + Vite frontend (:5173), then runs Sonnet test agents CONSECUTIVELY — each given a unique screen/feature to exercise via the built-in browser — that draft GitHub issues to test-runs/. Issues are NEVER filed automatically: the drafts go through a review gate and are only pushed with `gh issue create` after the user approves. Use when the user asks to "run test-jema", "bug hunt the JEMA app", "test the web app", or "draft issues from a testing pass".
---

# /test-jema — browser-driven bug hunt with a publish gate

Drives an end-to-end testing pass on the local JEMA web app. Sonnet subagents
exercise the app in the built-in browser, find bugs / UX problems, and **draft**
GitHub issues. Nothing is filed to GitHub until the user reviews and approves.

## Hard rules

1. **Consecutive, never concurrent.** There is exactly ONE browser pane per
   session. Two agents driving the browser at once corrupt each other's tabs and
   navigation. Spawn test agents **one at a time** (`run_in_background: false`),
   review each one's output, then spawn the next. This is not a performance knob —
   parallel browser agents produce garbage.
2. **Agents draft; they never publish.** Test agents write issue drafts to files
   only. They are explicitly told NOT to run `gh`, `git push`, or any network/
   write command. Filing to GitHub happens only in the review gate below, run by
   the main agent, after explicit user approval.
3. **No Aurora branding** anywhere in drafts or issues (see CLAUDE.md).

## Step 1 — Start the backend (API on :8787)

The frontend's `/api/*` calls (Policy Deep Dive interactive mode, catch-up, manage
writes) proxy to the local `repower web-api`. Start it as a background process
(it's an API, not a browsable page) and confirm health before touching the UI:

```bash
cd "C:/Users/SehunNakama/Projects/Remote Energy Market Status" && ./.venv/Scripts/python.exe -m repower.cli web-api
```

Run that with the **Bash tool + `run_in_background: true`**. Then poll health
(retry — the server needs a moment):

```bash
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/api/health 2>/dev/null)
  [ "$code" = "200" ] && { echo "backend up:"; curl -s http://127.0.0.1:8787/api/health; exit 0; }
  sleep 1
done
echo "BACKEND NOT UP (last=$code)"
```

Expect `{"ok": true, "mode": "local"}`. If it never comes up, check the background
task output and the venv (`.venv` is Python 3.12; the PATH `python` is 3.9 without
deps — see the python-venv-3-12 memory). Do not start test agents without a
healthy backend, or Policy Deep Dive tests will report false positives.

## Step 2 — Start the frontend (Vite on :5173)

```
preview_start { name: "jema-web" }
```

Requires the `jema-web` entry in `.claude/launch.json` (gitignored / machine-local;
runtimeArgs `["--prefix","web","run","dev"]`, port 5173). If it's missing, recreate
it before proceeding. Capture the returned `tabId`. Do a `read_page` and confirm
the app mounted (header "JEMA — Japan Energy Market Analytics"); an immediate read
right after start can return an empty 0×0 page before the SPA mounts — read again.

## Step 3 — Create the run folder

```bash
RUN=$(date +%Y%m%d-%H%M%S); mkdir -p "test-runs/$RUN"; echo "$RUN"
```

`test-runs/` is gitignored. Each test agent writes its drafts into `test-runs/$RUN/`.

## Step 4 — Run test agents CONSECUTIVELY

The app has four screens (nav order): **Market Overview, Market Data, Capacity &
Auctions, Policy Deep Dive** (+ Watchlist, Notifications, Settings). Give each agent
a **unique, non-overlapping** slice so findings don't collide. Suggested split:

- `market-overview` — KPI tiles, intraday price chart, 9-area price table, Recent &
  Scheduled panel, METI Committee Radar, Data Freshness panel.
- `market-data` — area/date filters, tables, CSV export (download + contents), chart
  interactions, empty/edge states.
- `capacity-auctions` — auction results table, clearing-price-by-delivery-year chart,
  per-zone prices, any .ics/CSV export.
- `policy-deepdive` — committee radar, deep-dive drilldown, catalog cross-check, and
  the **interactive /api paths** (track/priority/catch-up) now that the backend is up.
  Watch both browser console AND backend logs (`preview_logs` / the bg task output).

Spawn each with the **Agent tool**, `subagent_type: "claude"` (or `general-purpose`),
`model: "sonnet"`, `run_in_background: false`. Use the prompt template in
`agent-prompt.md` (same directory), substituting the screen, its checklist, the
browser `tabId`, and the run folder. After each agent returns:

- Read the drafts it wrote under `test-runs/$RUN/`.
- Sanity-check each finding against the source (a claimed bug that the code
  contradicts is a false positive — drop it or downgrade to a question).
- Note it, then spawn the next agent. Do NOT batch them.

Scale to the request: "quick smoke test" → 1–2 agents; "thorough" → all four, and
optionally a second pass with adversarial/edge-case tasks.

### Known tooling gotchas (observed — tell each agent)

- **`computer` clicks/screenshots are unreliable on this React SPA.** Across runs,
  `computer` `left_click` often didn't register and `screenshot`/`zoom` timed out.
  Agents should fall back to `javascript_tool` (invoke the element's React `onClick`,
  read `getComputedStyle`/`document.querySelectorAll`, `fetch()` the data JSON) and
  cross-check state via `read_page` + `read_network_requests`. Put this in the agent
  prompt so it doesn't burn tool calls rediscovering it.
- **`getComputedStyle`/DOM-diff findings are false-positive-prone.** Two "control X
  is wired to the wrong series / active-state is stuck" findings turned out to be
  measurement artifacts (a *segmented view-selector* mistaken for broken toggles; a
  pill "desync" contradicted by complete `useMemo` deps). In the gate, ALWAYS
  code-verify any "this control is wired wrong / stuck / dead" claim against the
  component's state + `useMemo` dependency array before filing.
- **`/api/health` returns 500 for a beat at startup** until the backend binds, then
  200. The app correctly gates its `interactive` flag on it — not a bug.

### Draft file format (one issue per file)

Agents write one file per issue: `test-runs/$RUN/<screen>-NN.md`.
- **Line 1** = the issue title (plain text, no leading `#`).
- **Line 2** = blank.
- **Rest** = body, with `## Steps to reproduce`, `## Expected`, `## Actual`,
  `## Severity` (blocker/major/minor/cosmetic), `## Notes` (env: screen, viewport,
  Vite version; and whether it reproduced in browser console vs. backend logs).

This split lets the gate file each as `gh issue create --title <line1> --body-file <rest>`.

## Step 5 — Review gate (main agent; user approval REQUIRED before filing)

Filing a GitHub issue is publishing to a public repo — it needs explicit per-batch
user approval. Do this in the main session, never inside a test agent:

1. Collect every draft under `test-runs/$RUN/`. **Deduplicate** across agents
   (different screens often surface the same root cause) and drop verified false
   positives.
2. Present the surviving drafts to the user as a numbered list: title, severity,
   one-line summary, source file path. Recommend which to file / merge / skip.
3. Ask the user which to file (all / a subset / none). **Wait for a clear answer.**
4. For each approved draft, confirm the repo, then:

   ```bash
   gh issue create --repo sh-nakama/Remote-JEMA \
     --title "$(head -1 test-runs/$RUN/<file>.md)" \
     --body-file <(tail -n +3 test-runs/$RUN/<file>.md)
   ```

   Add `--label bug` / `--label ux` only if those labels already exist in the repo
   (`gh label list`); otherwise omit — a nonexistent label makes the call fail.
5. Report the created issue URLs back to the user.

Never file issues the user didn't approve. If the user says "draft only, don't
file", stop after step 2 and leave the drafts in `test-runs/$RUN/` for later.

## Cleanup

Leave the backend + frontend running if the user may iterate. When done, stop the
frontend with `preview_stop` (serverId from `preview_list`) and kill the backend
background task. `test-runs/` can be left in place (gitignored) or cleared.
