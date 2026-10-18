"""One-time conversion of the legacy per-mode profile rows to the unified layout.

Legacy rows: ``personal`` plus one row per mode (running / cycling / hybrid / lifting).
New rows: ``shared`` plus ``running`` / ``cycling`` / ``lifting`` (see ``profile.py``).

``unify_rows`` is pure so it can be tested directly; ``migrate_profile_rows`` applies it to a
DB connection. Legacy rows are kept under ``legacy:<name>`` so nothing is lost.
"""

import json
import re

import sqlalchemy as sa

from .body_metrics import normalize_personal
from .profile import DISCIPLINES, SHARED_DEFAULTS

_ORDER = ("running", "cycling", "hybrid", "lifting")
_TEXT_FIELDS = ("goals", "injuries_and_health", "other_notes")


def _s(val: object) -> str:
    return str(val).strip() if val not in (None, "") else ""


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _first(*vals: object) -> str:
    for v in vals:
        if _s(v):
            return _s(v)
    return ""


def _merge_text(values: list[str]) -> str:
    seen, out = set(), []
    for v in values:
        v = v.strip()
        if v and _norm(v) not in seen:
            seen.add(_norm(v))
            out.append(v)
    return "\n\n".join(out)


def _merge_snacks(rows: list[dict]) -> list[str]:
    seen, out = set(), []
    for row in rows:
        snacks = row.get("nutrition_snacks") or []
        if isinstance(snacks, str):
            snacks = snacks.splitlines()
        for item in snacks:
            item = str(item).strip()
            if item and _norm(item) not in seen:
                seen.add(_norm(item))
                out.append(item)
    return out


def _personal(old: dict[str, dict], settings_max_hr: str | None) -> dict:
    p = normalize_personal(old.get("personal") or {})
    out = {k: p.get(k, v) for k, v in SHARED_DEFAULTS["personal"].items()}
    if p.get("body_notes"):
        out["body_notes"] = p["body_notes"]
    raw = _s(p.get("max_hr"))
    if raw:
        m = re.fullmatch(r"(\d{2,3})\s*(?:bpm)?", raw, flags=re.I)
        if m:
            out["max_hr"] = int(m[1])
        else:
            out["max_hr"] = None
            note = f"Max HR: {raw}"
            out["body_notes"] = "; ".join(x for x in (out.get("body_notes"), note) if x)
    else:
        legacy = _s(settings_max_hr)
        out["max_hr"] = int(legacy) if legacy.isdigit() else None
    return out


def _discipline(name: str, old: dict[str, dict]) -> dict:
    spec = DISCIPLINES[name]
    out = {
        "since": "",
        "volume": "",
        "focus": "",
        "background": "",
        "bests": {key: "" for key, _ in spec.bests},
        "gear": "",
    }
    if name == "lifting":
        src = [(old.get("lifting") or {}, "lifting_background", "lifting_bests")]
        legacy_keys = {"since": ("lifting_since",), "volume": ("sessions_per_week",)}
        focus_keys = ("training_style",)
    elif name == "running":
        src = [
            (old.get("running") or {}, "running_background", "personal_bests"),
            (old.get("hybrid") or {}, "running_background", "running_bests"),
        ]
        legacy_keys = {
            "since": ("running_since",),
            "volume": ("weekly_volume", "weekly_run_volume"),
        }
        focus_keys = ("running_focus",)
    else:
        src = [
            (old.get("cycling") or {}, "cycling_background", "cycling_bests"),
            (old.get("hybrid") or {}, "cycling_background", "cycling_bests"),
        ]
        legacy_keys = {
            "since": ("cycling_since",),
            "volume": ("weekly_distance", "weekly_ride_distance"),
        }
        focus_keys = ("cycling_focus",)

    for row, bg_key, bests_key in src:
        bg, bests = row.get(bg_key) or {}, row.get(bests_key) or {}
        out["since"] = out["since"] or _first(*(bg.get(k) for k in legacy_keys["since"]))
        out["volume"] = out["volume"] or _first(*(bg.get(k) for k in legacy_keys["volume"]))
        out["focus"] = out["focus"] or _first(*(bg.get(k) for k in focus_keys))
        out["background"] = out["background"] or _s(bg.get("background"))
        for key in out["bests"]:
            out["bests"][key] = out["bests"][key] or _s(bests.get(key))

    own = old.get(name) or {}
    out["gear"] = (
        _first(own.get("equipment"), own.get("gear")) if name == "lifting" else _s(own.get("gear"))
    )
    return out


def unify_rows(old: dict[str, dict], settings_max_hr: str | None = None) -> dict[str, dict]:
    """Convert ``{legacy_row_name: fields}`` into ``{section: fields}``."""
    rows = [old.get(m) or {} for m in _ORDER]
    shared = {
        "personal": _personal(old, settings_max_hr),
        "availability": dict(SHARED_DEFAULTS["availability"]),
        "nutrition_snacks": _merge_snacks(rows),
        "coach_voice": _first(*(r.get("coach_voice") for r in rows)),
    }
    for key in _TEXT_FIELDS:
        shared[key] = _merge_text([_s(r.get(key)) for r in rows])

    sections = {"shared": shared}
    for name in DISCIPLINES:
        sections[name] = _discipline(name, old)

    # A hybrid-only gear note goes to running, else cycling, else is appended to running.
    hybrid_gear = _s((old.get("hybrid") or {}).get("gear"))
    if hybrid_gear:
        if not sections["running"]["gear"]:
            sections["running"]["gear"] = hybrid_gear
        elif not sections["cycling"]["gear"]:
            sections["cycling"]["gear"] = hybrid_gear
        else:
            sections["running"]["gear"] = _merge_text([sections["running"]["gear"], hybrid_gear])
    return sections


def migrate_profile_rows(conn: sa.Connection) -> bool:
    """Convert legacy rows in place. Returns False if already migrated or nothing to migrate."""
    rows = {
        r.mode: json.loads(r.fields_json)
        for r in conn.execute(sa.text("SELECT mode, fields_json FROM profiles"))
    }
    if "shared" in rows or not rows:
        return False
    legacy = {k: v for k, v in rows.items() if not k.startswith("legacy:")}
    setting = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'max_hr'")).scalar()
    sections = unify_rows(legacy, setting)
    for name in legacy:
        conn.execute(
            sa.text("UPDATE profiles SET mode = :new WHERE mode = :old"),
            {"new": f"legacy:{name}", "old": name},
        )
    for name, data in sections.items():
        conn.execute(
            sa.text("INSERT INTO profiles (mode, fields_json) VALUES (:m, :f)"),
            {"m": name, "f": json.dumps(data)},
        )
    return True
