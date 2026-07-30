# JEMA — Claude Design bundle

Everything needed to seed a Claude Design project for the JEMA dashboard. This
folder is **sync-ready**: the HTML files carry the `@dsCard` markers Claude
Design uses to build its Design System card index.

## Contents

| File | Purpose |
|---|---|
| `JEMA-product-design-spec.md` | The full ~19.5k-word product & visual design spec (source of truth). |
| `screens/market-overview.html` | Wireframe card — Screen 1, hybrid landing (`@dsCard` group `Screens`). |
| `screens/market-data.html` | Wireframe card — Screen 2, wholesale & balancing. |
| `screens/policy-deep-dive.html` | Wireframe card — Screen 3, policy observer. |

Each `screens/*.html` is a self-contained, themeable (light/dark) preview that
renders standalone in a browser and as a card in the Claude Design pane.

> **Not to be confused with the repo-root `screens/*.html`.** Those are a
> different, later set: hi-fi Claude Design *exports* (~114–159 KB, inlined
> `dc-runtime` + `DCLogic` fixtures) that `web/src/screens/*.tsx` were ported
> from, and they include a fourth screen, Capacity & Auctions, that never got a
> wireframe here. The files in *this* folder are the low-fi wireframe cards split
> from `../wireframes.html`.
>
> Both sets are **pre-implementation mockups filled with illustrative data**, not
> a source of truth. `screens/capacity-auctions.html`, for example, invents its
> Hokkaido/Kyushu clearing prices and mislabels how the FY2027 auction split. The
> shipped React screens are authoritative; see `docs/GOTCHAS.md`.

## How to push into Claude Design

Design-system authorization needs an **interactive `claude` terminal**, so this
can't be done from the desktop/web app session that generated it.

**Option A — sync from an interactive terminal (recommended)**
1. Open a terminal in this repo and run `claude`.
2. Run `/design-login` and complete the browser authorization.
3. Ask Claude: *"Sync `docs/design/claude-design/` into my JEMA Claude Design
   project (create it if it doesn't exist)."* Claude uses the DesignSync tool:
   `list_projects` → `create_project "JEMA"` (or pick an existing one) →
   `finalize_plan` with `localDir = docs/design/claude-design` → `write_files`.

**Option B — manual**
1. Open claude.ai/design and create a project (e.g. "JEMA").
2. Provide the spec (`JEMA-product-design-spec.md`) as context and open the
   `screens/*.html` files for the visual reference, then prompt Claude Design to
   mock up prototypes screen by screen.

## Regenerating the screen files

The `screens/*.html` are split from `../wireframes.html`. If that file changes,
re-run `scratchpad/split_wireframes.py` to refresh them.

> Palette is the placeholder teal/navy "Harbor" base; brand tokens are named in
> the spec so a later swap is a one-line change. No legacy vendor branding.
