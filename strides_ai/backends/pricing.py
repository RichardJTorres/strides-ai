"""Estimated cost of one LLM call, from a per-model price table.

USD per million tokens. Prices are estimates (as of 2026-11): they ignore long-prompt tiers, batch
and fast-mode rates. Cost is computed on read so a price change never needs a data rewrite.
Models with no entry (OpenAI, Gemini) have no cost: ``cost`` returns None, never 0. Ollama runs
locally and costs nothing.
"""

from dataclasses import dataclass

# Anthropic's documented cache multipliers where a model does not list its own cache-read price.
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None  # defaults to CACHE_READ_FACTOR * input
    cache_write: float | None = None  # defaults to CACHE_WRITE_FACTOR * input

    @property
    def read(self) -> float:
        return self.cache_read if self.cache_read is not None else self.input * CACHE_READ_FACTOR

    @property
    def write(self) -> float:
        return self.cache_write if self.cache_write is not None else self.input * CACHE_WRITE_FACTOR


# Longest prefix wins, so "claude-opus-5-5" is not priced as "claude-opus-5".
_CLAUDE = {
    "claude-fable-5-2": Price(8, 40, cache_read=0.20),
    "claude-mythos-5-2": Price(8, 40, cache_read=0.20),
    "claude-fable-5": Price(10, 50),  # 5 and 5.1
    "claude-mythos-5": Price(10, 50),
    "claude-opus-5-5": Price(4, 20, cache_read=0.20),
    "claude-opus-5": Price(5, 25),
    # Opus 4 and 4.1 were priced higher and are deliberately absent (unpriced, not mispriced).
    "claude-opus-4-5": Price(5, 25),
    "claude-opus-4-6": Price(5, 25),
    "claude-opus-4-7": Price(5, 25),
    "claude-opus-4-8": Price(5, 25),
    "claude-sonnet-5": Price(2, 10),
    "claude-sonnet-5-5": Price(2, 10, cache_read=0.10),
    "claude-sonnet-4-6": Price(3, 15),
    "claude-haiku-5-5": Price(0.10, 0.50),
    "claude-haiku-4-5": Price(1, 5),
}
_FREE = Price(0, 0, 0, 0)
_TABLES = {"claude": _CLAUDE}


def price_for(provider: str, model: str) -> Price | None:
    if provider == "ollama":
        return _FREE
    table = _TABLES.get(provider, {})
    for prefix in sorted(table, key=len, reverse=True):
        if (model or "").startswith(prefix):
            return table[prefix]
    return None


def cost(provider: str, model: str, usage: dict) -> float | None:
    """Estimated USD for one call, or None when the model is unpriced or tokens were unreported.

    ``usage`` holds ``input_total`` (cached + uncached), ``cache_read``, ``cache_write`` and
    ``output_total`` (which already includes reasoning, so it is not added again).
    """
    price = price_for(provider, model)
    inp, out = usage.get("input_total"), usage.get("output_total")
    if price is None or inp is None or out is None:
        return None
    read = usage.get("cache_read") or 0
    write = usage.get("cache_write") or 0
    fresh = max(inp - read - write, 0)
    return (
        fresh * price.input + read * price.read + write * price.write + out * price.output
    ) / 1_000_000
