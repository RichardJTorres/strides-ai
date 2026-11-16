"""Choosing what goes into a chat request: required context that is never cut, and reducible
sections each with a cap and a floor of zero, cut in a fixed order only when the total is over
``context_target``.

Pure: it works from a ``ContextPrompt``, the history pairs and two size functions, so the same
inputs always give the same prompt.
"""

from dataclasses import dataclass, field

from .budget import BudgetExceeded, ContextPrompt

HISTORY_CAP = 0.35  # share of the context target
HISTORY_CAP_REDUCED = 0.20
HISTORY_KEY = "history"

# The order things are cut in when the total is over the target. Each step only ever lowers a
# section, and the last ones empty everything, so the ladder ends at the required context alone.
LADDER = (
    ("older_summary:drop", "older_summary", 0),
    ("recent_activities:15", "recent_activities", 15),
    ("history:20%", HISTORY_KEY, "20%"),
    ("upcoming_later:28d", "upcoming_later", 28),
    ("other_memories:halve", "other_memories", "half"),
    ("recent_activities:7", "recent_activities", 7),
    ("progress_group:drop", "progress_group", 0),
    ("upcoming_later:drop", "upcoming_later", 0),
    ("history:1_pair", HISTORY_KEY, 1),
    ("history:none", HISTORY_KEY, 0),
    ("other_memories:none", "other_memories", 0),
    ("recent_activities:none", "recent_activities", 0),
)


@dataclass
class Selection:
    knobs: dict[str, int]
    pairs: int  # newest history pairs kept
    pairs_cap: int  # tokens the first history level was allowed
    max_pairs: int
    available_pairs: int
    ladder: list[str] = field(default_factory=list)
    required_est: int = 0
    stable: str = ""
    tail: str = ""


def too_large(required_est: int, target: int, parts: list[tuple[str, int]]) -> BudgetExceeded:
    """The rejection for required context that cannot fit: it names the three largest parts."""
    biggest = sorted((p for p in parts if p[1] > 0), key=lambda p: -p[1])[:3]
    named = ", ".join(f"{label} (about {est:,} tokens)" for label, est in biggest)
    return BudgetExceeded(
        f"This request needs about {required_est:,} tokens of required context, more than this "
        f"model's {target:,}-token budget for a request. The largest parts are {named}. "
        "Shorten them, or choose a model with a larger context window."
    )


def history_note(pairs: int, available: int) -> list[str]:
    if pairs >= available:
        return []
    return [f"Earlier conversation: {available - pairs} older exchanges omitted."]


def select_context(
    prompt: ContextPrompt,
    groups: list,
    *,
    target: int,
    cost,
    size,
    max_pairs: int,
    recent_limit: int | None = None,
    part_sizes=(),
    check_required: bool = True,
) -> Selection:
    """Pick every reducible section's level and how much history to keep.

    ``cost(value)`` is a token estimate (0 for empty); ``size(system, history)`` the estimate of
    the whole request (tools and the new message included) with that system text and those
    history messages. ``groups`` is the history as whole (user, assistant) pairs, oldest first.
    With ``check_required`` false (a provider count already admitted the request) the ladder runs
    to the end instead of rejecting.
    """
    available = min(max_pairs, len(groups))

    def history_of(pairs):
        return [m for group in groups[len(groups) - pairs :] for m in group] if pairs else []

    def fit_pairs(share):
        budget = int(target * share)
        low, high = 0, available
        while low < high:
            mid = (low + high + 1) // 2
            low, high = (mid, high) if cost(history_of(mid)) <= budget else (low, mid - 1)
        return low

    def total(knobs, pairs):
        text = prompt.stable(knobs, history_note(pairs, available))
        return size(f"{text}\n\n{prompt.tail}" if prompt.tail else text, history_of(pairs))

    empty = {p.key: 0 for p in prompt.reducible}
    required_est = total(empty, 0)
    if check_required and required_est > target:
        raise too_large(required_est, target, list(part_sizes))

    limits = {"recent_activities": recent_limit}
    chosen = Selection(
        {p.key: p.fit(int(target * p.cap), cost, limits.get(p.key)) for p in prompt.reducible},
        fit_pairs(HISTORY_CAP),
        int(target * HISTORY_CAP),
        max_pairs,
        len(groups),
        required_est=required_est,
    )
    for name, key, level in LADDER:
        if total(chosen.knobs, chosen.pairs) <= target:
            break
        if key == HISTORY_KEY:
            new = min(chosen.pairs, fit_pairs(HISTORY_CAP_REDUCED) if level == "20%" else level)
            changed, chosen.pairs = new != chosen.pairs, new
        elif key in chosen.knobs:
            current = chosen.knobs[key]
            new = current // 2 if level == "half" else min(current, level)
            changed, chosen.knobs[key] = new != current, new
        else:
            continue
        if changed:
            chosen.ladder.append(name)
    chosen.stable = prompt.stable(chosen.knobs, history_note(chosen.pairs, available))
    chosen.tail = prompt.tail
    return chosen
