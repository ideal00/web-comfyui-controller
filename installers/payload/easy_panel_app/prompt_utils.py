"""Prompt normalization helpers shared by compilers and AI integrations."""

from __future__ import annotations

import re

# Canonical panel section order.  Unknown keys are appended in insertion order so an
# API caller cannot lose content by using a newer section name.
SECTION_ORDER = (
    "subject", "appearance", "expression", "clothing", "pose",
    "composition", "scene", "lighting", "style", "naturalLanguage", "manual",
)


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


def compose_prompt_sections(sections: dict, order: tuple = SECTION_ORDER) -> str:
    """Join section texts in a stable order, skipping empty sections."""
    if not isinstance(sections, dict):
        return ""
    keys = list(order) + [key for key in sections if key not in order]
    parts = [str(sections.get(key, "") or "").strip() for key in keys]
    return ", ".join(part for part in parts if part)


def replace_prompt_section(sections: dict, section: str, replacement: str,
                           mode: str = "replace") -> dict:
    """Return a copy of ``sections`` with exactly one section replaced.

    Section-scoped on purpose: replacing clothing must never touch appearance,
    pose, composition, scene or the hi-res enhancement fields, because the
    compiler owns those boundaries.
    """
    key = str(section or "").strip().lower()
    if key not in SECTION_ORDER:
        raise ValueError(f"未知提示词分区：{section or '（空）'}")
    value = str(replacement or "").strip()
    updated = dict(sections or {})
    if str(mode or "").strip().lower() == "append" and value:
        updated[key] = unique_prompt_terms(str(updated.get(key, "") or ""), value)
    else:
        updated[key] = value
    return updated


def diff_prompt_sections(before: dict, after: dict) -> list[dict]:
    """Describe which sections changed, in panel display order."""
    changes = []
    for key in SECTION_ORDER:
        old = str((before or {}).get(key, "") or "").strip()
        new = str((after or {}).get(key, "") or "").strip()
        if old != new:
            changes.append({"section": key, "before": old, "after": new})
    return changes


def parse_prompt_sections(text: str, family: str = "illustrious") -> dict:
    """Best-effort split of a flat English prompt; unclassified terms land in manual."""
    try:
        from easy_panel_app.integrations.ai import classify_english_prompt
        sections = classify_english_prompt(text, family)
    except Exception:  # pragma: no cover - classifier import/parse fallback
        sections = {"manual": str(text or "").strip()}
    return {key: str(value or "").strip()
            for key, value in (sections or {}).items() if str(value or "").strip()}


def normalized_safety_level(data: dict) -> str:
    level = str(data.get("safetyLevel", "")).strip().lower()
    if level not in {"safe", "sensitive", "nsfw", "explicit"}:
        level = "nsfw" if data.get("mature") else "safe"
    return level


__all__ = [
    "SECTION_ORDER",
    "compose_prompt_sections",
    "diff_prompt_sections",
    "merge_hires_prompt",
    "normalize_prompt_key",
    "normalized_safety_level",
    "parse_prompt_sections",
    "replace_prompt_section",
    "split_prompt_terms",
    "unique_prompt_terms",
]
