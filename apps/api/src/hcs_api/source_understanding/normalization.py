"""Text cleaning and confidence normalization for recognized blocks.

The OCR layer must never silently ship low-quality recognition into teaching
content. These helpers collapse whitespace, normalize pinyin spacing, and turn
confidence scores into explicit review decisions (auto / needs_review).
"""

from __future__ import annotations

import re
import unicodedata

from hcs_api.models import OCREvidenceBlock, OCREvidenceWarning

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"))
_WS = re.compile(r"[ \t]+")


def clean_text(text: str) -> str:
    """Trim, drop zero-width chars, collapse internal spaces. Keep line breaks."""
    if not text:
        return ""
    text = text.translate(_ZERO_WIDTH)
    text = unicodedata.normalize("NFC", text)
    text = _WS.sub(" ", text)
    return text.strip()


_PINYIN_RUN = re.compile(r"^[A-Za-zà-ɏ]+$")


def normalize_pinyin(block: OCREvidenceBlock) -> None:
    """Ensure pinyin tokens are single-space separated and flag misalignment.

    A common textbook failure is hanzi/pinyin interleaving where the pinyin line
    drifts out of alignment with the characters. We do not "fix" it (that would
    be fabrication); we surface a warning so a teacher verifies it.
    """
    if block.language_hint not in ("pinyin", "mixed"):
        return
    tokens = block.text.split()
    norm = " ".join(tokens)
    if norm != block.text:
        block.text = norm
    # pinyin line that also contains hanzi -> likely misalignment
    if re.search(r"[一-鿿]", block.text):
        block.warnings.append(OCREvidenceWarning(
            type="pinyin_hanzi_misalignment",
            message="Pinyin block contains hanzi; verify pinyin/character alignment.",
        ))


def apply_confidence_policy(block: OCREvidenceBlock, high: float, medium: float) -> None:
    """Convert a confidence score into an explicit review decision."""
    conf = block.confidence
    if conf >= high:
        block.review_status = "auto"
    elif conf >= medium:
        block.review_status = "auto"
        if not any(w.type == "medium_confidence" for w in block.warnings):
            block.warnings.append(OCREvidenceWarning(
                type="medium_confidence",
                confidence=round(conf, 3),
                message="Medium confidence; verify before generating key teaching content.",
            ))
    else:
        block.needs_review = True
        block.review_status = "needs_review"
        if not any(w.type == "low_confidence" for w in block.warnings):
            block.warnings.append(OCREvidenceWarning(
                type="low_confidence",
                confidence=round(conf, 3),
                message="Low confidence; blocked from automatic key-content generation.",
            ))
