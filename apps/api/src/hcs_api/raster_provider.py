"""One opt-in experimental raster illustration adapter.

This module intentionally contains a single provider implementation.  It is
not a registry or a router: callers must explicitly select
``experimental_openai_images``.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import struct
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import truststore

from .models import IllustrationRequest, ImageProviderSettings, RasterFailureCategory, RasterFailureStage
from .providers import ProviderError


EXPERIMENTAL_PROVIDER = "experimental_openai_images"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/images/generations"
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 1
_TLS_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class RasterProviderError(ProviderError):
    """Classified adapter failure that is safe to turn into an SVG fallback."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        stage: RasterFailureStage,
        category: RasterFailureCategory | None = None,
        status_code: int | None = None,
        provider_request_id: str | None = None,
        retry_count: int = 0,
    ):
        super().__init__(message)
        self.kind = kind
        self.stage = stage
        self.category = category or _category_for_kind(kind)
        self.status_code = status_code
        self.provider_request_id = provider_request_id
        self.retry_count = retry_count


@dataclass(frozen=True)
class ProviderImagePayload:
    image_bytes: bytes
    mime_type: str
    model: str
    prompt: str
    revised_prompt: str | None
    seed: int | None
    retry_count: int
    provider_request_id: str | None
    warnings: list[str]


def experimental_raster_enabled(settings: ImageProviderSettings) -> bool:
    # Selecting this dedicated provider name is the explicit opt-in.  The
    # persisted default remains ``placeholder`` and the existing settings
    # schema/UI need no experimental controls.
    return settings.provider == EXPERIMENTAL_PROVIDER


def generate_experimental_raster_image(
    settings: ImageProviderSettings,
    request: IllustrationRequest,
) -> ProviderImagePayload:
    """Generate one image through the sole experimental adapter.

    The adapter accepts OpenAI Images-compatible responses to keep the trial
    inexpensive to operate against an explicitly configured endpoint.  It
    supports either inline base64 or a short-lived URL, but URL data is always
    downloaded before this function returns and is never retained in metadata.
    """
    if not experimental_raster_enabled(settings):
        raise RasterProviderError("disabled", "Experimental raster provider is disabled", stage="request_build")
    api_key = os.environ.get("HCS_EXPERIMENTAL_RASTER_API_KEY", settings.api_key).strip()
    if not api_key:
        raise RasterProviderError("configuration", "Experimental raster provider has no API key", stage="request_build")
    if not request.scene_description.strip():
        raise RasterProviderError("configuration", "Illustration request has no scene description", stage="request_build")

    timeout = REQUEST_TIMEOUT_SECONDS
    retries = MAX_RETRIES
    endpoint = settings.endpoint_url.strip() or DEFAULT_ENDPOINT
    model = settings.model.strip() or "gpt-image-1"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": request.scene_description,
        "image_size": _size_for_request(request),
        "batch_size": max(1, min(request.candidate_count, 1)),
    }
    if request.negative_constraints:
        payload["negative_prompt"] = ", ".join(request.negative_constraints)
    if request.seed is not None:
        payload["seed"] = request.seed

    response, response_request_id, generation_retry_count = _post_json_with_retries(endpoint, payload, api_key, timeout, retries)
    # SiliconFlow's compatible endpoint returns ``images`` while the OpenAI
    # endpoint uses ``data``. Both contain items with a temporary ``url``.
    items = response.get("data") or response.get("images") or []
    if not items or not isinstance(items[0], dict):
        raise RasterProviderError(
            "response", "Experimental raster provider returned no image item",
            stage="provider_response_parse", category="response_shape",
            provider_request_id=response_request_id,
        )
    item = items[0]
    revised_prompt = item.get("revised_prompt") if isinstance(item.get("revised_prompt"), str) else None
    provider_request_id = response_request_id or _first_string(response, "request_id", "id")
    seed = response.get("seed") if isinstance(response.get("seed"), int) else request.seed
    download_retry_count = 0

    if isinstance(item.get("b64_json"), str):
        try:
            image_bytes = base64.b64decode(item["b64_json"], validate=True)
        except (ValueError, TypeError) as exc:
            raise RasterProviderError(
                "response", "Provider returned invalid base64 image data",
                stage="provider_response_parse", category="response_shape",
                provider_request_id=provider_request_id,
            ) from exc
        mime_type = _validated_download_mime(item.get("mime_type") or "application/octet-stream", image_bytes)
    elif isinstance(item.get("url"), str):
        image_bytes, mime_type, response_request_id, download_retry_count = _download_image(item["url"], timeout, retries)
        provider_request_id = provider_request_id or response_request_id
    else:
        raise RasterProviderError(
            "response", "Experimental raster provider returned neither image bytes nor URL",
            stage="provider_response_parse", category="response_shape",
            provider_request_id=provider_request_id,
        )

    if not image_bytes:
        raise RasterProviderError(
            "response", "Experimental raster provider returned an empty image",
            stage="provider_response_parse", category="response_shape",
            provider_request_id=provider_request_id,
        )
    return ProviderImagePayload(
        image_bytes=image_bytes,
        mime_type=mime_type,
        model=model,
        prompt=request.scene_description,
        revised_prompt=revised_prompt,
        seed=seed,
        retry_count=generation_retry_count + download_retry_count,
        provider_request_id=provider_request_id,
        warnings=[],
    )


def image_dimensions(image_bytes: bytes, mime_type: str) -> tuple[int | None, int | None]:
    """Extract dimensions when the provider returned a common raster format."""
    if mime_type == "image/png" and len(image_bytes) >= 24 and image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", image_bytes[16:24])
    return None, None


def _size_for_request(request: IllustrationRequest) -> str:
    if request.width and request.height:
        return f"{request.width}x{request.height}"
    return {"1:1": "1024x1024", "16:9": "1536x864", "9:16": "864x1536"}.get(request.aspect_ratio, "1536x864")


def _post_json_with_retries(
    endpoint: str, payload: dict[str, Any], api_key: str, timeout: int, retries: int,
) -> tuple[dict[str, Any], str | None, int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    (response, request_id), retry_count = _with_retries(
        lambda: _read_json_response(request, timeout),
        retries,
        {"rate_limit", "provider_generation", "generation_timeout", "network"},
    )
    return response, request_id, retry_count


def _download_image(url: str, timeout: int, retries: int) -> tuple[bytes, str, str | None, int]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RasterProviderError(
            "response", "Provider image URL must use HTTP(S)",
            stage="provider_response_parse", category="response_shape",
        )
    request = urllib.request.Request(url, method="GET")

    def read() -> tuple[bytes, str, str | None]:
        try:
            with _open_url(request, timeout) as response:
                image_bytes = response.read()
                mime_type = _validated_download_mime(response.headers.get_content_type(), image_bytes)
                return image_bytes, mime_type, response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            request_id = exc.headers.get("x-request-id") if exc.headers else None
            category: RasterFailureCategory = "download_forbidden" if exc.code in {401, 403, 404, 410, 451} else "unknown"
            raise RasterProviderError(
                "http", f"Image download HTTP {exc.code}",
                stage="remote_asset_download", category=category,
                status_code=exc.code, provider_request_id=request_id,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            timed_out = _is_timeout(exc)
            raise RasterProviderError(
                "timeout" if timed_out else "network", str(exc),
                stage="remote_asset_download",
                category="download_timeout" if timed_out else "network",
            ) from exc

    (image_bytes, mime_type, request_id), retry_count = _with_retries(
        read, retries, {"download_timeout", "network"},
    )
    return image_bytes, mime_type, request_id, retry_count


def _read_json_response(
    request: urllib.request.Request,
    timeout: int,
) -> tuple[dict[str, Any], str | None]:
    try:
        with _open_url(request, timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            provider_request_id = response.headers.get("x-siliconcloud-trace-id") or response.headers.get("x-request-id")
    except urllib.error.HTTPError as exc:
        request_id = _request_id_from_headers(exc.headers)
        if exc.code in {401, 403}:
            category: RasterFailureCategory = "authentication"
        elif exc.code == 429:
            category = "rate_limit"
        else:
            category = "provider_generation"
        raise RasterProviderError(
            "http", f"Image generation HTTP {exc.code}",
            stage="provider_generation", category=category,
            status_code=exc.code, provider_request_id=request_id,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        timed_out = _is_timeout(exc)
        raise RasterProviderError(
            "timeout" if timed_out else "network", str(exc),
            stage="provider_generation",
            category="generation_timeout" if timed_out else "network",
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RasterProviderError(
            "response", "Image generation returned invalid JSON",
            stage="provider_response_parse", category="response_shape",
        ) from exc
    if not isinstance(payload, dict):
        raise RasterProviderError(
            "response", "Image generation returned a non-object response",
            stage="provider_response_parse", category="response_shape",
            provider_request_id=provider_request_id,
        )
    return payload, provider_request_id


def _with_retries(operation, retries: int, retry_categories: set[str]):
    last_error: RasterProviderError | None = None
    for attempt in range(retries + 1):
        try:
            return operation(), attempt
        except RasterProviderError as exc:
            last_error = exc
            exc.retry_count = attempt
            if attempt >= retries or exc.category not in retry_categories:
                break
    assert last_error is not None
    raise last_error


def _validated_mime(value: object) -> str:
    mime_type = str(value or "").split(";", 1)[0].strip().lower()
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise RasterProviderError(
            "mime", f"Provider returned unsupported image content type: {mime_type or 'missing'}",
            stage="mime_validation", category="invalid_mime",
        )
    return mime_type


def _validated_download_mime(value: object, image_bytes: bytes) -> str:
    mime_type = str(value or "").split(";", 1)[0].strip().lower()
    detected = _detect_image_mime(image_bytes)
    if mime_type in ALLOWED_IMAGE_MIME_TYPES:
        if detected != mime_type:
            raise RasterProviderError(
                "mime", "Downloaded body does not match its declared image content type",
                stage="mime_validation", category="invalid_mime",
            )
        return mime_type
    if mime_type not in {"", "application/octet-stream"}:
        return _validated_mime(mime_type)
    if detected:
        return detected
    raise RasterProviderError(
        "mime", "Provider returned generic content type without a supported image signature",
        stage="mime_validation", category="invalid_mime",
    )


def _detect_image_mime(image_bytes: bytes) -> str | None:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()


def _request_id_from_headers(headers: object) -> str | None:
    if not headers or not hasattr(headers, "get"):
        return None
    return headers.get("x-siliconcloud-trace-id") or headers.get("x-request-id")  # type: ignore[union-attr]


def _category_for_kind(kind: str) -> RasterFailureCategory:
    return {
        "disabled": "configuration",
        "configuration": "configuration",
        "response": "response_shape",
        "mime": "invalid_mime",
        "timeout": "unknown",
        "network": "network",
        "http": "unknown",
    }.get(kind, "unknown")


def _open_url(request: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(request, timeout=timeout, context=_TLS_CONTEXT)
