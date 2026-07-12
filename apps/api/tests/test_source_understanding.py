"""Tests for the Source Document Understanding / OCR layer.

These cover the five responsibilities called out in the OCR report:
  1. text recognition (with language hints)
  2. layout structure recovery (bbox + reading order)
  3. textbook semantic-unit reconstruction (NOT teaching activities)
  4. non-text asset handling
  5. uncertainty preservation (confidence -> review status, never fabricated)
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from hcs_api.models import (
    OCREvidenceBlock,
    SourceAnalysisResult,
    SourceMaterial,
    VisualAsset,
)
from hcs_api.source_understanding import (
    OCRPolicy,
    PageInput,
    get_engine_status,
    parse_pp_structurev3_result,
    run_source_understanding,
)
from hcs_api.source_understanding.normalization import (
    apply_confidence_policy,
    clean_text,
    normalize_pinyin,
)
from hcs_api.parser import _native_text_is_reliable, parse_source


# ── 1. engine availability ──────────────────────────────────────────────────

def test_engine_status_reports_availability():
    statuses = {s.name: s for s in get_engine_status()}
    assert statuses["native"].available is True
    # paddle engines are dormant unless the heavy deps are installed
    assert "paddle_ocr" in statuses
    assert statuses["paddle_vl"].available is False
    assert "tesseract" in statuses


# ── 2. native path => structured blocks, reading order, confidence 1.0 ──────

def test_native_pipeline_structured_blocks():
    page = PageInput(
        page_number=1,
        width=720,
        height=1280,
        has_native_text=True,
        native_blocks=[
            ("第三课 你叫什么名字", None, "title"),
            ("你叫什么名字？", [0.12, 0.31, 0.83, 0.39], "body"),
            ("nǐ jiào shénme míngzi", [0.12, 0.40, 0.83, 0.45], "body"),
            ("A：我叫李明。", [0.12, 0.50, 0.83, 0.55], "body"),
        ],
    )
    sa = run_source_understanding([page], source_type="pdf")
    assert sa.source_method_summary == {"native": 1}
    assert sa.overall_confidence == 1.0
    assert sa.needs_review_count == 0

    blocks = sorted(sa.pages[0].blocks, key=lambda b: b.reading_order or 0)
    # reading order: positioned blocks first (by top), title (no bbox) last
    assert blocks[0].text == "你叫什么名字？"
    assert blocks[0].language_hint == "zh"
    assert blocks[1].language_hint == "pinyin"
    assert all(b.source_method == "native" for b in sa.pages[0].blocks)
    # pinyin misalignment warning surfaces when hanzi appear in a pinyin line
    assert all(b.confidence == 1.0 for b in sa.pages[0].blocks)


# ── 3. scanned page with no usable image => honest pending, needs_review ─────

def test_scanned_no_text_is_flagged_not_fabricated():
    page = PageInput(page_number=2, has_native_text=False, native_blocks=[], image=None)
    sa = run_source_understanding([page], source_type="pdf")
    assert sa.source_method_summary == {"tesseract": 1} or sa.needs_review_count >= 1
    pending = sa.pages[0].blocks[0]
    assert pending.text == ""
    assert pending.needs_review is True
    assert any(w.type in ("ocr_unavailable", "ocr_no_text") for w in pending.warnings)


# ── 4. real Tesseract OCR on a rendered image (skipped if no binary) ─────────

@pytest.fixture
def tesseract_image(tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("tesseract binary not installed")
    import fitz

    src = tmp_path / "src.pdf"
    doc = fitz.open()
    p = doc.new_page(width=600, height=200)
    p.insert_text((40, 110), "Hello World 123", fontsize=28)
    doc.save(str(src))
    doc.close()
    d = fitz.open(str(src))
    pix = d[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    img = tmp_path / "scan.png"
    pix.save(str(img))
    d.close()
    return img


def test_scanned_image_ocr_and_crop(tesseract_image, tmp_path):
    sm = parse_source(tesseract_image, tmp_path, "scan.png")
    sa = sm.source_analysis
    assert set(sa.source_method_summary).issubset({"paddle_ocr", "tesseract"})
    text = " ".join(b.text for b in sa.pages[0].blocks)
    assert "Hello" in text and "World" in text
    # evidence crop should be written for the recognized block
    assert any(b.source_crop for b in sa.pages[0].blocks)
    assert (tmp_path / "assets" / "ocr_crops").exists()


# ── 5. PP-StructureV3 mapping (no paddle install required) ──────────────────

def test_pp_structurev3_mapping():
    fake = {
        "res": [
            {"type": "title", "bbox": [10, 10, 200, 40], "res": "第一课", "score": 0.98, "layout_order": 1},
            {"type": "text", "bbox": [10, 50, 300, 80], "res": "你好，世界。", "score": 0.95, "layout_order": 2},
            {"type": "figure", "bbox": [10, 90, 200, 300], "score": 0.9},
            {"type": "table", "bbox": [220, 90, 500, 300], "score": 0.92},
        ]
    }
    blocks, assets = parse_pp_structurev3_result(fake, PageInput(page_number=1, width=600, height=800))
    texts = [(b.text, b.block_type, b.confidence) for b in blocks]
    assert ("第一课", "title", 0.98) in texts
    assert ("你好，世界。", "body", 0.95) in texts
    # table becomes both a marker block and a visual asset
    assert any(b.block_type == "table" for b in blocks)
    assert any(a.asset_type == "table" for a in assets)
    assert any(a.asset_type == "illustration" for a in assets)


# ── 6. confidence thresholds => explicit review status ──────────────────────

def test_confidence_policy_thresholds():
    policy = OCRPolicy()
    high = OCREvidenceBlock(id="b1", page_number=1, text="x", confidence=0.95)
    mid = OCREvidenceBlock(id="b2", page_number=1, text="x", confidence=0.75)
    low = OCREvidenceBlock(id="b3", page_number=1, text="x", confidence=0.5)
    apply_confidence_policy(high, policy.high_confidence, policy.medium_confidence)
    apply_confidence_policy(mid, policy.high_confidence, policy.medium_confidence)
    apply_confidence_policy(low, policy.high_confidence, policy.medium_confidence)
    assert high.review_status == "auto" and not high.needs_review
    assert mid.review_status == "auto"
    assert any(w.type == "medium_confidence" for w in mid.warnings)
    assert low.needs_review is True and low.review_status == "needs_review"


def test_clean_text_and_pinyin():
    assert clean_text("  你\t叫 什么  \n") == "你 叫 什么"
    blk = OCREvidenceBlock(id="p", page_number=1, text="nǐ hǎo   world", language_hint="pinyin")
    normalize_pinyin(blk)
    assert blk.text == "nǐ hǎo world"
    mixed = OCREvidenceBlock(id="q", page_number=1, text="nǐ hǎo 你", language_hint="mixed")
    normalize_pinyin(mixed)
    assert any(w.type == "pinyin_hanzi_misalignment" for w in mixed.warnings)


# ── 7. header / footer dedupe across pages ──────────────────────────────────

def test_repeated_margin_blocks_tagged():
    pages = []
    for n in range(1, 4):
        pages.append(PageInput(
            page_number=n,
            has_native_text=True,
            native_blocks=[
                ("My Textbook", [0.1, 0.02, 0.9, 0.06], "body"),  # repeated header
                (f"正文内容 page {n}", [0.1, 0.3, 0.9, 0.4], "body"),
            ],
        ))
    sa = run_source_understanding(pages, source_type="pdf")
    headers = [b for pr in sa.pages for b in pr.blocks if b.block_type == "header"]
    assert len(headers) == 3
    assert all(b.text.startswith("My Textbook") for b in headers)


# ── 8. textbook structure reconstruction (vocabulary + dialogue) ─────────────

def test_structure_dialogue_and_vocabulary():
    page = PageInput(
        page_number=1,
        has_native_text=True,
        native_blocks=[
            ("生词", [0.1, 0.1, 0.3, 0.14], "body"),
            ("你好 nǐ hǎo hello", [0.1, 0.16, 0.6, 0.2], "body"),
            ("对话", [0.1, 0.3, 0.3, 0.34], "body"),
            ("A：你好！", [0.1, 0.36, 0.6, 0.4], "body"),
            ("B：你好！", [0.1, 0.42, 0.6, 0.46], "body"),
        ],
    )
    sa = run_source_understanding([page], source_type="pdf")
    types = {s.section_type for s in sa.textbook_structure.sections}
    assert "vocabulary" in types
    assert "dialogue" in types
    turns = [b for b in sa.pages[0].blocks if b.block_type == "dialogue_turn"]
    assert len(turns) == 2
    assert turns[0].speaker == "A"
    vocab = [b for b in sa.pages[0].blocks if b.block_type == "vocabulary_item"]
    assert vocab and "你好" in vocab[0].text


# ── 9. serialization round-trip via SourceMaterial ──────────────────────────

def test_source_material_serialization_roundtrip():
    page = PageInput(page_number=1, has_native_text=True,
                     native_blocks=[("第三课", None, "title"), ("你叫什么名字？", [0.1, 0.3, 0.8, 0.4], "body")])
    sa = run_source_understanding([page], source_type="pdf")
    sm = SourceMaterial(source_type="pdf", original_filename="x.pdf",
                        pages=[], source_analysis=sa)
    dumped = sm.model_dump(mode="json")
    restored = SourceMaterial.model_validate(dumped)
    assert restored.source_analysis is not None
    assert restored.source_analysis.schema_ == "hanclassstudio.source_evidence.v1"
    assert restored.source_analysis.pages[0].blocks[0].text == "第三课"


def test_native_text_reliability_rejects_scan_overlays_and_corruption():
    blocks = [("第三课 你好", [0.1, 0.1, 0.8, 0.2], "body")]
    assert _native_text_is_reliable(blocks) is True
    assert _native_text_is_reliable(blocks, has_full_page_image=True) is False
    assert _native_text_is_reliable([("\ufffd\x00\ufffd", None, "body")]) is False


# ── 10. parser integration: native PDF + image upload ───────────────────────

def test_parse_source_pdf_native(tmp_path):
    import fitz

    pdf = tmp_path / "lesson.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((50, 60), "Lesson 3 Greetings", fontsize=20)
    pg.insert_text((50, 110), "Hello, world!")
    doc.save(str(pdf))
    doc.close()

    sm = parse_source(pdf, tmp_path, "lesson.pdf")
    assert sm.source_analysis is not None
    assert sm.source_analysis.source_method_summary == {"native": 1}
    assert sm.pages[0].ocr_text  # legacy field still derived for downstream compat
    assert sm.pages[0].text_blocks
    assert "evidence_blocks" not in sm.pages[0].model_dump()
    assert not list((tmp_path / "assets" / "ocr_render").glob("*.png"))


def test_parse_source_image_upload(tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("tesseract binary not installed")
    import fitz

    src = tmp_path / "src.pdf"
    doc = fitz.open()
    p = doc.new_page(width=600, height=200)
    p.insert_text((40, 110), "Hello World 123", fontsize=28)
    doc.save(str(src))
    doc.close()
    d = fitz.open(str(src))
    pix = d[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    img = tmp_path / "scan.png"
    pix.save(str(img))
    d.close()

    sm = parse_source(img, tmp_path, "scan.png")
    assert sm.source_type == "image"
    assert sm.source_analysis is not None
