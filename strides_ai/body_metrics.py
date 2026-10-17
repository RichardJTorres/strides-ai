"""Athlete body measurements (height, weight) in the profile's personal section.

Stored as numbers in SI (personal.height_cm, personal.weight_kg) and shown in the athlete's unit
system via strides_ai/units.py. Profiles written before that used free text (personal.height /
personal.weight); normalize_personal() parses those on read, and anything it can't parse is kept
verbatim in personal.body_notes so nothing the athlete typed is lost.

Deliberately dependency-free (only units.py) so the DB layer can import it without a cycle.
"""

import re

from .units import CM_PER_INCH, POUNDS_PER_KG

_NUM = r"(\d+(?:[.,]\d+)?)"


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_height_cm(text: str) -> float | None:
    """Free-text height -> cm. Accepts e.g. "178cm", "1.78 m", "5'10\"", "5 ft 10 in", "70 in",
    or a bare number that is unambiguous (>= 100 is cm, 1.2-2.5 is meters)."""
    t = text.strip().lower().replace("’", "'").replace("”", '"').replace("''", '"')
    if not t:
        return None
    if m := re.fullmatch(rf"{_NUM}\s*cm", t):
        return round(_num(m[1]), 1)
    if m := re.fullmatch(rf"{_NUM}\s*m(?:eters?|etres?)?", t):
        return round(_num(m[1]) * 100, 1)
    ft_in = rf"(\d+)\s*(?:'|ft|feet|foot)\s*(?:(\d+(?:\.\d+)?)\s*(?:\"|in|inches|inch)?)?"
    if m := re.fullmatch(ft_in, t):
        return round((int(m[1]) * 12 + (float(m[2]) if m[2] else 0)) * CM_PER_INCH, 1)
    if m := re.fullmatch(rf"{_NUM}\s*(?:\"|in|inches|inch)", t):
        return round(_num(m[1]) * CM_PER_INCH, 1)
    if m := re.fullmatch(_NUM, t):
        n = _num(m[1])
        if n >= 100:
            return round(n, 1)
        if 1.2 <= n <= 2.5:
            return round(n * 100, 1)
    return None


def parse_weight_kg(text: str) -> float | None:
    """Free-text weight -> kg. Accepts e.g. "77kg", "77 kilos", "170 lb", "170 lbs". A bare
    number is ambiguous (kg or lb) and is not parsed."""
    t = text.strip().lower()
    if m := re.fullmatch(rf"{_NUM}\s*(?:kg|kgs|kilos?|kilograms?)", t):
        return round(_num(m[1]), 1)
    if m := re.fullmatch(rf"{_NUM}\s*(?:lb|lbs|pounds?)", t):
        return round(_num(m[1]) / POUNDS_PER_KG, 1)
    return None


def normalize_personal(personal: dict) -> dict:
    """Return a copy of ``personal`` with legacy free-text height/weight moved to the numeric
    height_cm/weight_kg fields. Idempotent; unparseable text goes to body_notes."""
    p = dict(personal)
    notes = [p["body_notes"]] if p.get("body_notes") else []
    for legacy, field, parse, label in (
        ("height", "height_cm", parse_height_cm, "Height"),
        ("weight", "weight_kg", parse_weight_kg, "Weight"),
    ):
        raw = p.pop(legacy, None)
        text = str(raw).strip() if raw not in (None, "") else ""
        if not text or p.get(field) is not None:
            continue
        parsed = parse(text)
        if parsed is not None:
            p[field] = parsed
        else:
            notes.append(f"{label}: {text}")
    if notes:
        p["body_notes"] = "; ".join(notes)
    return p
