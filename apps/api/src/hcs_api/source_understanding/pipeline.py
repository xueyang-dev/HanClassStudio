"""OCR / Source Document Understanding pipeline.

``run_source_understanding`` is the single entry point. It consumes a list of
``PageInput`` (built by the parser from PDF / PPTX / images) and returns a
structured ``SourceAnalysisResult`` (the normalized source contract) that is
stored on ``SourceMaterial.source_analysis``.

Design rules honored from the OCR report:
  * Keep structured output with bbox / reading order / confidence / source_method.
  * Never fabricate text or confidence — missing engines => needs_review.
  * PaddleOCR-VL is only a fallback for hard pages; it never overwrites good OCR.
  * This layer only describes the source; it does not plan teaching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hcs_api.models import (
    OCREvidenceBlock,
    OCREvidenceWarning,
    PageAnalysisResult,
    SourceAnalysisResult,
    SourceMethod,
    VisualAsset,
    VisualAssetType,
)
from .backends import (
    NativeTextEngine,
    PaddleOCREngine,
    PaddleVLEngine,
    RawBlock,
    RawVisualAsset,
    TesseractEngine,
    detect_language,
)
from .layout import assign_reading_order, find_repeated_margin_blocks
from .normalization import apply_confidence_policy, clean_text, normalize_pinyin
from .structure import reconstruct_structure

PIPELINE_STAGES = [
    "document_ingestion",
    "text_recognition",
    "reading_order",
    "structure_reconstruction",
    "source_normalization",
]


@dataclass
class PageInput:
    """Normalized per-page input handed to the pipeline by the parser."""

    page_number: int
    width: float | None = None  # pixel/page-unit width, for bbox normalization
    height: float | None = None
    # Reliable native text layer: (text, bbox_normalized_or_None, kind)
    native_blocks: list[tuple[str, list[float] | None, str]] = field(default_factory=list)
    # Rendered page image (bytes or path) for OCR + visual extraction
    image: bytes | str | Path | None = None
    # Embedded image crops already saved by the parser: (rel_path, bbox_or_None)
    embedded_images: list[tuple[str, list[float] | None]] = field(default_factory=list)
    has_native_text: bool = False
    is_whole_image: bool = False  # True for image uploads (page == the image)
    title: str = ""


@dataclass
class OCRPolicy:
    """Knobs for the layered OCR strategy."""

    preferred_ocr: SourceMethod = "paddle_ocr"
    fallback_order: tuple[SourceMethod, ...] = ("tesseract",)
    # ponytail: keep the unvalidated VLM path off until it has a real backend
    # and provenance-preserving merge tests.
    enable_vl_fallback: bool = False
    high_confidence: float = 0.9
    medium_confidence: float = 0.7
    vl_fallback_confidence: float = 0.6
    tesseract_langs: str = "chi_sim+eng"
    crop_evidence: bool = True  # save per-block crops for teacher review


def _build_engines() -> dict[SourceMethod, Any]:
    return {
        "native": NativeTextEngine(),
        "tesseract": TesseractEngine(),
        "paddle_ocr": PaddleOCREngine(),
        "paddle_vl": PaddleVLEngine(),
    }


def _select_scanned_engine(policy: OCRPolicy, engines: dict[SourceMethod, Any]):
    preferred = engines.get(policy.preferred_ocr)
    if preferred is not None and preferred.available():
        return preferred
    for name in policy.fallback_order:
        eng = engines.get(name)
        if eng is not None and eng.available():
            return eng
    return None


def _recognize_page(page: PageInput, policy: OCRPolicy, engines: dict[SourceMethod, Any]
                    ) -> tuple[list[RawBlock], list[RawVisualAsset], SourceMethod]:
    if page.has_native_text and page.native_blocks:
        blocks, visuals = engines["native"].recognize(page, policy)
        return blocks, visuals, "native"

    engine = _select_scanned_engine(policy, engines)
    if engine is None:
        pending = RawBlock(
            text="",
            bbox=None,
            block_type="other",
            confidence=0.0,
            warnings=[{
                "type": "ocr_unavailable",
                "message": "No OCR engine available for this scanned/imageless page; manual text entry required.",
            }],
        )
        return [pending], [], "unavailable"

    blocks, visuals = engine.recognize(page, policy)
    if not blocks:
        # Engine ran (or had no image) but recognized nothing. Surface this
        # honestly instead of silently dropping the page.
        pending = RawBlock(
            text="",
            bbox=None,
            block_type="other",
            confidence=0.0,
            warnings=[{
                "type": "ocr_no_text",
                "message": "OCR engine ran but found no text; confirm whether the page is image-only or needs manual entry.",
            }],
        )
        return [pending], visuals, engine.name
    method: SourceMethod = engine.name

    return blocks, visuals, method


def _wrap_block(raw: RawBlock, page_number: int, index: int, method: SourceMethod,
                policy: OCRPolicy) -> OCREvidenceBlock:
    block = OCREvidenceBlock(
        id=f"page_{page_number}_block_{index:02d}",
        page_number=page_number,
        block_type=raw.block_type,
        text=clean_text(raw.text),
        bbox=raw.bbox,
        reading_order=raw.reading_order,
        confidence=raw.confidence,
        source_method=method,
        speaker=raw.speaker,
        language_hint=raw.language_hint,
        alternatives=raw.alternatives,
    )
    for w in raw.warnings:
        block.warnings.append(OCREvidenceWarning(**w))
    normalize_pinyin(block)
    apply_confidence_policy(block, policy.high_confidence, policy.medium_confidence)
    return block


def _crop_block(page: PageInput, block: OCREvidenceBlock, project_root: str | Path) -> str:
    """Render the block's page region to a small PNG crop for teacher review."""
    img = page.image
    if not img or not block.bbox:
        return ""
    try:
        import fitz

        stream = img if isinstance(img, (bytes, bytearray)) else None
        doc = fitz.open(stream=stream, filetype="png") if stream else fitz.open(str(img))
        pg = doc[0]
        w, h = pg.rect.width, pg.rect.height
        x0, y0, x1, y1 = block.bbox
        clip = fitz.Rect(x0 * w, y0 * h, x1 * w, y1 * h)
        pix = pg.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2))
        out_dir = Path(project_root) / "assets" / "ocr_crops"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{block.id}.png"
        pix.save(str(out_path))
        return f"assets/ocr_crops/{block.id}.png"
    except Exception:
        return ""


def _embedded_assets(page: PageInput) -> list[VisualAsset]:
    assets: list[VisualAsset] = []
    if page.is_whole_image:
        return assets  # the image is the page, not a figure within it
    for j, (rel_path, bbox) in enumerate(page.embedded_images, start=1):
        assets.append(VisualAsset(
            id=f"page_{page.page_number}_asset_{j:02d}",
            page_number=page.page_number,
            asset_type="illustration",
            bbox=bbox,
            crop_path=rel_path,
            confidence=1.0,
        ))
    return assets


def _dominant_language(blocks: list[OCREvidenceBlock]) -> str:
    counts: dict[str, int] = {}
    for b in blocks:
        hint = b.language_hint or detect_language(b.text)
        if hint:
            counts[hint] = counts.get(hint, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _build_notes(page_results: list[PageAnalysisResult], engines: dict[SourceMethod, Any],
                 policy: OCRPolicy, had_scanned: bool) -> list[str]:
    notes: list[str] = []
    if not engines["paddle_ocr"].available():
        notes.append(
            "PP-OCRv6 (paddle_ocr) not installed; scanned pages use Tesseract. "
            "Install the project's 'ocr' extra for the preferred Chinese text engine."
        )
    if had_scanned and not engines["tesseract"].available():
        notes.append("No OCR engine is available for scanned pages; those pages are flagged needs_review.")
    if had_scanned and engines["tesseract"].available() and not engines["tesseract"].supports_chinese():
        notes.append("Tesseract has no chi_sim traineddata; install it for reliable Chinese recognition.")
    if had_scanned and policy.enable_vl_fallback:
        notes.append("PaddleOCR-VL fallback is disabled until its backend and provenance merge are validated.")
    return notes


def run_source_understanding(
    pages: list[PageInput],
    source_type: str = "unknown",
    project_root: str | Path | None = None,
    policy: OCRPolicy | None = None,
) -> SourceAnalysisResult:
    """Run the Source Document Understanding pipeline."""
    policy = policy or OCRPolicy()
    engines = _build_engines()

    page_results: list[PageAnalysisResult] = []
    had_scanned = False

    for page in pages:
        blocks_raw, visuals_raw, method = _recognize_page(page, policy, engines)
        if method != "native":
            had_scanned = True

        blocks = [
            _wrap_block(rb, page.page_number, i + 1, method, policy)
            for i, rb in enumerate(blocks_raw)
        ]
        # Per-block source crops for teacher review (scanned / image pages only).
        if method != "native" and policy.crop_evidence and project_root:
            for b in blocks:
                if b.bbox:
                    b.source_crop = _crop_block(page, b, project_root)
        visuals = [
            VisualAsset(
                id=f"page_{page.page_number}_asset_{j + 1:02d}",
                page_number=page.page_number,
                asset_type=v.asset_type,
                bbox=v.bbox,
                crop_path=v.crop_path,
                confidence=v.confidence,
                warnings=[OCREvidenceWarning(**w) for w in v.warnings],
            )
            for j, v in enumerate(visuals_raw)
        ]
        visuals += _embedded_assets(page)

        assign_reading_order(blocks)

        pr = PageAnalysisResult(
            page_number=page.page_number,
            width=page.width,
            height=page.height,
            orientation=0,
            skew_corrected=False,
            has_native_text=page.has_native_text,
            dominant_language=_dominant_language(blocks),
            source_method=method,
            blocks=blocks,
            visual_assets=visuals,
        )
        for b in blocks:
            pr.warnings.extend(b.warnings)
        page_results.append(pr)

    margin_ids = find_repeated_margin_blocks(page_results)
    for pr in page_results:
        for b in pr.blocks:
            if (pr.page_number, b.id) in margin_ids and b.block_type in ("body", "other"):
                b.block_type = "header" if (b.bbox and b.bbox[1] < 0.5) else "footer"

    structure = reconstruct_structure(page_results)

    all_blocks = [b for pr in page_results for b in pr.blocks]
    method_counts: dict[str, int] = {}
    for pr in page_results:
        method_counts[pr.source_method] = method_counts.get(pr.source_method, 0) + 1
    overall = round(sum(b.confidence for b in all_blocks) / len(all_blocks), 3) if all_blocks else 0.0

    sa = SourceAnalysisResult(
        source_method_summary=method_counts,
        pipeline=PIPELINE_STAGES,
        pages=page_results,
        textbook_structure=structure,
        overall_confidence=overall,
        needs_review_count=sum(1 for b in all_blocks if b.needs_review),
        warnings=[w for pr in page_results for w in pr.warnings],
        notes=_build_notes(page_results, engines, policy, had_scanned),
    )
    return sa
