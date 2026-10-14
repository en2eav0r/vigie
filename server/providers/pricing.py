"""Model prices, in USD per million tokens: (input, cached input, output).

Sources: the providers' public pricing pages, read on 12 October 2026. Reasoning tokens are billed as output.
A model missing here uses DEFAULT, deliberately high so the spending cap stays on the safe side.
Update this table when a provider changes its prices.
"""
from __future__ import annotations

PRICES: dict[str, tuple[float, float, float]] = {
    # Anthropic
    "claude-opus-5-5": (4.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 0.20, 10.00),
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    # OpenAI (models without hidden reasoning tokens are preferred for Vigie)
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    # Google Gemini (paid tier; the free tier costs nothing but is rate limited)
    "gemini-3.8-flash": (0.75, 0.075, 3.75),
    "gemini-3.6-flash": (0.75, 0.075, 3.75),
    "gemini-3.5-flash-lite": (0.30, 0.03, 2.50),
    "gemini-3.1-flash-lite": (0.25, 0.025, 1.50),
    "gemini-3-flash-preview": (0.50, 0.05, 3.00),
    # DeepSeek (peak hours; off-peak is half)
    "deepseek-flash": (0.30, 0.006, 1.20),
    "deepseek-v4-pro": (1.32, 0.044, 3.96),
}
DEFAULT = (2.00, 0.20, 12.00)


def price(model: str) -> tuple[float, float, float]:
    if model in PRICES:
        return PRICES[model]
    for name in sorted(PRICES, key=len, reverse=True):  # dated variants, e.g. gpt-4.1-nano-2025-04-14
        if model.startswith(name):
            return PRICES[name]
    return DEFAULT


def cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    p_in, p_cached, p_out = price(model)
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1e6
