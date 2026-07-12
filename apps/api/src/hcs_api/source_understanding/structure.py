"""Textbook structure reconstruction (teaching-agnostic).

This stage answers only "what structural units does the source contain?" — unit
titles, vocabulary lists, dialogues, grammar points, exercises, culture notes,
listening tasks, picture tasks, readings. It deliberately does NOT turn any of
these into teaching activities; that belongs to the Learner Analysis / State-
Evidence Kernel. The output is a stable ``TextbookStructure`` that downstream
layers can rely on.
"""

from __future__ import annotations

import re

from hcs_api.models import OCREvidenceBlock, PageAnalysisResult, TextbookSection, TextbookSectionType, TextbookStructure

UNIT_RE = re.compile(r"(第\s*[一二三四五六七八九十\d]+\s*单元)|(Unit\s*[\dIVX]+)", re.I)
LESSON_RE = re.compile(r"(第\s*[一二三四五六七八九十\d]+\s*课)|(Lesson\s*[\dIVX]+)", re.I)

HEADING_RULES: list[tuple[TextbookSectionType, re.Pattern[str]]] = [
    ("vocabulary", re.compile(r"生词|词语|词汇|New\s*Words|Word\s*List|Vocabulary", re.I)),
    ("dialogue", re.compile(r"对话|Dialogue|Conversation", re.I)),
    ("language_focus", re.compile(r"语法|语言点|Language\s*Point|Grammar", re.I)),
    ("exercise", re.compile(r"练习|做一?做|听一?听|说一?说|选择题|连线|填空|Exercise|Quiz", re.I)),
    ("culture", re.compile(r"文化|Culture", re.I)),
    ("listening", re.compile(r"听力|Listening", re.I)),
    ("picture_task", re.compile(r"看图|Look\s*at\s*the\s*picture|Picture\s*Description", re.I)),
    ("reading", re.compile(r"阅读|读课文|Reading", re.I)),
    ("notes", re.compile(r"注释|说明|Notes", re.I)),
]

DIALOGUE_TURN_RE = re.compile(r"^\s*([^：:\n]{1,12})[：:]\s*(.*)$")
EXERCISE_OPTION_RE = re.compile(r"^\s*[（(]?[A-Da-d][）)．.、]\s")
EXERCISE_Q_RE = re.compile(r"^\s*([0-9]+[.、]|[一二三四五六七八九十]+[.、]|[（(][0-9]+[）)])")
EXERCISE_ANSWER_RE = re.compile(r"答案|Answer|正确选项", re.I)

# Strip leading list markers ("1. ", "一、", "（2）") before testing heading candidacy.
_LIST_MARKER = re.compile(r"^\s*([0-9]+[.、]|[一二三四五六七八九十]+[.、]|[（(][0-9]+[）)])\s*")
_ENGLISH_HEADING = re.compile(r"^[A-Za-z][A-Za-z ]{1,20}$")


def _is_heading_candidate(stripped: str) -> bool:
    """A heading is a short CJK label or a known English section word.

    This prevents instructions such as '听一听，选一选。' (listen and choose)
    from being mistaken for a new section heading.
    """
    if not stripped:
        return False
    if _ENGLISH_HEADING.fullmatch(stripped):
        return True
    return len(stripped) <= 6


def _match_heading(text: str) -> TextbookSectionType | None:
    stripped = _LIST_MARKER.sub("", text).strip()
    if not _is_heading_candidate(stripped):
        return None
    for section_type, pattern in HEADING_RULES:
        if pattern.search(text):
            return section_type
    return None


def _refine_block_type(block: OCREvidenceBlock, section_type: TextbookSectionType, text: str) -> None:
    if section_type == "vocabulary":
        block.block_type = "vocabulary_item"
    elif section_type == "dialogue":
        m = DIALOGUE_TURN_RE.match(text)
        if m:
            block.block_type = "dialogue_turn"
            block.speaker = m.group(1).strip()
        else:
            if block.block_type == "body":
                block.block_type = "dialogue_turn"
    elif section_type == "language_focus":
        block.block_type = "grammar_point"
    elif section_type == "culture":
        block.block_type = "culture_note"
    elif section_type == "exercise":
        if EXERCISE_OPTION_RE.match(text):
            block.block_type = "exercise_option"
        elif EXERCISE_ANSWER_RE.search(text):
            block.block_type = "exercise_answer"
        elif text.endswith(("？", "?")) or EXERCISE_Q_RE.match(text):
            block.block_type = "exercise_question"
        elif block.block_type == "body":
            block.block_type = "exercise_question"
    elif section_type in ("unit_title", "lesson_title"):
        block.block_type = section_type  # type: ignore[assignment]


def reconstruct_structure(page_results: list[PageAnalysisResult]) -> TextbookStructure:
    structure = TextbookStructure()
    sections: list[TextbookSection] = []
    current: TextbookSection | None = None

    for pr in page_results:
        for block in sorted(pr.blocks, key=lambda b: b.reading_order or 0):
            text = block.text.strip()
            if not text:
                continue

            if UNIT_RE.search(text) and not structure.unit:
                structure.unit = text
                title_section = TextbookSection(section_type="unit_title", title=text)
                sections.append(title_section)
                block.block_type = "unit_title"
                title_section.block_ids.append(block.id)
                current = None
                continue

            if LESSON_RE.search(text) and not structure.lesson_title:
                structure.lesson_title = text
                title_section = TextbookSection(section_type="lesson_title", title=text)
                sections.append(title_section)
                block.block_type = "lesson_title"
                title_section.block_ids.append(block.id)
                current = None
                continue

            heading = _match_heading(text)
            if heading:
                current = TextbookSection(section_type=heading, title=text)
                sections.append(current)
                if block.block_type in ("title", "heading", "body"):
                    block.block_type = "heading"
                current.block_ids.append(block.id)
                continue

            if current is not None:
                current.block_ids.append(block.id)
                _refine_block_type(block, current.section_type, text)

    structure.sections = sections
    return structure
