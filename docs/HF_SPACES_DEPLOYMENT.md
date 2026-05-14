# HF Spaces Deployment Plan

Deploy the `repower` Streamlit dashboard to **Hugging Face Spaces** (free CPU tier, native Streamlit SDK), reading the SQLite database from a **private HF Dataset** that is updated by the existing GitHub Actions cron job.

## Architecture

```
GitHub Repo (nakama-s/repower-energy, code)
  .github/workflows/daily.yml  — cron 05:30 JST
        |
        v  push via HF_TOKEN
HF Dataset: nakama-s/repower-data  (PRIVATE)
  repower.db  <- pushed by `repower push-hf` after each daily cron run
        |
        v  pulled on Space cold-start + Refresh button
HF Space: nakama-s/repower  (PUBLIC, Streamlit SDK)
  app.py              <- entry: pulls DB, calls repower.dashboard.main()
  requirements.txt    <- pinned deps (streamlit provided by HF)
  src/repower/...     <- package source, synced from GitHub by sync-space.yml
  Secret: HF_TOKEN    <- read-only, scoped to nakama-s/repower-data
```

## Key decisions

| Item | Choice |
|---|---|
| HF username | `nakama-s` |
| Space repo | `nakama-s/repower` (public) |
| Dataset repo | `nakama-s/repower-data` (private, holds `repower.db`) |
| SDK | Streamlit (native) |
| DB refresh | Pull on Space cold-start + manual **Refresh** button in sidebar |
| Secrets | `HF_TOKEN` set as Space Secret, read-only fine-grained scope |

## Files created / modified

| File | Purpose |
|---|---|
| `space/README.md` | YAML frontmatter required by HF Spaces |
| `space/app.py` | Entry: cold-start DB pull + calls `repower.dashboard.main()` |
| `space/requirements.txt` | Pinned deps (streamlit provided by HF) |
| `space/packages.txt` | Empty (no apt packages needed) |
| `src/repower/dashboard.py` | Full dashboard logic, exposes `main(show_refresh)` |
| `dashboard/app.py` | Local dev shim — 3 lines |
| `src/repower/config.py` | DB path now CWD-relative (works when pip-installed) |
| `src/repower/hf_sync.py` | Removed deprecated `local_dir_use_symlinks` param |
| `.github/workflows/sync-space.yml` | Push code to HF Space on push to main |
| `.github/workflows/daily.yml` | Already has `push-hf` step — no change needed |

## One-time setup steps

1. **Create HF account** `nakama-s` at huggingface.co if not present.

2. **Generate two HF tokens:**
   - **Write token** (for CI and local use):
     - huggingface.co → Settings → Access Tokens → New token → Role: Write
     - Save as GitHub repo secret `HF_TOKEN`
   - **Read-only token** (for the Space — finer security):
     - Role: Read, scoped to `nakama-s/repower-data`
     - Save as HF Space secret `HF_TOKEN` (see step 5)

3. **Seed the dataset** (creates it automatically on first push):
   ```
   cp .env.example .env
   # fill in HF_TOKEN and HF_DATASET_REPO=nakama-s/repower-data
   python -m repower.cli run-all
   python -m repower.cli push-hf
   ```

4. **Create the Space** at huggingface.co:
   - New Space → Streamlit SDK → name `repower` → public → Create

5. **Add Space secrets** via Space Settings UI:
   - `HF_TOKEN` = read-only token from step 2
   - `HF_DATASET_REPO` = `nakama-s/repower-data`

6. **Add GitHub repo secrets:**
   - `HF_TOKEN` = write token from step 2
   - `HF_DATASET_REPO` = `nakama-s/repower-data`
   - `WEBHOOK_URL` = your Discord/Slack webhook

7. **Push to GitHub `main`** → `sync-space.yml` fires → uploads `space/` + `src/repower/` to the HF Space → Space auto-builds and starts.

## Verification checklist

- [ ] Space build log shows no missing dependencies
- [ ] Space cold-start pulls DB (visible in Space logs, ~2-5 s)
- [ ] All 5 dashboard tabs render with real data
- [ ] Sidebar Refresh button re-pulls DB and clears cache
- [ ] Push a code change to GitHub main → sync-space fires → Space rebuilds
- [ ] Day after first cron run: Refresh on Space shows latest date

## Security notes

- The HF Space token should be **read-only** and scoped only to `nakama-s/repower-data`. This limits blast radius if the Space token is ever exposed.
- Raw JEPX/TEPCO data is stored in the private dataset only — the public Space shows charts/aggregates, never raw CSV files.
- The Space filesystem is ephemeral — the DB is pulled fresh on each cold-start and is never persistently stored on the Space.

## Maintenance

- **DB size:** ~2 MB/year; well within 10 GB HF free tier.
- **Space sleep:** Free Spaces sleep after ~48 h inactivity. Wake time ~30 s. Acceptable for an analytical dashboard.
- **Future — auto-restart after cron:** If you want the Space to always show fresh data without a manual Refresh, add a step to `daily.yml` after `push-hf`:
  ```yaml
  - name: Restart HF Space
    env:
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
    run: |
      pip install --quiet huggingface-hub
      python -c "
      import os
      from huggingface_hub import HfApi
      HfApi(token=os.environ['HF_TOKEN']).restart_space('nakama-s/repower')
      "
  ```
