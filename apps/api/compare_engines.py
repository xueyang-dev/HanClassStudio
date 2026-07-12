"""Compare two OCR benchmark runs (e.g. PaddleOCR vs Tesseract) on the same
pages. Reads the two ``source_material.json`` files produced by
``benchmark_lesson1.py`` and emits a comparison report.

Usage:
    python compare_engines.py \
        --a output/lesson1_ocr_test_v2_chisim/source_material.json \
        --b output/lesson1_paddleocr/source_material.json \
        --a-name Tesseract --b-name PaddleOCR \
        --out output/lesson1_compare/report.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def metrics(contract: dict) -> dict:
    all_blocks: list[dict] = [b for p in contract["pages"] for b in p["blocks"]]
    n = len(all_blocks)
    nr = sum(1 for b in all_blocks if b.get("needs_review"))
    confs = [b["confidence"] for b in all_blocks if isinstance(b.get("confidence"), (int, float))]
    lang = Counter(b.get("language_hint") or "" for b in all_blocks)
    zh = lang.get("zh", 0) + lang.get("mixed", 0)
    tables = sum(1 for b in all_blocks if b.get("block_type") == "table")
    titles = sum(1 for b in all_blocks if b.get("block_type") in ("title", "heading"))
    illustrations = sum(
        1 for p in contract["pages"] for a in p.get("visual_assets", [])
        if a.get("asset_type") == "illustration"
    )
    methods = Counter(p["source_method"] for p in contract["pages"])
    return {
        "pages": len(contract["pages"]),
        "blocks": n,
        "needs_review": nr,
        "needs_review_rate": round(nr / n, 3) if n else 0.0,
        "mean_conf": round(sum(confs) / len(confs), 3) if confs else 0.0,
        "zh_blocks": zh,
        "zh_rate": round(zh / n, 3) if n else 0.0,
        "tables": tables,
        "titles": titles,
        "illustrations": illustrations,
        "methods": dict(methods),
        "lang_breakdown": dict(lang),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--a-name", default="A")
    ap.add_argument("--b-name", default="B")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ca, cb = load(args.a), load(args.b)
    ma, mb = metrics(ca), metrics(cb)

    lines: list[str] = []
    lines.append(f"# OCR Engine Comparison: {args.a_name} vs {args.b_name}\n")
    lines.append("| metric | " + args.a_name + " | " + args.b_name + " |")
    lines.append("|---|---|---|")
    rows = [
        ("pages", "pages"),
        ("total evidence blocks", "blocks"),
        ("needs_review blocks", "needs_review"),
        ("needs_review rate", "needs_review_rate"),
        ("mean confidence", "mean_conf"),
        ("Chinese (zh+mixed) blocks", "zh_blocks"),
        ("Chinese block rate", "zh_rate"),
        ("table regions", "tables"),
        ("title/heading blocks", "titles"),
        ("illustration assets", "illustrations"),
    ]
    for label, key in rows:
        lines.append(f"| {label} | {ma[key]} | {mb[key]} |")
    lines.append("")
    lines.append(f"- {args.a_name} source methods: {ma['methods']}")
    lines.append(f"- {args.b_name} source methods: {mb['methods']}")
    lines.append("")
    lines.append(f"- {args.a_name} language breakdown: {ma['lang_breakdown']}")
    lines.append(f"- {args.b_name} language breakdown: {mb['lang_breakdown']}")
    lines.append("")

    # Per-page block count + needs_review, side by side.
    lines.append("## Per-page\n")
    lines.append("| PDF page | " + args.a_name + " blocks (nr) | " + args.b_name + " blocks (nr) |")
    lines.append("|---|---|---|")
    pa = {p["page_number"]: p for p in ca["pages"]}
    pb = {p["page_number"]: p for p in cb["pages"]}
    for pn in sorted(set(pa) | set(pb)):
        a = pa.get(pn)
        b = pb.get(pn)
        a_s = f"{len(a['blocks'])} ({sum(1 for x in a['blocks'] if x.get('needs_review'))})" if a else "-"
        b_s = f"{len(b['blocks'])} ({sum(1 for x in b['blocks'] if x.get('needs_review'))})" if b else "-"
        lines.append(f"| {pn} | {a_s} | {b_s} |")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out)
    print(f"  {args.a_name}: blocks={ma['blocks']} nr_rate={ma['needs_review_rate']} "
          f"zh_rate={ma['zh_rate']} conf={ma['mean_conf']} tables={ma['tables']}")
    print(f"  {args.b_name}: blocks={mb['blocks']} nr_rate={mb['needs_review_rate']} "
          f"zh_rate={mb['zh_rate']} conf={mb['mean_conf']} tables={mb['tables']}")


if __name__ == "__main__":
    main()
