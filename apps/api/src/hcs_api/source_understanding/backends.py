"""Pluggable OCR / recognition backends.

Each backend implements a small protocol:

    name          -> SourceMethod identifier
    available()   -> bool (heavy deps / binaries detected at runtime)
    recognize(page, policy) -> (list[RawBlock], list[RawVisualAsset])

Backends never fabricate text. When a backend is unavailable its ``available()``
returns False and the pipeline selects another engine or marks the page
``needs_review`` instead of inventing characters.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from hcs_api.models import (
    OCREvidenceBlockType,
    SourceMethod,
    VisualAssetType,
)

if TYPE_CHECKING:
    from .pipeline import OCRPolicy, PageInput

# ── Script detection ─────────────────────────────────────────────────────────

_HAN = re.compile(r"[一-鿿]")
_PINYIN = re.compile(r"[À-ɏ]")  # Latin Extended-A/B with tone diacritics
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """Return a coarse language hint: zh | pinyin | ar | en | mixed | ''."""
    if not text:
        return ""
    han = bool(_HAN.search(text))
    pin = bool(_PINYIN.search(text))
    ar = bool(_ARABIC.search(text))
    lat = bool(_LATIN.search(text))
    if han and (pin or lat):
        return "mixed"
    if han:
        return "zh"
    if pin:
        return "pinyin"
    if ar:
        return "ar"
    if lat:
        return "en"
    return ""


# ── Internal recognition result types ───────────────────────────────────────

@dataclass
class RawBlock:
    """Engine-agnostic recognition result before it becomes an OCREvidenceBlock."""

    text: str
    bbox: list[float] | None = None  # normalized [x0,y0,x1,y1] in 0..1
    block_type: OCREvidenceBlockType = "body"
    confidence: float = 1.0
    language_hint: str = ""
    speaker: str = ""
    reading_order: int | None = None
    alternatives: list[str] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


@dataclass
class RawVisualAsset:
    asset_type: VisualAssetType = "unknown"
    bbox: list[float] | None = None
    crop_path: str = ""
    confidence: float = 1.0
    warnings: list[dict] = field(default_factory=list)


# ── Engine protocol ──────────────────────────────────────────────────────────

class OCREngine(Protocol):
    name: SourceMethod

    def available(self) -> bool: ...

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]: ...


# ── Native text-layer engine (always on) ────────────────────────────────────

_CLASS_KIND_MAP: dict[str, OCREvidenceBlockType] = {
    "title": "title",
    "heading": "heading",
    "body": "body",
}


class NativeTextEngine:
    """Uses a reliable native text layer (PDF digital text / PPTX shapes).

    This is the highest-confidence path: no recognition error is possible, so
    confidence is 1.0 and ``source_method`` is ``native``.
    """

    name: SourceMethod = "native"

    def available(self) -> bool:
        return True

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]:
        blocks: list[RawBlock] = []
        for idx, (text, bbox, kind) in enumerate(page.native_blocks, start=1):
            text = (text or "").strip()
            if not text:
                continue
            block_type = _CLASS_KIND_MAP.get(kind, "body")
            blocks.append(
                RawBlock(
                    text=text,
                    bbox=bbox,
                    block_type=block_type,
                    confidence=1.0,
                    language_hint=detect_language(text),
                )
            )
        return blocks, []


# ── Tesseract engine (CPU baseline, optional) ───────────────────────────────

class TesseractEngine:
    """Lightweight CPU baseline using the system ``tesseract`` binary.

    Runs only on scanned pages / images. Chinese requires the ``chi_sim``
    traineddata; if it is missing, the engine still runs (Latin) but every
    Chinese-heavy page will surface as low-confidence + needs_review, which is
    the honest outcome rather than silent misrecognition.
    """

    name: SourceMethod = "tesseract"

    def __init__(self) -> None:
        self._binary = shutil.which("tesseract")
        self._supports_chinese = False
        if self._binary:
            try:
                proc = subprocess.run(
                    [self._binary, "--list-langs"],
                    capture_output=True, text=True, timeout=20,
                )
                # tesseract writes the language list to stdout on macOS and to
                # stderr on some Linux builds; check both.
                out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                self._supports_chinese = "chi_sim" in out
            except Exception:
                self._supports_chinese = False

    def available(self) -> bool:
        return bool(self._binary)

    def supports_chinese(self) -> bool:
        return self._supports_chinese

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]:
        if not self._binary or page.image is None:
            return [], []
        lang = "chi_sim+eng" if self._supports_chinese else "eng"
        img_path = self._prepare_image(page.image)
        if img_path is None:
            return [], []
        try:
            proc = subprocess.run(
                [self._binary, str(img_path), "stdout", "-l", lang, "--psm", "3", "tsv"],
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return [], []
        finally:
            if isinstance(page.image, (bytes, bytearray)):
                try:
                    img_path.unlink()
                except Exception:
                    pass

        if not self._supports_chinese:
            # Latin-only model on a Chinese page -> the result will be poor.
            pass  # warnings are attached during normalization via low confidence

        blocks = self._parse_tsv(proc.stdout, page)
        if not self._supports_chinese:
            for b in blocks:
                b.warnings.append({
                    "type": "ocr_engine_limited",
                    "message": "Tesseract has no chi_sim model; Chinese recognition unreliable.",
                })
        return blocks, []

    # ── helpers ──

    def _prepare_image(self, image) -> "str | None":
        if isinstance(image, (str, Path)):
            return str(image)
        if isinstance(image, (bytes, bytearray)):
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                    fh.write(bytes(image))
                    return fh.name
            except Exception:
                return None
        return None

    def _parse_tsv(self, tsv: str, page: "PageInput") -> list[RawBlock]:
        lines = tsv.splitlines()
        if not lines:
            return []
        header = lines[0].split("\t")
        if header[0] != "level":
            return []
        idx = {name: i for i, name in enumerate(header)}
        w = float(page.width or 0) or 1.0
        h = float(page.height or 0) or 1.0

        # Group word-level (level==5) rows by block/par/line.
        groups: dict[tuple[int, int, int], list[list[str]]] = {}
        order: list[tuple[int, int, int]] = []
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) <= idx.get("text", -1):
                continue
            if int(cols[idx["level"]]) != 5:
                continue
            key = (int(cols[idx["block_num"]]), int(cols[idx["par_num"]]), int(cols[idx["line_num"]]))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(cols)

        blocks: list[RawBlock] = []
        for reading_order, key in enumerate(order, start=1):
            words = groups[key]
            texts, confs, xs0, ys0, xs1, ys1 = [], [], [], [], [], []
            for cols in words:
                try:
                    conf = float(cols[idx["conf"]])
                    left = int(cols[idx["left"]])
                    top = int(cols[idx["top"]])
                    ww = int(cols[idx["width"]])
                    hh = int(cols[idx["height"]])
                except (ValueError, IndexError):
                    continue
                txt = cols[idx["text"]].strip()
                if not txt:
                    continue
                texts.append(txt)
                if conf >= 0:
                    confs.append(conf)
                xs0.append(left); ys0.append(top)
                xs1.append(left + ww); ys1.append(top + hh)
            if not texts:
                continue
            line_text = " ".join(texts)
            x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
            bbox = [
                round(x0 / w, 4), round(y0 / h, 4),
                round(x1 / w, 4), round(y1 / h, 4),
            ]
            conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
            blocks.append(
                RawBlock(
                    text=line_text,
                    bbox=bbox,
                    block_type="body",
                    confidence=round(conf, 3),
                    language_hint=detect_language(line_text),
                    warnings=(
                        [{"type": "low_confidence_line", "confidence": round(conf, 3)}]
                        if conf < 0.6 else []
                    ),
                )
            )
        return blocks


# ── PaddleOCR / PP-StructureV3 engine (default for scanned pages, optional) ──

def parse_pp_structurev3_result(result: dict, page: "PageInput") -> tuple[list[RawBlock], list[RawVisualAsset]]:
    """Map a PP-StructureV3 (paddleocr 3.x) result dict into RawBlock / RawVisualAsset.

    paddleocr 3.x ``PPStructureV3`` returns, per page, a dict shaped like::

        {
          "input_path": ...,
          "page_index": 0,
          "output": [
            {
              "layout_bbox": [x1, y1, x2, y2],     # pixel coords
              "layout_label": "title"|"text"|"table"|"figure"|"formula"|"seal",
              "score": 0.99,
              "layout_order": 1,
              "ocr": {"rec_texts": [...], "rec_scores": [...], "rec_polys": [...]},
              "table": {...}                        # present for table regions
            }, ...
          ]
        }

    The mapper is defensive: it also tolerates 2.x-style keys (``type``/``bbox``/
    ``res``) so older dumps still parse. Unknown keys are ignored, never crashed on.
    """
    w = float(page.width or 0) or 1.0
    h = float(page.height or 0) or 1.0
    regions = (
        result.get("output") or result.get("res")
        or result.get("layout") or result.get("regions") or []
    )
    blocks: list[RawBlock] = []
    assets: list[RawVisualAsset] = []

    type_map = {
        "title": "title",
        "text": "body",
        "header": "header",
        "footer": "footer",
        "formula": "formula",
        "seal": "other",
        "table": "table",
        "figure": "other",
        "image": "other",
    }

    for region in regions:
        rtype = (region.get("layout_label") or region.get("type") or "text").lower()
        bbox_px = (
            region.get("layout_bbox") or region.get("bbox") or region.get("points")
        )
        if not bbox_px or len(bbox_px) < 4:
            continue
        # bbox may be [x0,y0,x1,y1] or a 4-point quad.
        if isinstance(bbox_px[0], (list, tuple)):
            xs = [p[0] for p in bbox_px]
            ys = [p[1] for p in bbox_px]
        else:
            xs = bbox_px[0::2]
            ys = bbox_px[1::2]
        bbox = [round(min(xs) / w, 4), round(min(ys) / h, 4),
                round(max(xs) / w, 4), round(max(ys) / h, 4)]
        score = float(region.get("score") or region.get("confidence") or 0.9)
        raw_order = region.get("layout_order") or region.get("order")
        order = int(raw_order) if isinstance(raw_order, int) else None

        if rtype in {"table", "figure", "image", "seal"}:
            asset_type = "table" if rtype == "table" else ("unknown" if rtype == "seal" else "illustration")
            assets.append(RawVisualAsset(asset_type=asset_type, bbox=bbox, confidence=score))
            if rtype == "table":
                # Keep a lightweight marker block so structure reconstruction sees it.
                blocks.append(RawBlock(text="[table]", bbox=bbox, block_type="table", confidence=score))
            continue

        # Text region: prefer structured OCR (texts + per-line scores).
        ocr = region.get("ocr") or {}
        texts = ocr.get("rec_texts") or []
        scores = ocr.get("rec_scores") or []
        if texts:
            text = "\n".join(t for t in texts if t)
            if scores:
                conf = sum(float(s) for s in scores) / len(scores)
            else:
                conf = score
        else:
            # 2.x fallback: plain text / res field
            sub = region.get("res") or region.get("text") or ""
            if isinstance(sub, str):
                text = sub
            elif isinstance(sub, list):
                text = "\n".join(
                    s.get("text", "") if isinstance(s, dict) else str(s) for s in sub
                )
            else:
                text = ""
            conf = score
        if not text.strip():
            continue
        blocks.append(
            RawBlock(
                text=text.strip(),
                bbox=bbox,
                block_type=type_map.get(rtype, "body"),
                confidence=round(conf, 3),
                language_hint=detect_language(text),
                reading_order=order,
            )
        )
    return blocks, assets


def parse_paddle_text_result(res: dict, page: "PageInput") -> tuple[list[RawBlock], list[RawVisualAsset]]:
    """Map a paddleocr 3.x ``PaddleOCR`` text result (``res`` dict) into blocks.

    The text engine returns, under ``res``::

        {"rec_texts": [...], "rec_scores": [...], "rec_boxes": [[x1,y1,x2,y2], ...]}

    Lines are re-sorted into a top-to-bottom, left-to-right reading order and
    each becomes one ``body`` block with its per-line recognition score.
    """
    w = float(page.width or 0) or 1.0
    h = float(page.height or 0) or 1.0
    texts = res.get("rec_texts") or []
    scores = res.get("rec_scores") or []
    boxes = res.get("rec_boxes") or []
    if not texts:
        return [], []

    rows = []
    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            continue
        box = boxes[i] if i < len(boxes) else None
        score = float(scores[i]) if i < len(scores) else 0.0
        if not box or len(box) < 4:
            rows.append((1e9, 0.0, t, score, None))
            continue
        x0, y0, x1, y1 = [float(v) for v in box]
        yc = (y0 + y1) / 2.0
        xc = (x0 + x1) / 2.0
        bbox = [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)]
        rows.append((yc, xc, t, score, bbox))

    # Reading order: top-to-bottom, then left-to-right.
    rows.sort(key=lambda r: (r[0], r[1]))
    blocks: list[RawBlock] = []
    for order, (_, _, t, score, bbox) in enumerate(rows, start=1):
        blocks.append(RawBlock(
            text=t,
            bbox=bbox,
            block_type="body",
            confidence=round(score, 3),
            language_hint=detect_language(t),
            reading_order=order,
        ))
    return blocks, []


class PaddleTextEngine:
    """PaddleOCR text engine (paddleocr 3.x ``PaddleOCR`` with PP-OCRv6 det+rec).

    This is the reliable, default Chinese OCR path. It needs only the text
    detection + recognition models (cached after first run) and does NOT pull
    the heavier layout / table / formula chain, so it loads fast and is robust
    on scanned Chinese pages. Reading order is reconstructed from geometry.
    """

    name: SourceMethod = "paddle_ocr"

    def __init__(self) -> None:
        self._ok = self._probe()
        self._engine = None

    def _probe(self) -> bool:
        try:
            import paddleocr  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def available(self) -> bool:
        return self._ok

    def _get_engine(self):
        if self._engine is None:
            from paddleocr import PaddleOCR  # type: ignore

            self._engine = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._engine

    def _prepare_image(self, image) -> "str | None":
        if isinstance(image, (str, Path)):
            return str(image)
        if isinstance(image, (bytes, bytearray)):
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                    fh.write(bytes(image))
                    return fh.name
            except Exception:
                return None
        return None

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]:
        if not self._ok or page.image is None:
            return [], []
        img = self._prepare_image(page.image)
        if img is None:
            return [], []
        try:
            engine = self._get_engine()
            results = engine.predict(input=img)
        except Exception:
            return [], []
        finally:
            if isinstance(page.image, (bytes, bytearray)) and img:
                try:
                    os.unlink(img)
                except Exception:
                    pass
        if not results:
            return [], []
        j = getattr(results[0], "json", None)
        data = j() if callable(j) else (j if isinstance(j, dict) else results[0])
        inner = data.get("res", data) if isinstance(data, dict) else data
        return parse_paddle_text_result(inner, page)


class PaddleOCREngine:
    """Backwards-compatible alias that delegates to :class:`PaddleTextEngine`.

    Historically this wrapped ``PPStructureV3`` (full layout + table + formula).
    On machines where the full model chain cannot be fetched, the reliable
    PP-OCRv6 text engine is the correct default, so this class now delegates to
    it. The PP-StructureV3 mapping helper (:func:`parse_pp_structurev3_result`)
    remains available for callers that can load the full pipeline.
    """

    name: SourceMethod = "paddle_ocr"

    def __init__(self) -> None:
        self._delegate = PaddleTextEngine()

    def available(self) -> bool:
        return self._delegate.available()

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]:
        return self._delegate.recognize(page, policy)


# ── PaddleOCR-VL-1.6 engine (VLM fallback for hard pages, optional) ──────────

class PaddleVLEngine:
    """Reserved PaddleOCR-VL backend.

    It deliberately remains unavailable until a real inference path and a
    provenance-preserving merge have been validated end to end.
    """

    name: SourceMethod = "paddle_vl"

    def __init__(self) -> None:
        self._ok = False

    def available(self) -> bool:
        return self._ok

    def recognize(self, page: "PageInput", policy: "OCRPolicy") -> tuple[list[RawBlock], list[RawVisualAsset]]:
        return [], []


# ── Status reporting ─────────────────────────────────────────────────────────

@dataclass
class EngineStatus:
    name: SourceMethod
    available: bool
    detail: str = ""


def get_engine_status() -> list[EngineStatus]:
    t = TesseractEngine()
    statuses = [
        EngineStatus("native", True, "native text layer (always available)"),
        EngineStatus(
            "tesseract",
            t.available(),
            ("chi_sim+eng" if t.supports_chinese() else "eng only (no chi_sim)")
            if t.available() else "tesseract binary not found",
        ),
        EngineStatus("paddle_ocr", PaddleOCREngine().available(), "PP-OCRv6 text detection + recognition"),
        EngineStatus("paddle_vl", False, "disabled until backend and provenance merge are validated"),
    ]
    return statuses
