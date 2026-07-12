"""Layout helpers: reading-order recovery and repeated margin (header/footer) detection."""

from __future__ import annotations

from hcs_api.models import OCREvidenceBlock, PageAnalysisResult


def assign_reading_order(blocks: list[OCREvidenceBlock]) -> None:
    """Assign a contiguous 1..n ``reading_order`` to blocks.

    - If every block already has a reading order (e.g. from native extraction or
      PP-StructureV3 ``layout_order``), it is normalized to be gap-free.
    - Otherwise blocks are ordered top-to-bottom, left-to-right, with a simple
      two-column heuristic: when a meaningful left and right column both exist,
      the left column is read fully before the right column (textbook reading).
    - Blocks without a bbox are appended after positioned ones.
    """
    if not blocks:
        return
    if all(b.reading_order is not None for b in blocks):
        for i, b in enumerate(sorted(blocks, key=lambda b: b.reading_order or 0), start=1):
            b.reading_order = i
        return

    positioned = [b for b in blocks if b.bbox and len(b.bbox) == 4]
    unpositioned = [b for b in blocks if not b.bbox]

    left = [b for b in positioned if (b.bbox[0] + b.bbox[2]) / 2.0 < 0.5]
    right = [b for b in positioned if (b.bbox[0] + b.bbox[2]) / 2.0 >= 0.5]

    if left and right and len(left) >= 2 and len(right) >= 2:
        left.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        right.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
        ordered = left + right
    else:
        ordered = sorted(positioned, key=lambda b: (b.bbox[1], b.bbox[0]))

    ordered.extend(unpositioned)
    for i, b in enumerate(ordered, start=1):
        b.reading_order = i


def find_repeated_margin_blocks(page_results: list[PageAnalysisResult]) -> set[tuple[int, str]]:
    """Find blocks that repeat as page headers / footers across many pages.

    Returns a set of ``(page_number, block_id)`` for blocks whose text appears in
    the top margin (<8% height) or bottom margin (>92%) on at least two pages.
    These are tagged (not deleted) so downstream consumers can exclude them from
    body-text mining while preserving source traceability.
    """
    header_texts: dict[str, list[tuple[int, str]]] = {}
    footer_texts: dict[str, list[tuple[int, str]]] = {}

    for pr in page_results:
        for b in pr.blocks:
            if not b.bbox or len(b.bbox) != 4 or not b.text.strip():
                continue
            top, bottom = b.bbox[1], b.bbox[3]
            key = (pr.page_number, b.id)
            if top < 0.08:
                header_texts.setdefault(b.text.strip(), []).append(key)
            elif bottom > 0.92:
                footer_texts.setdefault(b.text.strip(), []).append(key)

    repeated: set[tuple[int, str]] = set()
    for keys in list(header_texts.values()) + list(footer_texts.values()):
        if len(keys) >= 2:
            repeated.update(keys)
    return repeated
