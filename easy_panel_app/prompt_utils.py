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


def merge_hires_prompt(base_positive: str, base_negative: str,
                       hires_positive: str, hires_negative: str,
                       mode: str) -> tuple[str, str]:
    """Merge first-stage and hi-res-stage prompts.

    inherit: the hi-res pass reuses the first-stage conditioning verbatim.
    append:  keep the first-stage composition and append hi-res detail terms.
    replace: the hi-res pass uses only its own text; a blank field keeps the
             first-stage text so an accidental empty box cannot wipe an
             already validated prompt.
    """
    second_positive = str(hires_positive or "").strip()
    second_negative = str(hires_negative or "").strip()
    normalized = str(mode or "").strip().lower()
    if normalized == "replace":
        return (unique_prompt_terms(second_positive or base_positive),
                unique_prompt_terms(second_negative or base_negative))
    if normalized == "append":
        return (unique_prompt_terms(base_positive, second_positive),
                unique_prompt_terms(base_negative, second_negative))
    return str(base_positive or ""), str(base_negative or "")


def normalized_safety_level(data: dict) -> str:
    level = str(data.get("safetyLevel", "")).strip().lower()
    if level not in {"safe", "sensitive", "nsfw", "explicit"}:
        level = "nsfw" if data.get("mature") else "safe"
    return level


__all__ = [
    "merge_hires_prompt",
    "normalize_prompt_key",
    "normalized_safety_level",
    "split_prompt_terms",
    "unique_prompt_terms",
]
