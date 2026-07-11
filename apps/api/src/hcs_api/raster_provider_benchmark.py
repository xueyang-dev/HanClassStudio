"""Development-only side-by-side review gallery for the raster experiment."""

from __future__ import annotations

import html
import json
import time
from hashlib import sha256
from pathlib import Path

from .media import _extension_for_mime, _placeholder_svg
from .models import GeneratedImage, IllustrationRequest, ProviderSettings, utc_now_iso
from .raster_provider import RasterProviderError, experimental_raster_enabled, generate_experimental_raster_image, image_dimensions


BENCHMARK_CONCEPTS = ["睡觉", "吃饭", "喝水", "学习", "学生向老师问好"]


def create_raster_provider_ab_gallery(project_root: Path, settings: ProviderSettings) -> Path:
    """Generate local diagnostic comparisons; never touches AssetManifest/courseware."""
    root = project_root / "diagnostics" / "raster_provider_ab"
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    for index, concept in enumerate(BENCHMARK_CONCEPTS, start=1):
        request = IllustrationRequest(
            id=f"raster-ab-{index}",
            concept=concept,
            scene_description=f"Chinese language classroom illustration of {concept}; clear action, no text.",
            illustration_role="benchmark_primary_visual",
            aspect_ratio="16:9",
            negative_constraints=["no words", "no watermark", "no learner-facing metadata"],
            source_trace=["diagnostics/raster_provider_ab"],
        )
        svg_name = f"{index:02d}-fallback.svg"
        (assets_dir / svg_name).write_text(_placeholder_svg(request.scene_description, index), encoding="utf-8")
        started = time.perf_counter()
        raster: GeneratedImage | None = None
        fallback_reason: str | None = None
        raster_size = 0
        if experimental_raster_enabled(settings.image):
            try:
                payload = generate_experimental_raster_image(settings.image, request)
                suffix = _extension_for_mime(payload.mime_type)
                raster_name = f"{index:02d}-raster{suffix}"
                raster_path = assets_dir / raster_name
                raster_path.write_bytes(payload.image_bytes)
                width, height = image_dimensions(payload.image_bytes, payload.mime_type)
                raster_size = len(payload.image_bytes)
                raster = GeneratedImage(
                    provider=settings.image.provider,
                    model=payload.model,
                    local_path=f"assets/{raster_name}",
                    mime_type=payload.mime_type,
                    width=width,
                    height=height,
                    prompt=payload.prompt,
                    revised_prompt=payload.revised_prompt,
                    seed=payload.seed,
                    content_hash=sha256(payload.image_bytes).hexdigest(),
                    generated_at=utc_now_iso(),
                    provider_request_id=payload.provider_request_id,
                    source_trace=request.source_trace,
                    warnings=payload.warnings,
                )
            except RasterProviderError as exc:
                fallback_reason = f"{exc.kind}: {exc}"
        else:
            fallback_reason = "disabled: Experimental raster provider is disabled"
        records.append({
            "concept": concept,
            "request": request.model_dump(mode="json"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "raster": raster.model_dump(mode="json") if raster else None,
            "raster_file_size": raster_size,
            "svg_fallback": f"assets/{svg_name}",
            "fallback_used": raster is None,
            "fallback_reason": fallback_reason,
        })

    (root / "results.json").write_text(json.dumps({
        "schema": "hanclassstudio.raster_provider_ab.v1",
        "diagnostic_only": True,
        "teacher_visual_review_required": True,
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_raster_provider_benchmark_summary(root, records)
    (root / "index.html").write_text(_render_gallery(records), encoding="utf-8")
    return root / "index.html"


def write_raster_provider_benchmark_summary(root: Path, records: list[dict]) -> Path:
    """Write review-ready metrics without exposing temporary provider URLs."""
    summary = {
        "schema": "hanclassstudio.raster_provider_ab_summary.v1",
        "diagnostic_only": True,
        "human_review_required": True,
        "records": [{
            "concept": record["concept"],
            "latency_ms": record["latency_ms"],
            "provider": record["raster"]["provider"] if record["raster"] else None,
            "model": record["raster"]["model"] if record["raster"] else None,
            "local_file_size": record["raster_file_size"],
            "fallback_used": record["fallback_used"],
            "human_review": {"status": "pending", "notes": ""},
        } for record in records],
    }
    path = root / "benchmark_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _render_gallery(records: list[dict]) -> str:
    cards = []
    for record in records:
        raster = record["raster"]
        raster_html = (
            f'<img src="{html.escape(raster["local_path"])}" alt="Raster: {html.escape(record["concept"])}">'
            if raster else f'<p class="fallback">Raster unavailable: {html.escape(record["fallback_reason"] or "unknown")}</p>'
        )
        cards.append(f"""
<article><h2>{html.escape(record["concept"])}</h2><div class="comparison">
<section><h3>Experimental raster</h3>{raster_html}</section>
<section><h3>Current deterministic SVG fallback</h3><img src="{html.escape(record["svg_fallback"])}" alt="SVG fallback: {html.escape(record["concept"])}"></section>
</div><details><summary>Request and provenance</summary><pre>{html.escape(json.dumps(record, ensure_ascii=False, indent=2))}</pre></details></article>""")
    return """<!doctype html><meta charset=\"utf-8\"><title>Raster Provider A/B</title>
<style>body{font:16px system-ui;margin:2rem;background:#f7f8fa;color:#182028}article{background:white;padding:1rem;margin:1rem 0;border-radius:10px}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:1rem}section{border:1px solid #d9dfe5;padding:.75rem}img{display:block;max-width:100%;background:#f3f5f7}.fallback{min-height:12rem;padding:1rem;background:#fff3cd}.notice{background:#fff3cd;padding:1rem;border-radius:8px}pre{white-space:pre-wrap}</style>
<h1>Experimental raster provider A/B</h1><p class=\"notice\">Diagnostic-only. Teacher visual review is required; this page does not assert visual superiority and is excluded from courseware/export.</p>""" + "\n".join(cards)
