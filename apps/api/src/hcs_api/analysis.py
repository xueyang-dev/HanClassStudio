"""Teaching Candidate Extraction — analyse source material for lesson building."""

from __future__ import annotations

import re
from collections import Counter

from pypinyin import Style, lazy_pinyin

from .models import (
    RouteHint,
    SourceMaterial,
    TeachingCandidates,
)


# High-priority greeting words — these are core for greeting_lesson route
GREETING_WORDS = {"你好", "您好", "你", "您", "你们", "好", "再见", "谢谢", "不客气", "对不起", "没关系"}

# Stroke/numeral noise — not real vocabulary in teaching context
STROKE_NOISE = {"一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "横", "竖", "撇", "捺", "点", "提", "折", "钩"}

# Common teaching framework words — noise in most lessons
FRAMEWORK_NOISE = {"第", "课", "的", "了", "是", "不", "在", "有", "和", "也", "都", "就", "很", "会", "能", "要", "可", "以", "没", "对", "个"}

# Generic high-frequency Chinese functional words
GENERIC_FUNCTIONAL = {"学习", "中文", "老师", "同学", "学校", "上课", "下课", "作业", "考试", "问题", "答案", "练习", "复习", "预习", "学生"}

DIALOGUE_PATTERN = re.compile(r"([A-Ga-g]|[啊-嗯])[：:]\s*(.+?)(?=(?:[A-Ga-g]|[啊-嗯])[：:]|\Z)", re.DOTALL)
DIALOGUE_LINE = re.compile(r"^[A-Za-z\u4e00-\u9fff][：:]\s*(.*)", re.MULTILINE)

POLITENESS_PATTERN = re.compile(r"(你|您|你好|您好)", re.UNICODE)

IN_ZAI_NE_PATTERN = re.compile(r"在.*?呢")
LE_PATTERN = re.compile(r"(?:了|V\s*\+\s*了)")

CHARACTER_STROKE_PATTERN = re.compile(r"笔画|笔顺|书写|横|竖|撇|捺|点", re.UNICODE)
NUMBER_PATTERN = re.compile(r"\d+")


def extract_candidates(source: SourceMaterial) -> TeachingCandidates:
    """Analyse source material and produce TeachingCandidates."""
    text = _source_text(source)
    all_text = text
    candidates = TeachingCandidates()

    # ── Route hint ──
    candidates.route_hint = _detect_route(all_text, source)

    # ── Vocabulary ──
    core, secondary, noise = _classify_vocabulary(all_text, source, candidates.route_hint)
    candidates.core_vocabulary = core
    candidates.secondary_vocabulary = secondary
    candidates.noise_candidates = noise

    # ── Grammar ──
    candidates.grammar_candidates = _detect_grammar_candidates(all_text)

    # ── Dialogues ──
    candidates.dialogue_candidates = _extract_dialogues(all_text)

    # ── Characters ──
    candidates.character_candidates = _extract_character_candidates(all_text)

    # ── Classroom tasks ──
    candidates.classroom_task_candidates = _extract_tasks(all_text)

    # ── Warnings ──
    candidates.source_warnings = _generate_warnings(candidates, source)

    return candidates


def _source_text(source: SourceMaterial) -> str:
    chunks: list[str] = []
    for page in source.pages:
        if page.title:
            chunks.append(page.title)
        chunks.append(page.content_text())
        if page.notes:
            chunks.append(page.notes)
    return "\n".join(chunk for chunk in chunks if chunk)


# ── Route detection ──

GREETING_SIGNALS = ["你好", "您好", "你", "您", "你们", "问候", "打招呼", "greeting", "hello", "hi"]
DIALOGUE_SIGNALS = ["对话", "说一说", "Talk", " dialogue", "Dialogue", "A：", "B：", "A:", "B:"]
CHARACTER_SIGNALS = ["汉字", "笔画", "笔顺", "书写", "stroke", "character"]
VOCAB_SIGNALS = ["生词", "词汇", "词语", "vocabulary", "word", "词卡"]
GRAMMAR_SIGNALS = ["语法", "句型", "知识点", "grammar", "pattern"]


def _detect_route(text: str, source: SourceMaterial) -> RouteHint:
    scores: dict[RouteHint, int] = {
        "greeting_lesson": 0,
        "vocabulary_lesson": 0,
        "dialogue_lesson": 0,
        "character_lesson": 0,
        "grammar_pattern_lesson": 0,
        "mixed_lesson": 1,
    }

    # Check page titles and first blocks for greeting focus
    for page in source.pages:
        title_lower = page.title.lower()
        if any(g.lower() in title_lower for g in ["你好", "您好", "你", "greeting", "hello", "第1课", "lesson 1"]):
            scores["greeting_lesson"] += 3
        if any(d.lower() in title_lower for d in ["对话", "dialogue"]):
            scores["dialogue_lesson"] += 2
        if any(c.lower() in title_lower for c in ["汉字", "笔画", "character"]):
            scores["character_lesson"] += 3

    # Count signals in full text
    greeting_count = sum(text.count(s) for s in GREETING_SIGNALS)
    scores["greeting_lesson"] += greeting_count // 2
    if "A：" in text or "B：" in text:
        scores["dialogue_lesson"] += 2
    if "对话" in text or "dialogue" in text.lower():
        scores["dialogue_lesson"] += 2
    for signal in CHARACTER_SIGNALS:
        if signal in text:
            scores["character_lesson"] += 2
    for signal in VOCAB_SIGNALS:
        if signal in text:
            scores["vocabulary_lesson"] += 1
    for signal in GRAMMAR_SIGNALS:
        if signal in text:
            scores["grammar_pattern_lesson"] += 2

    # If multiple high scores, default to mixed
    top = sorted(scores.items(), key=lambda x: -x[1])
    if top[0][1] >= 4 and top[0][1] > top[1][1] * 1.5:
        return top[0][0]

    return "mixed_lesson"


# ── Vocabulary classification ──

def _classify_vocabulary(
    text: str, source: SourceMaterial, route: RouteHint
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """Return (core_vocab, secondary_vocab, noise)."""

    # Extract all Chinese word candidates (1-4 characters)
    raw_candidates = re.findall(r"[\u4e00-\u9fff]{1,4}", text)
    counter = Counter(raw_candidates)

    # Build context: which words appear near pinyin, English gloss, or examples?
    has_pinyin_nearby = _words_near_pattern(text, r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]+")
    has_example_nearby = _words_near_pattern(text, r"(?:例如|比如|例如|e\.g\.|example|例)")
    has_meaning_nearby = _words_near_pattern(text, r"(?:意思|释义|meaning|means|definition)")

    # Words in dialogue lines get higher priority
    dialogue_words: set[str] = set()
    for m in re.finditer(r"[A-Za-z\u4e00-\u9fff][：:]\s*(.*)", text):
        line = m.group(1)
        dialogue_words.update(re.findall(r"[\u4e00-\u9fff]{1,4}", line))

    core: list[dict[str, str]] = []
    secondary: list[dict[str, str]] = []
    noise: list[str] = []

    seen = set()

    for word, freq in counter.most_common(30):
        if word in seen or len(word) < 1:
            continue
        seen.add(word)

        # Skip pure stroke/noise in non-character lessons
        if word in STROKE_NOISE:
            if route != "character_lesson":
                noise.append(word)
                continue
            else:
                secondary.append({"word": word, "pinyin": "", "meaning": ""})
                continue

        # Skip framework noise
        if word in FRAMEWORK_NOISE and freq <= 3:
            noise.append(word)
            continue

        # A greeting route should not promote nearby phonetics/explanation text
        # into target vocabulary merely because OCR placed it near pinyin.
        if route == "greeting_lesson" and word not in GREETING_WORDS:
            noise.append(word)
            continue

        # Determine if core or secondary
        is_greeting = word in GREETING_WORDS
        in_dialogue = word in dialogue_words
        has_pinyin = word in has_pinyin_nearby
        has_example = word in has_example_nearby
        has_meaning = word in has_meaning_nearby
        high_freq = freq >= 2

        pinyin = " ".join(lazy_pinyin(word, style=Style.TONE, neutral_tone_with_five=True)).replace("5", "").strip()

        if is_greeting and route == "greeting_lesson":
            core.append({"word": word, "pinyin": pinyin, "meaning": ""})
        elif (in_dialogue or has_pinyin or has_example or has_meaning) and high_freq:
            core.append({"word": word, "pinyin": pinyin, "meaning": ""})
        elif freq >= 2 and word not in GENERIC_FUNCTIONAL:
            secondary.append({"word": word, "pinyin": pinyin, "meaning": ""})
        elif word in GENERIC_FUNCTIONAL and freq >= 3:
            secondary.append({"word": word, "pinyin": pinyin, "meaning": ""})
        else:
            noise.append(word)

    # Ensure greeting lesson has core greeting words even if not detected
    if route == "greeting_lesson":
        existing = {v["word"] for v in core}
        for gw in ["你好", "您好", "你", "您", "你们", "好"]:
            if gw not in existing and gw in text:
                pinyin = " ".join(lazy_pinyin(gw, style=Style.TONE, neutral_tone_with_five=True)).replace("5", "").strip()
                core.append({"word": gw, "pinyin": pinyin, "meaning": ""})
                existing.add(gw)

    return core[:10], secondary[:8], noise


def _words_near_pattern(text: str, pattern: str, window: int = 80) -> set[str]:
    """Find Chinese words that appear within `window` chars of a pattern match."""
    result: set[str] = set()
    for m in re.finditer(pattern, text):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        context = text[start:end]
        result.update(re.findall(r"[\u4e00-\u9fff]{1,4}", context))
    return result


# ── Grammar detection ──

GRAMMAR_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"在.*?呢"), "sb. + 在 + V + 呢", "正在进行时"),
    (re.compile(r"V\s*\+\s*了"), "V + 了", "动作完成"),
    (re.compile(r"了(?![a-zA-Z])"), "V + 了", "动作完成"),
    (re.compile(r"喜欢"), "sb. + 喜欢 + noun / verb", "表达喜好"),
    (re.compile(r"会"), "sb. + 会 + V", "能力"),
    (re.compile(r"想"), "sb. + 想 + V", "意愿"),
    (re.compile(r"是"), "A + 是 + B", "判断"),
    (re.compile(r"有"), "sb. + 有 + noun", "拥有"),
    (re.compile(r"在\s"), "sb. + 在 + PLACE", "所在位置"),
    (re.compile(r"吗"), "S + V + O + 吗？", "疑问句"),
    (re.compile(r"不"), "sb. + 不 + V", "否定"),
    (re.compile(r"很"), "sb. + 很 + adj.", "程度"),
    (re.compile(r"和"), "A + 和 + B", "并列"),
]


def _detect_grammar_candidates(text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen = set()
    for pattern, label, note in GRAMMAR_RULES:
        if pattern.search(text) and label not in seen:
            candidates.append({"pattern": label, "note": note, "source": "inferred"})
            seen.add(label)
    # Check for politeness contrast
    if "你" in text and "您" in text and "您" not in {c["pattern"] for c in candidates}:
        candidates.append({"pattern": "你 vs 您", "note": "礼貌对比", "source": "politeness_detected"})
    return candidates


# ── Dialogue extraction ──

def _extract_dialogues(text: str) -> list[dict[str, str]]:
    dialogues: list[dict[str, str]] = []
    lines: list[str] = []
    for m in DIALOGUE_LINE.finditer(text):
        line = m.group(1).strip()
        if line and len(line) <= 100:
            lines.append(line)
    if lines:
        speaker = "A"
        for line in lines:
            dialogues.append({"speaker": speaker, "text": line})
            speaker = "B" if speaker == "A" else "A"
    return dialogues


# ── Character candidates ──

def _extract_character_candidates(text: str) -> list[str]:
    if CHARACTER_STROKE_PATTERN.search(text):
        found = re.findall(r"[\u4e00-\u9fff]", text)
        # Pick the most frequent characters that aren't pure noise
        counter = Counter(c for c in found if c not in FRAMEWORK_NOISE and c not in STROKE_NOISE)
        return [c for c, _ in counter.most_common(6)]
    return []


# ── Task candidates ──

TASK_SIGNALS = ["说一说", "读一读", "写一写", "听一听", "选一选", "连一连", "做一做", "演一演",
                "Talk", "Read", "Write", "Listen", "Choose", "Match", "Practice", "Role-play"]


def _extract_tasks(text: str) -> list[str]:
    tasks = []
    for signal in TASK_SIGNALS:
        count = text.count(signal)
        if count > 0:
            tasks.append(signal)
            if count > 1:
                tasks.append(f"{signal} (×{count})")
    seen = set()
    deduped = []
    for t in tasks:
        base = t.split(" (")[0]
        if base not in seen:
            deduped.append(t)
            seen.add(base)
    return deduped


# ── Warnings ──

def _generate_warnings(candidates: TeachingCandidates, source: SourceMaterial) -> list[str]:
    warnings = []
    if not candidates.core_vocabulary:
        warnings.append("未能从素材中提取核心词汇，将使用默认词表。")
    if not candidates.dialogue_candidates:
        warnings.append("未检测到对话结构，对话练习将基于核心词汇生成。")
    if len(candidates.core_vocabulary) <= 2:
        warnings.append("核心词汇数过少（≤2），建议补充教学材料。")
    if any(w in STROKE_NOISE for w in [v["word"] for v in candidates.core_vocabulary]):
        warnings.append("核心词汇中包含疑似笔画/数字噪声，可能提取不准确。")
    return warnings
