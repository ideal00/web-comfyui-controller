"""Prompt normalization helpers shared by compilers and AI integrations."""

from __future__ import annotations

import re


def split_prompt_terms(value: str, limit: int = 48) -> list[str]:
    return [term.strip() for term in re.split(r"[,;\n]+", str(value or "")) if term.strip()][:limit]


def normalize_prompt_key(value: str) -> str:
    """Normalize one comma-delimited term for exact, not substring, deduping."""
    term = str(value or "").strip().casefold().replace("\\(", "(").replace("\\)", ")")
    weighted = re.fullmatch(r"\((.*):\s*(?:0(?:\.\d+)?|1(?:\.\d+)?|2(?:\.0+)?)\)", term)
    if weighted:
        term = weighted.group(1).strip()
    return re.sub(r"\s+", " ", term.replace("_", " ")).strip(" .")


def unique_prompt_terms(*chunks: str) -> str:
    seen: set[str] = set()
    terms: list[str] = []
    for chunk in chunks:
        for term in split_prompt_terms(chunk, limit=180):
            key = normalize_prompt_key(term)
            if key not in seen:
                seen.add(key)
                terms.append(term)
    return ", ".join(terms)


def normalized_safety_level(data: dict) -> str:
    level = str(data.get("safetyLevel", "")).strip().lower()
    if level not in {"safe", "sensitive", "nsfw", "explicit"}:
        level = "nsfw" if data.get("mature") else "safe"
    return level


__all__ = [
    "normalize_prompt_key",
    "normalized_safety_level",
    "split_prompt_terms",
    "unique_prompt_terms",
]
