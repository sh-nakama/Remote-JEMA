# design-sync notes (JEMA)

- **This is a hand-authored reference-seed, not a converter sync.** RePower has no
  JS design system (no `dist/`, Storybook, or `package.json` components), so the
  `/design-sync` converter pipeline (`_ds_bundle.js`, `_ds_sync.json`, etc.) does
  not apply. The sync just pushes `docs/design/claude-design/` (3 wireframe cards
  carrying `@dsCard` markers + the product spec + README) into the pinned JEMA
  project via `finalize_plan` → `write_files`. No `_ds_sync.json` anchor exists,
  so every re-sync re-uploads the full set (cheap — 5 files).

- **The banned-brand hard rule (CLAUDE.md) applies to the uploaded files too.**
  2026-07-03 sync caught the literal banned word in `README.md`'s closing note
  (which restated the rule by name) and neutralised it to "No legacy vendor
  branding." Re-run the CI brand grep (see ci.yml) over
  `docs/design/claude-design/` before every push.

- **Two spec copies diverge.** `docs/design/claude-design/JEMA-product-design-spec.md`
  (uploaded, source of truth per README) is newer/larger than the top-level
  `docs/design/JEMA-product-design-spec.md`. Only the claude-design copy is synced.
  The top-level copy is stale — reconcile or delete it when convenient.

- **`scratchpad/split_wireframes.py` (referenced by README/config for regenerating
  `screens/*.html` from `wireframes.html`) is gone** — scratchpad is ephemeral.
  The cards are already current (newer than `wireframes.html`); if `wireframes.html`
  changes again the splitter has to be re-created.
