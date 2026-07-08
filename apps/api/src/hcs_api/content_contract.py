"""Language-Agnostic Pedagogical Content Contract & Scaffold Resolver."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Meta labels forbidden in learner-facing output (language-agnostic)
LEARNER_FACING_FORBIDDEN_LABELS = {
    "生词卡", "词卡", "拖拽组句", "答案提示", "Teacher answer", "Teacher answer area",
    "SentenceDragBuilder", "GrammarPatternSlide", "VocabularyFlipCard",
    "VocabularySlide", "ObjectiveSlide", "WarmUpSlide", "PracticeSlide",
    "SummarySlide", "CoverSlide", "DialogueSlide",
    "MatchGame", "ListenAndChoose", "AudioButton",
    "component", "fallback", "debug", "provider_required",
    "Image placeholder", "Clean educational illustration",
}

LEARNER_FACING_FORBIDDEN_PATTERNS = [
    re.compile(r"provider_required"),
    re.compile(r"Editable PPTX export"),
    re.compile(r"Image placeholder"),
    re.compile(r"Clean educational"),
    re.compile(r"这(是|里|个|些)"),
    re.compile(r"朋友[之间同学]"),
    re.compile(r"同学之间"),
]

_LOCALE_CACHE: dict[str, dict] = {}


def load_language_profile(language_code: str) -> dict:
    """Load a language profile from bundled JSON files."""
    if language_code in _LOCALE_CACHE:
        return _LOCALE_CACHE[language_code]
    base = Path(__file__).parent / "language_profiles"
    candidates = [
        base / f"{language_code.lower()}.json",
        base / f"{language_code.capitalize()}.json",
        base / "english.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                _LOCALE_CACHE[language_code] = data
                return data
    _LOCALE_CACHE[language_code] = {"language_code": language_code, "minimal_glossary": {}}
    return _LOCALE_CACHE[language_code]


def resolve_scaffold_text(
    word: str,
    scaffold_language: str,
    language_items: list | None = None,
    item_lookup: dict[str, Any] | None = None,
) -> str:
    """Resolve scaffold text for a word in the given scaffold language.
    
    Priority:
    1. language_items[word].scaffold_meanings[scaffold_language]
    2. language_profile minimal_glossary[word]
    3. fallback to language_items[word].scaffold_meaning (generic)
    4. empty string
    """
    # Check scaffold_meanings dict on language_item
    if item_lookup and word in item_lookup:
        li = item_lookup[word]
        if hasattr(li, "scaffold_meanings") and isinstance(getattr(li, "scaffold_meanings", None), dict):
            if scaffold_language in li.scaffold_meanings:
                return li.scaffold_meanings[scaffold_language]
        if hasattr(li, "scaffold_meaning") and li.scaffold_meaning:
            return li.scaffold_meaning

    # Check language items list
    if language_items:
        for li in language_items:
            if hasattr(li, "target_form") and li.target_form == word:
                if hasattr(li, "scaffold_meanings") and isinstance(getattr(li, "scaffold_meanings", None), dict):
                    if scaffold_language in li.scaffold_meanings:
                        return li.scaffold_meanings[scaffold_language]
                if hasattr(li, "scaffold_meaning") and li.scaffold_meaning:
                    return li.scaffold_meaning

    # Check bundled language profile
    profile = load_language_profile(scaffold_language)
    glossary = profile.get("minimal_glossary", {})
    if word in glossary:
        return glossary[word]

    return ""


def is_allowed_learner_text(text: str, role: str, learner_level: str) -> tuple[bool, str]:
    """Check if text is allowed in learner-facing output."""
    if role in ("teacher", "debug", "ui"):
        return False, f"Role '{role}' is not learner-facing"

    if learner_level in ("zero_beginner",):
        for label in LEARNER_FACING_FORBIDDEN_LABELS:
            if label in text:
                return False, f"Contains forbidden label: '{label}'"
        for pattern in LEARNER_FACING_FORBIDDEN_PATTERNS:
            if pattern.search(text):
                return False, f"Matches forbidden pattern: {pattern.pattern}"

    return True, ""


def check_scaffold_language(text: str, expected_lang: str) -> tuple[bool, str]:
    """Basic check if scaffold text is in the expected language.
    For Arabic: check for Arabic Unicode range.
    For others: basic heuristic that text isn't Chinese (simplified check only)."""
    if not text.strip():
        return True, ""

    if expected_lang == "Arabic":
        arabic_range = re.compile(r"[؀-ۿݐ-ݿ]+")
        if not arabic_range.search(text):
            return False, "Scaffold text does not contain Arabic characters"
    elif expected_lang in ("Thai",):
        thai_range = re.compile(r"[฀-๿]+")
        if not thai_range.search(text):
            return False, "Scaffold text does not contain Thai characters"
    # For other languages, just check it's not Chinese characters
    chinese = re.compile(r"[一-鿿]{2,}")
    chinese_hits = chinese.findall(text)
    if chinese_hits and len("".join(chinese_hits)) > len(text) * 0.3:
        return False, f"Scaffold text contains Chinese: {chinese_hits[:3]}"

    return True, ""




def resolve_scaffold_usage(
    word: str,
    scaffold_language: str,
    language_items: list | None = None,
    item_lookup: dict | None = None,
) -> str:
    """Resolve usage context for a word in the scaffold language.
    
    Priority:
    1. language_items usage_contexts[scaffold_language]
    2. language profile usage_contexts[word]
    3. empty string (never fallback to Chinese)
    """
    # Check language_items
    if item_lookup and word in item_lookup:
        li = item_lookup[word]
        if hasattr(li, "usage_contexts") and isinstance(getattr(li, "usage_contexts", None), dict):
            if scaffold_language in li.usage_contexts:
                return li.usage_contexts[scaffold_language]
        if hasattr(li, "usage_context") and isinstance(getattr(li, "usage_context", None), dict):
            if scaffold_language in li.usage_context:
                return li.usage_context[scaffold_language]

    if language_items:
        for li in language_items:
            if hasattr(li, "target_form") and li.target_form == word:
                if hasattr(li, "usage_contexts") and isinstance(getattr(li, "usage_contexts", None), dict):
                    if scaffold_language in li.usage_contexts:
                        return li.usage_contexts[scaffold_language]
                if hasattr(li, "usage_context") and isinstance(getattr(li, "usage_context", None), dict):
                    if scaffold_language in li.usage_context:
                        return li.usage_context[scaffold_language]

    # Check language profile
    profile = load_language_profile(scaffold_language)
    usage_contexts = profile.get("usage_contexts", {})
    if word in usage_contexts:
        return usage_contexts[word]

    return ""


def resolve_scaffold_gloss(
    word: str,
    scaffold_language: str,
    language_items: list | None = None,
    item_lookup: dict | None = None,
) -> str:
    """Resolve scaffold meaning (gloss) only - never Chinese."""
    result = resolve_scaffold_text(word, scaffold_language, language_items, item_lookup)
    if result:
        return result
    return ""
def load_all_language_profiles() -> dict[str, dict]:
    """Load all available language profiles."""
    profiles = {}
    base = Path(__file__).parent / "language_profiles"
    for f in base.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
            profiles[data.get("language_code", f.stem)] = data
    return profiles
