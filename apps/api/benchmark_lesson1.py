"""Run the HanClassStudio OCR / Source Understanding layer on a slice of a PDF
(e.g. Lesson 1 of the textbook) with ONE forced engine, and dump the normalized
source contract + a human-readable report.

Usage:
    python benchmark_lesson1.py \
        --pdf "/Users/xueyang/Downloads/vivo办公套件/SHORT-TERM SPOKEN CHINESE 4th Edition.pdf" \
        --start 17 --end 24 --engine paddle_ocr \
        --out output/lesson1_paddleocr

Engines: native | tesseract | paddle_ocr | paddle_vl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Allow running from apps/api without an editable install.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import fitz  # PyMuPDF

from hcs_api.models import SourceMethod
from hcs_api.source_understanding import PageInput, run_source_understanding
from hcs_api.source_understanding.pipeline import OCRPolicy


def render_pages(pdf_path: Path, start: int, end: int, render_dir: Path) -> list[PageInput]:
    render_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    n = doc.page_count
    pages: list[PageInput] = []
    for idx in range(max(1, start) - 1, min(end, n)):
        page = doc[idx]
        rect = page.rect
        w, h = float(rect.width), float(rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
        render_path = render_dir / f"page_{idx + 1}.png"
        pix.save(str(render_path))
        pages.append(PageInput(
            page_number=idx + 1,
            width=pix.width,
            height=pix.height,
            native_blocks=[],
            image=str(render_path),
            embedded_images=[],
            has_native_text=False,
            is_whole_image=False,
        ))
    doc.close()
    return pages


def write_report(contract: dict, out_dir: Path) -> None:
    lines: list[str] = []
    lines.append(f"# OCR Benchmark Report — Lesson 1 (PDF pages {contract.get('page_range', '?')})\n")
    lines.append(f"- engine(s): {contract.get('source_method_summary')}")
    lines.append(f"- overall confidence: {contract.get('overall_confidence')}")
    lines.append(f"- needs_review blocks: {contract.get('needs_review_count')}")
    lines.append("")
    for note in contract.get("notes", []):
        lines.append(f"- note: {note}")
    lines.append("")
    for pr in contract["pages"]:
        lines.append(f"## PDF page {pr['page_number']} — method={pr['source_method']} "
                     f"lang={pr.get('dominant_language','')} conf(mean per page computed below)")
        lines.append("")
        for b in sorted(pr["blocks"], key=lambda x: (x.get("reading_order") or 0)):
            txt = (b.get("text") or "").replace("\n", " ⏎ ")
            flag = " ⚠" if b.get("needs_review") else ""
            lines.append(f"- [{b['block_type']}] (conf {b['confidence']}) {txt[:200]}{flag}")
        lines.append("")
    out = out_dir / "report.md"
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--engine", default="paddle_ocr",
                    choices=["native", "tesseract", "paddle_ocr", "paddle_vl"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    render_dir = out_dir / "assets" / "ocr_render"

    pages = render_pages(Path(args.pdf), args.start, args.end, render_dir)
    policy = OCRPolicy(
        preferred_ocr=args.engine,  # type: ignore[arg-type]
        fallback_order=(),
        enable_vl_fallback=False,
    )
    result = run_source_understanding(pages, source_type="pdf", project_root=out_dir, policy=policy)
    contract = result.model_dump()
    contract["page_range"] = f"{args.start}-{args.end}"
    (out_dir / "source_material.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(contract, out_dir)

    all_blocks = [b for p in contract["pages"] for b in p["blocks"]]
    nr = sum(1 for b in all_blocks if b.get("needs_review"))
    confs = [b["confidence"] for b in all_blocks]
    print(f"engine={args.engine} pages={len(contract['pages'])} blocks={len(all_blocks)} "
          f"needs_review={nr} mean_conf={sum(confs)/len(confs):.3f}")
    print(f"wrote {out_dir / 'source_material.json'}")


if __name__ == "__main__":
    main()
