"""Policy observer — track Japanese energy-policy committees (METI / OCCTO / EGC),
detect new meetings, and summarise the discussion via Google NotebookLM.

The package separates concerns so detection (cheap, no auth) is decoupled from
summarisation (slow, needs NotebookLM auth):

- ``committees``  — the tracked committees as clean, typed config.
- ``scraper``     — pure fetch+parse: discover meetings and their material PDFs.
- ``detect``      — diff what's online against the DB and record new work.
- ``store``       — DB read/write + deterministic running-document regeneration.
- ``notebook``    — thin wrapper around the ``notebooklm`` CLI.
- ``pipeline``    — the summarisation state machine (per-meeting + per-committee).
"""

from __future__ import annotations

from repower.policy.committees import COMMITTEES, Committee, committee_by_key

__all__ = ["COMMITTEES", "Committee", "committee_by_key"]
