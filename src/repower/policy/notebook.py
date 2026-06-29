"""Thin wrapper around the ``notebooklm`` CLI (the only place that shells out to it).

Every call uses ``--json`` and an explicit ``-n <notebook_id>`` / ``--notebook``
(parallel-safe), parses stdout with the stdlib ``json``, and branches on the CLI's
exit codes (0 ok, 1 error, 2 timeout). Language is set **per command**
(``--language ja``) — never the account-global ``language set`` — so a shared
account isn't corrupted. Auth is verified once per run via ``auth check --test``.

This module performs no DB I/O and holds no state; the pipeline persists results.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

NOTEBOOKLM_BIN = os.getenv("NOTEBOOKLM_BIN", "notebooklm")

# Exit codes (per the skill's documented contract).
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_TIMEOUT = 2


class NotebookLMError(RuntimeError):
    """A notebooklm command failed (non-zero exit, unparseable output, etc.)."""


class NotebookLMAuthError(NotebookLMError):
    """Authentication is missing or stale — a human must run ``notebooklm login``."""


class NotebookLMTimeout(NotebookLMError):
    """A ``wait``/long-running command hit its timeout (exit code 2)."""


def _run(args: list[str], *, timeout: float, allow_codes: tuple[int, ...] = (EXIT_OK,)) -> str:
    """Run ``notebooklm <args>`` and return stdout. Raise on disallowed exit codes."""
    cmd = [NOTEBOOKLM_BIN, *args]
    logger.debug("notebooklm %s", " ".join(args))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8"
        )
    except FileNotFoundError as e:
        raise NotebookLMError(f"`{NOTEBOOKLM_BIN}` not found on PATH — is notebooklm-py installed?") from e
    except subprocess.TimeoutExpired as e:
        raise NotebookLMTimeout(f"timeout after {timeout}s: notebooklm {' '.join(args)}") from e
    if proc.returncode == EXIT_TIMEOUT and EXIT_TIMEOUT not in allow_codes:
        raise NotebookLMTimeout(proc.stderr.strip() or "notebooklm timed out")
    if proc.returncode not in allow_codes:
        raise NotebookLMError(
            f"notebooklm {' '.join(args)} -> exit {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout


def _json(args: list[str], *, timeout: float):
    out = _run([*args, "--json"], timeout=timeout)
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise NotebookLMError(f"non-JSON output from notebooklm {' '.join(args)}: {out[:200]!r}") from e


# ── Auth ─────────────────────────────────────────────────────────────────────
def auth_ok(*, timeout: float = 60.0) -> bool:
    """True only if the network-validated auth check passes (status==ok AND
    token_fetch==true). A stale cookie file passes the parse check but not this."""
    try:
        data = _json(["auth", "check", "--test"], timeout=timeout)
    except NotebookLMError as e:
        logger.warning("notebooklm auth check failed: %s", e)
        return False
    return bool(data.get("status") == "ok" and data.get("checks", {}).get("token_fetch"))


def require_auth(*, timeout: float = 60.0) -> None:
    if not auth_ok(timeout=timeout):
        raise NotebookLMAuthError(
            "NotebookLM auth missing/stale — run `notebooklm login` (or refresh the "
            "NOTEBOOKLM_AUTH_JSON secret) before summarising."
        )


# ── Notebooks ────────────────────────────────────────────────────────────────
def create_notebook(title: str, *, timeout: float = 120.0) -> str:
    return _json(["create", title], timeout=timeout)["notebook"]["id"]


def delete_notebook(notebook_id: str, *, timeout: float = 120.0) -> None:
    # --json implies --yes (no interactive prompt).
    _json(["delete", "-n", notebook_id, "--yes"], timeout=timeout)


def list_notebooks(*, timeout: float = 60.0) -> list[dict]:
    return _json(["list"], timeout=timeout).get("notebooks", [])


# ── Sources ──────────────────────────────────────────────────────────────────
def add_source(notebook_id: str, path_or_url: str, *, timeout: float = 180.0) -> str:
    return _json(["source", "add", path_or_url, "--notebook", notebook_id], timeout=timeout)["source"]["id"]


def wait_source(notebook_id: str, source_id: str, *, timeout: float = 600.0) -> bool:
    """Block until a source is READY. Returns False on processing error/timeout."""
    try:
        _run(["source", "wait", source_id, "-n", notebook_id, "--timeout", str(int(timeout))],
             timeout=timeout + 30)
        return True
    except NotebookLMError as e:
        logger.warning("source wait failed (%s): %s", source_id, e)
        return False


def source_fulltext(notebook_id: str, source_id: str, *, timeout: float = 120.0) -> dict:
    return _json(["source", "fulltext", source_id, "--notebook", notebook_id], timeout=timeout)


def list_sources(notebook_id: str, *, timeout: float = 60.0) -> list[dict]:
    return _json(["source", "list", "--notebook", notebook_id], timeout=timeout).get("sources", [])


def delete_source_by_title(notebook_id: str, title: str, *, timeout: float = 120.0) -> None:
    try:
        _json(["source", "delete-by-title", title, "--notebook", notebook_id, "--yes"], timeout=timeout)
    except NotebookLMError as e:
        logger.debug("delete-by-title (%s) no-op: %s", title, e)


# ── Generation ───────────────────────────────────────────────────────────────
def generate_report(notebook_id: str, prompt: str, *, language: str = "ja",
                    fmt: str = "custom", retry: int = 2, timeout: float = 120.0) -> str:
    """Kick off a report generation; returns the task id (fire-and-forget)."""
    with _prompt_file(prompt) as pf:
        data = _json(
            ["generate", "report", "--format", fmt, "--prompt-file", pf,
             "--language", language, "--retry", str(retry), "-n", notebook_id],
            timeout=timeout,
        )
    return data["task_id"]


def wait_artifact(notebook_id: str, task_id: str, *, timeout: float = 1200.0) -> bool:
    """Block until an artifact completes. Returns False on timeout/error so the
    caller can leave the meeting in 'generating' for a later resume."""
    try:
        _run(["artifact", "wait", task_id, "-n", notebook_id, "--timeout", str(int(timeout))],
             timeout=timeout + 30)
        return True
    except NotebookLMError as e:
        logger.warning("artifact wait failed (%s): %s", task_id, e)
        return False


def download_report(notebook_id: str, task_id: str, dest: Path, *, timeout: float = 180.0) -> bool:
    try:
        _run(["download", "report", str(dest), "-a", task_id, "-n", notebook_id], timeout=timeout)
        return dest.exists()
    except NotebookLMError as e:
        logger.warning("download report failed (%s): %s", task_id, e)
        return False


def ask(notebook_id: str, question: str, *, language: str | None = None, timeout: float = 180.0) -> dict:
    args = ["ask", question, "-n", notebook_id]
    if language:
        args += ["--language", language]
    return _json(args, timeout=timeout)


# ── helpers ──────────────────────────────────────────────────────────────────
class _prompt_file:
    """Context manager writing *text* to a temp UTF-8 file for ``--prompt-file``
    (avoids shell length limits and quoting issues with long Japanese prompts)."""

    def __init__(self, text: str):
        self.text = text
        self.path: str | None = None

    def __enter__(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="nblm_prompt_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self.text)
        self.path = path
        return path

    def __exit__(self, *exc) -> None:
        if self.path:
            try:
                os.unlink(self.path)
            except OSError:
                pass
