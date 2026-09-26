"""No tracked file may carry the forbidden brand name, in its path or its bytes (see CLAUDE.md)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDLE = ("au" + "rora").encode()  # assembled here so this file carries no trace
ALLOWED = {"CLAUDE.md"}  # states the rule itself


def test_no_file_carries_the_brand():
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    offenders = []
    for rel in filter(None, listed.split("\0")):
        path = ROOT / rel
        if rel in ALLOWED:
            continue
        if NEEDLE in rel.lower().encode() or (path.is_file() and NEEDLE in path.read_bytes().lower()):
            offenders.append(rel)
    assert not offenders, f"brand trace in: {offenders}"
