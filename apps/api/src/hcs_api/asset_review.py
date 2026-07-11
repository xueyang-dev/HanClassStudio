"""Project-local review, replacement, and reuse helpers for image assets."""

from __future__ import annotations

import html
import json
import re
from hashlib import sha256
from pathlib import Path

from .models import (
    AssetCandidate, AssetFile, AssetManifest, AssetReviewEvent,
    IllustrationRequest, ImageProviderSettings, MediaReviewAction,
)
from .raster_provider import image_dimensions


def raster_request_fingerprint(request: IllustrationRequest, settings: ImageProviderSettings) -> str:
    payload = {
        "request": _normalize(request.model_dump(mode="json")),
        "provider": settings.provider,
        "model": settings.model,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def previous_assets(project_root: Path) -> dict[str, AssetFile]:
    path = project_root / "assets" / "data" / "asset_manifest.json"
    if not path.exists():
        path = project_root / "asset_manifest.json"
    if not path.exists():
        return {}
    try:
        manifest = AssetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {asset.id: asset for asset in manifest.images}


def reusable_asset(project_root: Path, previous: AssetFile | None, fingerprint: str) -> AssetFile | None:
    if not previous:
        return None
    if previous.review_state in {"replaced_by_teacher", "fallback_accepted"}:
        path = _project_file(project_root, previous.path)
        if path.is_file() and sha256(path.read_bytes()).hexdigest() == previous.content_hash:
            return previous.model_copy(deep=True)
    if previous.request_fingerprint != fingerprint or not previous.generation:
        return None
    if previous.review_state in {"rejected", "regenerate_requested"}:
        return None
    if previous.path != previous.generation.local_path or previous.content_hash != previous.generation.content_hash:
        return None
    path = _project_file(project_root, previous.path)
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != previous.content_hash:
        return None
    return previous.model_copy(deep=True)


def retain_candidate(asset: AssetFile, candidate: AssetCandidate) -> None:
    if not any(item.id == candidate.id for item in asset.candidates):
        asset.candidates.append(candidate)


def fallback_candidate(project_root: Path, asset: AssetFile) -> AssetCandidate | None:
    path = project_root / "assets" / "images" / f"{asset.id}.svg"
    if not path.is_file():
        return None
    digest = sha256(path.read_bytes()).hexdigest()
    return AssetCandidate(
        id=f"fallback-{digest[:12]}", path=path.relative_to(project_root).as_posix(),
        mime_type="image/svg+xml", content_hash=digest, source="fallback",
    )


def apply_review(project_root: Path, manifest: AssetManifest, asset_id: str, action: MediaReviewAction) -> AssetFile:
    asset = next((item for item in manifest.images if item.id == asset_id), None)
    if not asset:
        raise ValueError(f"Unknown image asset: {asset_id}")
    candidate = next((item for item in asset.candidates if item.id == action.candidate_id), None)
    if action.state in {"accepted", "fallback_accepted"}:
        if not candidate:
            raise ValueError("An existing candidate_id is required")
        if action.state == "fallback_accepted" and candidate.source != "fallback":
            raise ValueError("fallback_accepted requires a fallback candidate")
        if not _project_file(project_root, candidate.path).is_file():
            raise ValueError("Selected candidate file is missing")
        asset.path = candidate.path
        asset.mime_type = candidate.mime_type
        asset.content_hash = candidate.content_hash
        asset.selected_candidate_id = candidate.id
        asset.fallback_used = candidate.source == "fallback"
    elif action.state in {"rejected", "regenerate_requested"}:
        fallback = next((item for item in asset.candidates if item.source == "fallback"), None)
        if fallback and _project_file(project_root, fallback.path).is_file():
            asset.path = fallback.path
            asset.mime_type = fallback.mime_type
            asset.content_hash = fallback.content_hash
            asset.selected_candidate_id = fallback.id
            asset.fallback_used = True
    else:
        raise ValueError(f"State {action.state} is set by replacement or candidate acceptance")
    asset.review_state = action.state
    asset.review_history.append(AssetReviewEvent(
        state=action.state, candidate_id=action.candidate_id, notes=action.notes,
    ))
    return asset


def replace_with_teacher_image(
    project_root: Path, manifest: AssetManifest, asset_id: str,
    content: bytes, mime_type: str, notes: str = "",
) -> AssetFile:
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime_type)
    if not extension:
        raise ValueError("Teacher replacement must be PNG, JPEG, or WebP")
    image_dimensions(content, mime_type)
    asset = next((item for item in manifest.images if item.id == asset_id), None)
    if not asset:
        raise ValueError(f"Unknown image asset: {asset_id}")
    digest = sha256(content).hexdigest()
    relative = f"assets/images/{asset.id}-teacher-{digest[:12]}{extension}"
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    candidate = AssetCandidate(
        id=f"teacher-{digest[:12]}", path=relative, mime_type=mime_type,
        content_hash=digest, source="teacher",
    )
    retain_candidate(asset, candidate)
    asset.path = relative
    asset.mime_type = mime_type
    asset.content_hash = digest
    asset.selected_candidate_id = candidate.id
    asset.review_state = "replaced_by_teacher"
    asset.fallback_used = False
    asset.review_history.append(AssetReviewEvent(
        state="replaced_by_teacher", candidate_id=candidate.id, notes=notes,
    ))
    return asset


def render_review_page(project_id: str, manifest: AssetManifest) -> str:
    cards = []
    for asset in manifest.images:
        if not asset.candidates:
            continue
        candidates = "".join(
            f'<figure><img src="/runtime/projects/{html.escape(project_id)}/{html.escape(item.path)}" '
            f'alt="{html.escape(item.source)} candidate"><figcaption>{html.escape(item.source)} · '
            f'{html.escape(item.id)}</figcaption><button data-asset="{html.escape(asset.id)}" '
            f'data-candidate="{html.escape(item.id)}" data-state="'
            f'{"fallback_accepted" if item.source == "fallback" else "accepted"}">Use this candidate</button></figure>'
            for item in asset.candidates
        )
        cards.append(
            f'<article><h2>{html.escape(asset.id)}</h2><p>Review: {html.escape(asset.review_state or "not required")}</p>'
            f'<div class="candidates">{candidates}</div><div class="actions">'
            f'<button data-asset="{html.escape(asset.id)}" data-state="rejected">Reject</button>'
            f'<button data-asset="{html.escape(asset.id)}" data-state="regenerate_requested">Request regeneration</button>'
            f'<form data-asset="{html.escape(asset.id)}"><input name="file" type="file" accept="image/png,image/jpeg,image/webp" required>'
            f'<button>Use teacher image</button></form></div></article>'
        )
    return """<!doctype html><meta charset="utf-8"><title>Teacher media review</title>
<style>body{font:16px system-ui;margin:2rem;background:#f5f7f6;color:#223236}article{background:#fff;padding:1rem;margin:1rem 0}.candidates{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}figure{margin:0;border:1px solid #d9e7e1;padding:.75rem}img{max-width:100%;display:block}figcaption{margin:.5rem 0}.actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem}button{padding:.55rem .8rem}form{display:flex;gap:.5rem}</style>
<h1>Teacher media review</h1><p>Compare local candidates. A teacher decision is required before pilot approval.</p>""" + "".join(cards) + f"""
<script>
const mediaEndpoint = '/api/projects/' + encodeURIComponent({json.dumps(project_id)}) + '/media';
const base = mediaEndpoint + '/';
document.addEventListener('click', async event => {{
  const button = event.target.closest('button[data-state]');
  if (!button) return;
  const response = await fetch(base + encodeURIComponent(button.dataset.asset) + '/review', {{
    method: 'PUT', headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{state: button.dataset.state, candidate_id: button.dataset.candidate || null}})
  }});
  if (!response.ok) return alert(await response.text());
  if (button.dataset.state === 'regenerate_requested') {{
    const generated = await fetch(mediaEndpoint + '?force_regenerate=true', {{method: 'POST'}});
    if (!generated.ok) return alert(await generated.text());
  }}
  location.reload();
}});
document.addEventListener('submit', async event => {{
  const form = event.target.closest('form[data-asset]');
  if (!form) return;
  event.preventDefault();
  const response = await fetch(base + encodeURIComponent(form.dataset.asset) + '/replacement', {{
    method: 'POST', body: new FormData(form)
  }});
  if (response.ok) location.reload(); else alert(await response.text());
}});
</script>"""


def _normalize(value):
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items())}
    return value


def _project_file(project_root: Path, relative: str) -> Path:
    root = project_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        return root / ".invalid-asset-path"
    return path
