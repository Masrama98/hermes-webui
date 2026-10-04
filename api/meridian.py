"""Meridian Team Panel — read-only roster status for the Meridian agents.

Backs ``GET /api/meridian/team-status``. Pure stdlib: it never mutates profile
state and never starts an agent, so it is safe to call at any time.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

#: (profile dir name, display name, role) — keep in sync with _shared/meridian-ops.md
ROSTER: tuple[tuple[str, str, str], ...] = (
    ("default", "Sarah Anindita", "Lead, Front Door"),
    ("vera", "Vera Nathania", "Business & Operations"),
    ("irene", "Irene", "Technology & Engineering"),
    ("audrey", "Audrey", "Communication & Marketing"),
    ("clara", "Clara", "Research & Intelligence"),
    ("helena", "Helena", "Finance & Wealth Management"),
    ("ingrid", "Ingrid", "Security & Risk"),
    ("farras", "Farras", "Meridian's Shadow"),
)

#: A profile whose newest activity is newer than this counts as "active".
ACTIVE_WINDOW_SECONDS = 3600

_DEFAULT_HERMES_HOME = Path(
    os.getenv("HERMES_HOME") or (Path.home() / ".hermes")
).expanduser()


def _base_hermes_home() -> Path:
    """Return the Hermes root that owns ``profiles/``.

    ``HERMES_HOME`` may point straight at a profile directory (isolated profile
    mode), in which case the nearest ancestor containing ``profiles/`` wins.
    """
    candidate = _DEFAULT_HERMES_HOME
    for path in (candidate, *candidate.parents):
        if (path / "profiles").is_dir():
            return path
    return candidate


def _profile_home(base: Path, name: str) -> Path:
    return base if name == "default" else base / "profiles" / name


def _count_sessions(home: Path) -> int:
    db = home / "state.db"
    if db.is_file():
        try:
            uri = f"file:{db}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.5) as conn:
                row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
                if row is not None:
                    return int(row[0])
        except sqlite3.Error:
            pass
    sessions = home / "sessions"
    if sessions.is_dir():
        return sum(
            1
            for entry in sessions.iterdir()
            if entry.suffix == ".json" and not entry.name.startswith("_")
        )
    return 0


def _count_memories(home: Path) -> int:
    total = 0
    for filename in ("MEMORY.md", "USER.md"):
        path = home / "memories" / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Entries are separated by "§"; a file without separators still counts 1.
        total += sum(1 for chunk in text.split("\u00a7") if chunk.strip())
    return total


def _count_skills(home: Path) -> int:
    root = home / "skills"
    if not root.is_dir():
        return 0
    total = 0
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if (entry / "SKILL.md").is_file():
            total += 1
        else:
            total += sum(
                1 for sub in entry.iterdir() if sub.is_dir() and (sub / "SKILL.md").is_file()
            )
    return total


def _model_for(home: Path) -> str:
    config = home / "config.yaml"
    if not config.is_file():
        return ""
    try:
        import yaml  # local import: api.config already requires PyYAML

        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    model = data.get("model")
    if isinstance(model, str):
        return model
    if isinstance(model, dict):
        for key in ("default", "name", "model", "id"):
            value = model.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _last_activity(home: Path) -> float | None:
    stamps: list[float] = []
    for rel in ("memories/MEMORY.md", "memories/USER.md", "state.db", "SOUL.md"):
        path = home / rel
        if path.is_file():
            try:
                stamps.append(path.stat().st_mtime)
            except OSError:
                pass
    return max(stamps) if stamps else None


def _shared_ops_mtime(base: Path) -> float | None:
    path = base / "profiles" / "_shared" / "meridian-ops.md"
    try:
        return path.stat().st_mtime if path.is_file() else None
    except OSError:
        return None


def _profile_row(base: Path, name: str, display: str, role: str, now: float) -> dict:
    home = _profile_home(base, name)
    if not home.is_dir():
        return {
            "profile": name,
            "name": display,
            "role": role,
            "status": "empty",
            "sessions": 0,
            "memories": 0,
            "skills": 0,
            "model": "",
            "last_activity": None,
            "exists": False,
        }
    activity = _last_activity(home)
    if activity is not None and (now - activity) <= ACTIVE_WINDOW_SECONDS:
        status = "active"
    else:
        status = "idle"
    return {
        "profile": name,
        "name": display,
        "role": role,
        "status": status,
        "sessions": _count_sessions(home),
        "memories": _count_memories(home),
        "skills": _count_skills(home),
        "model": _model_for(home),
        "last_activity": activity,
        "exists": True,
    }


def get_meridian_team_status() -> dict:
    """Aggregate roster status for the Meridian Team panel."""
    base = _base_hermes_home()
    now = time.time()
    rows = [_profile_row(base, name, display, role, now) for name, display, role in ROSTER]
    active = sum(1 for row in rows if row["status"] == "active")
    return {
        "ok": True,
        "generated_at": now,
        "base_home": str(base),
        "active_window_seconds": ACTIVE_WINDOW_SECONDS,
        "last_sync": _shared_ops_mtime(base),
        "total": len(rows),
        "active": active,
        "idle": len(rows) - active,
        "profiles": rows,
    }
