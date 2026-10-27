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


# -- progress: what the library is doing right now (all levels, from the tail of run.log) -------------------

_ANY = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)\]\s*(?:\[[^\]]*\]\s*)?\[(\w+)\]\s*"
                  r"(?:\[[\w./-]+:\d+\]\s*)?(.*)$")
TAIL_BYTES = 128_000

# (substring of the library message, what the GUI tells the user), first match from the END of the log wins.
# Wording describes what runs NOW: spdlog prints a step when it starts or when it ends (timer lines), and long
# steps are silent in between. Unknown messages fall back to the message text itself.
PHASES: tuple[tuple[str, str], ...] = (
    ("[timer] sparse assembly", "Ein Nahfeld-Assemblierungsschritt ist fertig; es folgen der PML-Nahring bzw. der "
                                "PML-Fernring (ACA) und die Vorkonditionierung"),
    ("sparse assembly (PML)", "PML-Nahring: gestreckte Dreieckspaare werden berechnet (oft der längste Schritt, "
                              "still bis zur Timer-Zeile)"),
    ("sparse assembly:", "Nahfeld-Matrix wird assembliert"),
    ("PmlRingOperator", "PML-Ring: Nahring und Fernring (ACA); die Zeile nennt Blöcke und Speicher, der Fernring "
                        "läuft danach ohne weitere Meldung"),
    ("MlfmmOperator", "MLFMM-Operator wird zusammengesetzt"),
    ("MlfmmFarOperator: 2N", "MLFMM-Fernoperator fertig; Nahfeld-Matrizen werden assembliert"),
    ("MlfmmFarOperator: region", "MLFMM-Fernoperator wird aufgebaut (Gebiete und Oktree-Ebenen, feinste zuerst)"),
    ("Simulation (PML)", "Simulation steht; MLFMM-Fernoperatoren werden aufgebaut"),
    ("AngularSpectrumBeam", "Strahl ist berechnet; Simulation wird aufgebaut"),
)


def parse_lines(text: str, limit: int = 12) -> list[dict]:
    """The last ``limit`` spdlog lines (any level) as ``{"time", "level", "msg"}``; other output is skipped."""
    out = []
    for raw in text.splitlines():
        m = _ANY.match(_ANSI.sub("", raw).strip())
        if m:
            out.append({"time": m.group(1), "level": m.group(2).lower(), "msg": m.group(3).strip()})
    return out[-limit:]


def phase_of(lines: list[dict]) -> str | None:
    """Plain-language description of the step the last library messages point to (None without messages)."""
    for line in reversed(lines):
        for key, text in PHASES:
            if key in line["msg"]:
                return text
    return lines[-1]["msg"] if lines else None


def read_progress(run_dir: Path, limit: int = 12) -> dict:
    """``{"phase", "lines", "silent_seconds"}`` from the tail of ``run.log``; empty lines and None while the
    library has not logged anything. ``silent_seconds`` = time since the log was last written."""
    import time  # noqa: PLC0415

    path = Path(run_dir) / "run.log"
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
        silent = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return {"phase": None, "lines": [], "silent_seconds": None}
    lines = parse_lines(text, limit)
    return {"phase": phase_of(lines), "lines": lines, "silent_seconds": silent if lines else None}
