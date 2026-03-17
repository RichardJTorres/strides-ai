"""Athlete profile — stored per-mode in the database."""

import copy

# ── Per-mode default field schemas ────────────────────────────────────────────

RUNNING_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
    },
    "running_background": {
        "running_since": "",
        "weekly_volume": "",
        "background": "",
    },
    "personal_bests": {
        "5k": "",
        "10k": "",
        "half_marathon": "",
        "marathon": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
}

CYCLING_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
    },
    "cycling_background": {
        "cycling_since": "",
        "weekly_distance": "",
        "background": "",
    },
    "cycling_bests": {
        "ftp": "",
        "fastest_century": "",
        "fastest_gran_fondo": "",
        "other": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
}

HYBRID_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
    },
    "running_background": {
        "running_since": "",
        "weekly_run_volume": "",
        "background": "",
    },
    "cycling_background": {
        "cycling_since": "",
        "weekly_ride_distance": "",
        "background": "",
    },
    "running_bests": {
        "5k": "",
        "10k": "",
        "half_marathon": "",
        "marathon": "",
    },
    "cycling_bests": {
        "ftp": "",
        "fastest_century": "",
        "fastest_gran_fondo": "",
        "other": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
}

_DEFAULTS = {
    "running": RUNNING_DEFAULTS,
    "cycling": CYCLING_DEFAULTS,
    "hybrid": HYBRID_DEFAULTS,
}


def get_default_fields(mode: str) -> dict:
    return copy.deepcopy(_DEFAULTS.get(mode, RUNNING_DEFAULTS))


# ── Text formatting for LLM system prompt ─────────────────────────────────────


def _v(val: object) -> str:
    return str(val).strip() if val else ""


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line)
    return f"### {title}\n{body}" if body else ""


def profile_to_text(fields: dict | None, mode: str) -> str:
    """Convert a profile fields dict to readable text for the system prompt.

    Only non-empty fields are emitted. Returns "" if fields is None or all blank.
    """
    if not fields:
        return ""

    p = fields.get("personal", {})
    sections: list[str] = []

    # Personal
    personal_lines = [
        f"Name: {_v(p.get('name'))}" if _v(p.get("name")) else "",
        f"Gender: {_v(p.get('gender'))}" if _v(p.get("gender")) else "",
        f"Date of birth: {_v(p.get('date_of_birth'))}" if _v(p.get("date_of_birth")) else "",
        f"Height: {_v(p.get('height'))}" if _v(p.get("height")) else "",
        f"Weight: {_v(p.get('weight'))}" if _v(p.get("weight")) else "",
    ]
    s = _section("Personal", personal_lines)
    if s:
        sections.append(s)

    if mode in ("running", "hybrid"):
        rb = fields.get("running_background", {})
        rb_lines = [
            f"Running since: {_v(rb.get('running_since'))}" if _v(rb.get("running_since")) else "",
            (
                f"Weekly volume: {_v(rb.get('weekly_volume') or rb.get('weekly_run_volume'))}"
                if _v(rb.get("weekly_volume") or rb.get("weekly_run_volume"))
                else ""
            ),
            f"Background: {_v(rb.get('background'))}" if _v(rb.get("background")) else "",
        ]
        s = _section("Running Background", rb_lines)
        if s:
            sections.append(s)

        pbs = fields.get("personal_bests" if mode == "running" else "running_bests", {})
        pb_lines = [
            f"5K: {_v(pbs.get('5k'))}" if _v(pbs.get("5k")) else "",
            f"10K: {_v(pbs.get('10k'))}" if _v(pbs.get("10k")) else "",
            (
                f"Half marathon: {_v(pbs.get('half_marathon'))}"
                if _v(pbs.get("half_marathon"))
                else ""
            ),
            f"Marathon: {_v(pbs.get('marathon'))}" if _v(pbs.get("marathon")) else "",
        ]
        s = _section("Running Personal Bests", pb_lines)
        if s:
            sections.append(s)

    if mode in ("cycling", "hybrid"):
        cb = fields.get("cycling_background", {})
        cb_lines = [
            f"Cycling since: {_v(cb.get('cycling_since'))}" if _v(cb.get("cycling_since")) else "",
            (
                f"Weekly distance: {_v(cb.get('weekly_distance') or cb.get('weekly_ride_distance'))}"
                if _v(cb.get("weekly_distance") or cb.get("weekly_ride_distance"))
                else ""
            ),
            f"Background: {_v(cb.get('background'))}" if _v(cb.get("background")) else "",
        ]
        s = _section("Cycling Background", cb_lines)
        if s:
            sections.append(s)

        cyb = fields.get("cycling_bests", {})
        cyb_lines = [
            f"FTP: {_v(cyb.get('ftp'))}" if _v(cyb.get("ftp")) else "",
            (
                f"Fastest century: {_v(cyb.get('fastest_century'))}"
                if _v(cyb.get("fastest_century"))
                else ""
            ),
            (
                f"Fastest gran fondo: {_v(cyb.get('fastest_gran_fondo'))}"
                if _v(cyb.get("fastest_gran_fondo"))
                else ""
            ),
            f"Other: {_v(cyb.get('other'))}" if _v(cyb.get("other")) else "",
        ]
        s = _section("Cycling Bests", cyb_lines)
        if s:
            sections.append(s)

    for key, title in [
        ("goals", "Goals"),
        ("injuries_and_health", "Injuries & Health"),
        ("gear", "Gear"),
        ("other_notes", "Other Notes"),
    ]:
        val = _v(fields.get(key))
        if val:
            sections.append(f"### {title}\n{val}")

    snacks = fields.get("nutrition_snacks", [])
    if isinstance(snacks, list):
        snack_items = [s.strip() for s in snacks if str(s).strip()]
    else:
        snack_items = [s.strip() for s in str(snacks).splitlines() if s.strip()]
    if snack_items:
        bullet_list = "\n".join(f"- {s}" for s in snack_items)
        sections.append(f"### Preferred Nutrition & Snacks\n{bullet_list}")

    if not sections:
        return ""

    return "## Athlete Profile\n\n" + "\n\n".join(sections)
