"""Library log messages (warnings, errors) from a run's ``run.log``.

SpeckleBem logs through spdlog's default logger to the worker's stdout, which the job runner sends
to ``run.log``; spdlog flushes after every line. Format (default pattern, colour codes only on a
terminal): ``[2026-10-20 10:00:00.123] [warning] message``. stdlib only (GUI, job runner, worker).
"""

from __future__ import annotations

import re
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LINE = re.compile(r"^\[[^\]]*\]\s*(?:\[[^\]]*\]\s*)?\[(warning|warn|error|critical)\]\s*(.*)$")
MAX_MESSAGES = 30


def parse_messages(text: str) -> list[dict]:
    """Warnings and errors in spdlog lines, in order, without exact duplicates."""
    out, seen = [], set()
    for raw in text.splitlines():
        m = _LINE.match(_ANSI.sub("", raw).strip())
        if not m:
            continue
        level = "warning" if m.group(1) in ("warning", "warn") else "error"
        msg = m.group(2).strip()
        if (level, msg) in seen:
            continue
        seen.add((level, msg))
        out.append({"level": level, "msg": msg})
        if len(out) >= MAX_MESSAGES:
            break
    return out


def log_size(run_dir: Path) -> int:
    try:
        return (Path(run_dir) / "run.log").stat().st_size
    except OSError:
        return 0


def messages_since(run_dir: Path, offset: int) -> list[dict]:
    """Messages written to ``run.log`` after byte ``offset`` (the worker's start)."""
    try:
        with open(Path(run_dir) / "run.log", "rb") as f:
            f.seek(offset)
            return parse_messages(f.read().decode("utf-8", errors="replace"))
    except OSError:
        return []
