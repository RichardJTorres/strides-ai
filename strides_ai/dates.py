"""Date display for every prompt: a weekday on each date and "how far away" for upcoming ones.

The model is bad at calendar arithmetic, and a bare "2026-11-21" in a table forces it to work out
the weekday (and "next Tuesday", "in 9 days") itself. Rendering both next to the date removes the
most common source of off-by-one plan edits. Pure functions: `today` is always a parameter.
"""

from datetime import date, datetime, timezone


def parse_day(value) -> date | None:
    """A date from a `date`, a `datetime`, or the first 10 characters of an ISO string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def fmt_day(value) -> str:
    """ "Sat 2026-11-14". Unparseable input is returned as text ("?" when empty), never raised."""
    day = parse_day(value)
    if day is None:
        return str(value) if value else "?"
    return f"{day:%a} {day.isoformat()}"


def days_away(value, today: date) -> str:
    """ "today", "tomorrow", "in 9 days", "yesterday" or "4 days ago"; "" when unparseable."""
    day = parse_day(value)
    if day is None:
        return ""
    n = (day - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    return f"in {n} days" if n > 0 else f"{-n} days ago"


def week_bounds(today: date) -> tuple[date, date]:
    """Monday and Sunday of the week containing `today` (the backend's weeks are Monday-Sunday)."""
    monday = date.fromordinal(today.toordinal() - today.weekday())
    return monday, date.fromordinal(monday.toordinal() + 6)


def local_stamp(created_at: str | None) -> str | None:
    """A stored UTC timestamp ("YYYY-MM-DD HH:MM:SS") as local "Sat 2026-11-14 18:28".

    Local means this machine's timezone, the same one "Today is ..." in the prompt uses.
    """
    try:
        moment = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    local = moment.replace(tzinfo=timezone.utc).astimezone()
    return f"{local:%a %Y-%m-%d %H:%M}"
