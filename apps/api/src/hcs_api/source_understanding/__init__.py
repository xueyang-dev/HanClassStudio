"""Source Document Understanding — the OCR layer at the front of the workflow.

This package turns raw teaching material (PDF / PPTX / scanned page images) into
a structured, evidence-preserving Source Evidence Model. It is deliberately
separated from the Learner Analysis / State-Evidence Kernel: it answers only
"what is in the source material?", never "how should this be taught?".

Current pipeline stages (see ``pipeline.run_source_understanding``):

    1. document_ingestion      — raw pages become normalized ``PageInput``
    2. text_recognition        — native text, PP-OCRv6, or Tesseract fallback
    3. reading_order           — geometry-based ordering and margin tagging
    4. structure_reconstruction— conservative textbook units, not pedagogy
    5. source_normalization    — cleaning and explicit review thresholds

Engines degrade gracefully: if PaddleOCR is not installed, scanned pages fall
back to Tesseract. PaddleOCR-VL remains explicitly disabled until validated.
"""

from __future__ import annotations

from .backends import (
    EngineStatus,
    NativeTextEngine,
    OCREngine,
    PaddleOCREngine,
    PaddleVLEngine,
    RawBlock,
    RawVisualAsset,
    TesseractEngine,
    get_engine_status,
    parse_pp_structurev3_result,
)
from .pipeline import (
    OCRPolicy,
    PageInput,
    run_source_understanding,
)

__all__ = [
    "NativeTextEngine",
    "TesseractEngine",
    "PaddleOCREngine",
    "PaddleVLEngine",
    "OCREngine",
    "RawBlock",
    "RawVisualAsset",
    "EngineStatus",
    "get_engine_status",
    "parse_pp_structurev3_result",
    "OCRPolicy",
    "PageInput",
    "run_source_understanding",
]
