"""Shared serialization helpers for the D3 iframe chart builders.

Two hardening concerns, one entry point (:func:`js_json`):

* **NaN/Inf sanitation** — pandas missing values reach the builders as float
  ``NaN``; plain ``json.dumps`` emits a bare ``NaN`` token, which is invalid
  JSON but a *valid JavaScript literal*, so the charts silently plotted junk.
  ``sanitize`` mirrors ``repower.dashboard.export_web._jsonable`` and rewrites
  ``NaN``/``±Inf`` to ``None`` (→ ``null``) before serialization.
* **Script-context escaping** — every payload is interpolated into an inline
  ``<script>`` block, where a ``</script>`` inside a JSON string would
  terminate the block early. ``js_json`` escapes ``</`` as ``<\\/`` so no
  payload can break out of the script context.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable


def sanitize(obj: object) -> object:
    """Replace NaN/Inf floats with ``None``, recursively.

    Mirror of ``repower.dashboard.export_web._jsonable`` (kept separate so the
    Streamlit components stay importable without the web-export module).
    """
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def js_json(obj: object, default: Callable[[object], object] | None = None) -> str:
    """``json.dumps`` for values interpolated into an inline ``<script>``.

    NaN/Inf become ``null`` (``allow_nan=False`` guarantees no bare token can
    slip through) and ``</`` is escaped so the payload cannot close the
    surrounding script tag or open a new HTML context.
    """
    text = json.dumps(sanitize(obj), default=default, allow_nan=False)
    return text.replace("</", "<\\/")
