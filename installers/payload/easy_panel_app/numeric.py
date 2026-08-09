"""Small validation helpers shared by workflow and media modules."""

from __future__ import annotations


def bounded(value, default, low, high, integer: bool = True):
    """Coerce a value and clamp it to an inclusive range."""
    try:
        value = int(value) if integer else float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


__all__ = ["bounded"]
