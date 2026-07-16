from __future__ import annotations

import re

from pypinyin import Style, lazy_pinyin


HANZI = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def pinyin_for_text(text: str, overrides: dict[str, str] | None = None) -> str:
    """Return tone-mark pinyin for the Hanzi in learner-facing text."""
    syllables: list[str] = []
    for match in HANZI.finditer(text):
        value = match.group()
        if overrides and overrides.get(value):
            syllables.append(overrides[value])
        else:
            syllables.extend(lazy_pinyin(value, style=Style.TONE, neutral_tone_with_five=False))
    return " ".join(syllables)


def pinyin_segments(text: str, overrides: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Split text into plain spans and Hanzi spans with their pronunciation."""
    segments: list[tuple[str, str]] = []
    cursor = 0
    for match in HANZI.finditer(text):
        if match.start() > cursor:
            segments.append((text[cursor : match.start()], ""))
        value = match.group()
        segments.append((value, pinyin_for_text(value, overrides)))
        cursor = match.end()
    if cursor < len(text):
        segments.append((text[cursor:], ""))
    return segments
