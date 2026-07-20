"""Teacher-facing Provider Hub contracts and safe fixture task runners.

This module is an adapter over the existing Provider capability catalog and v1
registry.  It adds the domain separation and task contracts needed by the Hub
without changing legacy project/provider settings or granting remote manifests
execution authority.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import storage
from .models import ImageProviderSettings
from .provider_registry import (
    ProviderRegistryError,
    _read_mapping,
    _update_mapping,
    refresh_registry,
    registry_status,
)
from .providers import provider_capability_catalog


HubStatus = Literal[
    "discovered", "available", "not_installed", "installing", "installed",
    "not_configured", "configured", "checking", "ready", "degraded",
    "incompatible", "update_available", "failed", "disabled", "unavailable",
]
HubAction = Literal[
    "view_details", "open_project", "open_api_application", "configure",
    "delete_configuration", "test_connection", "install", "cancel_install",
    "repair", "check_health", "disable", "enable", "view_logs",
]
TrustLevel = Literal[
    "official_verified", "community_verified", "discovered_unverified",
    "user_added", "deprecated", "blocked",
]
Compatibility = Literal["compatible", "compatible_but_slow", "unsupported", "unknown"]
TaskState = Literal["queued", "running", "completed", "failed", "cancelled", "partial"]
InstallPhase = Literal[
    "preflight", "resolving", "downloading", "verifying", "extracting",
    "installing_runtime", "installing_model", "installing_workflow", "starting",
    "health_check", "smoke_test", "completed", "failed", "cancelled", "rolling_back",
]
ErrorCode = Literal[
    "network_error", "authentication_error", "rate_limited", "invalid_manifest",
    "license_unknown", "unsupported_platform", "insufficient_memory",
    "insufficient_vram", "insufficient_disk", "checksum_mismatch", "unsafe_artifact",
    "download_failed", "installation_failed", "health_check_failed", "cancelled",
    "internal_error", "task_not_found", "task_conflict",
]

_INSTALL_TASK_FILE = "provider_hub_install_tasks.json"
_REFRESH_TASK_FILE = "provider_hub_refresh_tasks.json"
_HUB_STATE_FILE = "provider_hub_state.json"
_FIXTURE_PATH = Path(__file__).resolve().parents[4] / "providers" / "fixtures" / "local-image-basic-v1.json"
_FIXTURE_SHA256 = "c6b6b757ff5615dd2d5dec4d79c3dc08f280f75c83c37f34ffe9fc022ed0012d"
_FIXTURE_MAX_BYTES = 64 * 1024
_INSTALL_STEP_DELAY_SECONDS = 0.025
_ONLINE_PROVIDER_ID = "openai_images"
_ONLINE_PACKAGE_ID = "hcs.online-image-high-quality"
_LOCAL_PACKAGE_ID = "hcs.local-image-basic"
_VIDEO_PACKAGE_ID = "hcs.teaching-video-basic"
_ONLINE_HOSTS = {"api.openai.com"}


class ProviderHubError(RuntimeError):
    def __init__(self, code: ErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_https(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("external links must not contain an invalid port") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or port is not None or parsed.query or parsed.fragment
    ):
        raise ValueError("external links must use plain HTTPS without credentials, ports, query, or fragment")
    return value


class SourceLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    official_website_url: str | None = None
    project_url: str | None = None
    api_application_url: str | None = None
    api_docs_url: str | None = None
    pricing_url: str | None = None
    terms_url: str | None = None
    privacy_url: str | None = None
    model_url: str | None = None
    license_url: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _links_are_safe(cls, value: Any) -> Any:
        return _safe_https(value) if isinstance(value, str) else value


class LicenseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: str | None = None
    redistribution_allowed: bool = False
    clear: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def _url_is_safe(cls, value: Any) -> Any:
        return _safe_https(value) if isinstance(value, str) else value


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    execution: str


class ModelPackageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    format: str
    safe_format: bool


class WorkflowPackSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    capabilities: list[str]


class CapabilityPackageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    runtime: RuntimeSpec | None = None
    model_packages: list[ModelPackageSpec] = Field(default_factory=list)
    workflow_packs: list[WorkflowPackSpec] = Field(default_factory=list)
    healthcheck: str


class HardwareCapability(BaseModel):
    operating_system: str
    architecture: str
    memory_mb: int | None = None
    free_disk_mb: int | None = None
    gpu_vendor: str | None = None
    gpu_name: str | None = None
    gpu_memory_mb: int | None = None
    cuda_available: bool | None = None
    directml_available: bool | None = None
    mps_available: bool | None = None
    status: Compatibility = "unknown"
    reasons: list[str] = Field(default_factory=list)
    speed_estimate: str | None = None
    checked_at: str


class ProviderHubItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider_id: str
    name: str
    description: str
    provider_type: Literal["online", "offline", "hybrid"]
    capabilities: list[str]
    trust_level: TrustLevel
    registry_source: Literal["builtin", "official_registry", "local_config"]
    status: HubStatus
    installed: bool = False
    configured: bool = False
    ready: bool = False
    compatible: Compatibility = "unknown"
    available_actions: list[HubAction] = Field(default_factory=list)
    recommended: bool = False
    requires_download: bool = False
    requires_api_key: bool = False
    paid_service: bool | None = None
    runs_locally: bool = False
    uploads_data: bool = False
    version: str | None = None
    update_channel: Literal["stable", "beta", "experimental"] = "stable"
    source_links: SourceLinks = Field(default_factory=SourceLinks)
    license: LicenseInfo = Field(default_factory=LicenseInfo)
    publisher: str | None = None
    third_party_executable_code: bool = False
    redistributed_by_hanclassstudio: bool = False
    capability_package: CapabilityPackageSpec | None = None
    technical_error: dict[str, Any] | None = None
    last_health_check_at: str | None = None


class ProviderHubCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: Literal["hanclassstudio.provider_hub.v1"] = Field(
        default="hanclassstudio.provider_hub.v1", alias="schema"
    )
    providers: list[ProviderHubItem]
    hardware: HardwareCapability
    last_refresh_at: str | None = None
    isolated_errors: list[dict[str, str]] = Field(default_factory=list)


class RefreshSourceResult(BaseModel):
    source_id: str
    status: Literal["updated", "unchanged", "failed"]
    message: str
    retained_previous_snapshot: bool = False


class RefreshSummary(BaseModel):
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed_sources: int = 0
    sources: list[RefreshSourceResult] = Field(default_factory=list)


class ProviderRefreshTask(BaseModel):
    task_id: str
    state: TaskState = "queued"
    started_at: str
    updated_at: str
    finished_at: str | None = None
    summary: RefreshSummary = Field(default_factory=RefreshSummary)
    error: dict[str, str] | None = None


class ProviderInstallTask(BaseModel):
    task_id: str
    package_id: str
    state: TaskState = "queued"
    phase: InstallPhase = "preflight"
    progress: int = Field(default=0, ge=0, le=100)
    current_file_progress: int = Field(default=0, ge=0, le=100)
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str
    started_at: str
    updated_at: str
    finished_at: str | None = None
    cancellable: bool = True
    cancel_requested: bool = False
    error: dict[str, Any] | None = None
    recoverable_actions: list[HubAction] = Field(default_factory=list)
    log_ref: str


class ProviderInstallStartResponse(BaseModel):
    task: ProviderInstallTask
    provider: ProviderHubItem


class OnlineProviderConfigRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=4096)
    endpoint: str = "https://api.openai.com/v1"
    model: str = Field(default="gpt-image-2", min_length=1, max_length=160)

    @field_validator("api_key")
    @classmethod
    def _credential_has_no_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("API Key contains invalid control characters")
        return value

    @field_validator("model")
    @classmethod
    def _model_is_a_safe_identifier(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", value):
            raise ValueError("model must be a plain model identifier")
        return value

    @field_validator("endpoint")
    @classmethod
    def _trusted_endpoint(cls, value: str) -> str:
        parsed = urlparse(value.rstrip("/"))
        if (
            parsed.scheme != "https" or parsed.hostname not in _ONLINE_HOSTS
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
        ):
            raise ValueError("online Provider endpoint is not an approved HTTPS origin")
        return value.rstrip("/")


class PublicOnlineProviderConfig(BaseModel):
    provider_id: str = _ONLINE_PROVIDER_ID
    endpoint: str
    model: str
    api_key_present: bool
    secure_storage: Literal["os_protected", "local_file_write_only"] = "local_file_write_only"


def _memory_mb() -> int | None:
    try:
        return int(int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES")) / (1024 * 1024))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def detect_hardware() -> HardwareCapability:
    """Best-effort hardware facts. Detection failure is represented, never raised."""
    checked_at = _iso()
    try:
        system = platform.system().lower() or "unknown"
        operating_system = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)
        raw_arch = platform.machine().lower() or "unknown"
        architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(raw_arch, raw_arch)
        try:
            free_disk_mb = int(shutil.disk_usage(storage.RUNTIME_DIR).free / (1024 * 1024))
        except OSError:
            free_disk_mb = None
        gpu_vendor = None
        gpu_name = None
        gpu_memory_mb = None
        cuda_available: bool | None = False
        directml_available: bool | None = False if operating_system == "windows" else None
        mps_available: bool | None = operating_system == "macos" and architecture == "arm64"
        if mps_available:
            gpu_vendor = "Apple"
            gpu_name = "Apple Silicon integrated GPU"
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                result = subprocess.run(
                    [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2, check=False,
                )
                first = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
                if first:
                    name, memory = [part.strip() for part in first.split(",", 1)]
                    gpu_vendor, gpu_name, gpu_memory_mb, cuda_available = "NVIDIA", name, int(memory), True
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                cuda_available = None
        reasons: list[str] = []
        status: Compatibility = "compatible"
        memory = _memory_mb()
        if memory is None or free_disk_mb is None:
            status = "unknown"
            reasons.append("部分硬件信息无法确认。")
        else:
            reasons.append("当前设备满足安全测试能力包的最低要求。")
        if not any((cuda_available, mps_available, directml_available)):
            status = "compatible_but_slow" if status == "compatible" else status
            reasons.append("未检测到可确认的 GPU 加速；本地生成可能较慢。")
        return HardwareCapability(
            operating_system=operating_system, architecture=architecture,
            memory_mb=memory, free_disk_mb=free_disk_mb, gpu_vendor=gpu_vendor,
            gpu_name=gpu_name, gpu_memory_mb=gpu_memory_mb, cuda_available=cuda_available,
            directml_available=directml_available, mps_available=mps_available,
            status=status, reasons=reasons, speed_estimate=None, checked_at=checked_at,
        )
    except Exception:
        return HardwareCapability(
            operating_system="unknown", architecture="unknown", status="unknown",
            reasons=["硬件检测失败，Provider 列表仍可使用。"], checked_at=checked_at,
        )


def _hub_state() -> dict[str, Any]:
    return _read_mapping(_HUB_STATE_FILE)


def _update_hub_state(key: str, value: Any) -> None:
    _update_mapping(_HUB_STATE_FILE, lambda current: {**current, key: value})


def _online_config() -> PublicOnlineProviderConfig:
    settings = storage.read_provider_settings()
    return PublicOnlineProviderConfig(
        endpoint=settings.image.endpoint_url or "https://api.openai.com/v1",
        model=settings.image.model or "gpt-image-2",
        api_key_present=bool(settings.image.api_key.strip()),
    )


def save_online_config(request: OnlineProviderConfigRequest) -> PublicOnlineProviderConfig:
    settings = storage.read_provider_settings()
    api_key = (request.api_key or "").strip() or settings.image.api_key
    if not api_key:
        raise ProviderHubError("authentication_error", "API Key is required before this Provider can be configured")
    settings.image = ImageProviderSettings(
        provider=_ONLINE_PROVIDER_ID,
        endpoint_url=request.endpoint,
        api_key=api_key,
        model=request.model,
    )
    settings.capabilities = {
        **settings.capabilities,
        "image": {
            "providerId": _ONLINE_PROVIDER_ID,
            "values": {"base_url": request.endpoint, "model": request.model, "api_key": api_key},
        },
    }
    storage.write_provider_settings(settings)
    _update_hub_state("online_disabled", False)
    return _online_config()


def delete_online_config() -> PublicOnlineProviderConfig:
    settings = storage.read_provider_settings()
    settings.image = ImageProviderSettings()
    capabilities = dict(settings.capabilities)
    if (capabilities.get("image") or {}).get("providerId") == _ONLINE_PROVIDER_ID:
        capabilities.pop("image", None)
    settings.capabilities = capabilities
    storage.write_provider_settings(settings)
    state = _hub_state()
    state.pop("online_health", None)
    state["online_disabled"] = False
    _update_mapping(_HUB_STATE_FILE, lambda _current: state)
    return _online_config()


def _default_connection_check(endpoint: str, api_key: str, model: str) -> None:
    parsed = urlparse(endpoint)
    connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=8)
    path = f"{parsed.path.rstrip('/')}/models/{model}"
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        response = connection.getresponse()
        response.read(4096)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ProviderHubError("network_error", "The Provider could not be reached") from exc
    finally:
        connection.close()
    if response.status in {401, 403}:
        raise ProviderHubError("authentication_error", "The Provider rejected the API Key")
    if response.status == 429:
        raise ProviderHubError("rate_limited", "The Provider rate limit was reached")
    if response.status >= 400:
        raise ProviderHubError("health_check_failed", "The Provider connection test failed")


CONNECTION_CHECKER: Callable[[str, str, str], None] = _default_connection_check


def test_online_connection() -> ProviderHubItem:
    settings = storage.read_provider_settings()
    if settings.image.provider != _ONLINE_PROVIDER_ID or not settings.image.api_key.strip():
        raise ProviderHubError("authentication_error", "Configure an API Key before testing this Provider")
    _update_hub_state("online_health", {"status": "checking", "checked_at": _iso()})
    try:
        CONNECTION_CHECKER(settings.image.endpoint_url, settings.image.api_key, settings.image.model)
    except ProviderHubError as exc:
        _update_hub_state("online_health", {"status": "degraded", "checked_at": _iso(), "error": {"code": exc.code, "message": exc.message}})
        raise
    _update_hub_state("online_health", {"status": "ready", "checked_at": _iso()})
    return next(item for item in hub_catalog().providers if item.id == _ONLINE_PACKAGE_ID)


def set_online_disabled(disabled: bool) -> ProviderHubItem:
    _update_hub_state("online_disabled", disabled)
    return next(item for item in hub_catalog().providers if item.id == _ONLINE_PACKAGE_ID)


def _last_refresh_at() -> str | None:
    try:
        return registry_status().source.fetched_at
    except ProviderRegistryError:
        return None


def _local_package_item(hardware: HardwareCapability) -> ProviderHubItem:
    state = _hub_state().get("local_image") if isinstance(_hub_state().get("local_image"), dict) else {}
    latest = latest_install_task(_LOCAL_PACKAGE_ID, recover_interrupted=True)
    installing = bool(latest and latest.state in {"queued", "running"})
    installed = bool(state.get("installed"))
    ready = bool(state.get("ready")) and installed
    compatible = hardware.status
    if hardware.free_disk_mb is not None and hardware.free_disk_mb < 1:
        compatible = "unsupported"
    status: HubStatus = "installing" if installing else "ready" if ready else "installed" if installed else "not_installed"
    if compatible == "unsupported":
        status = "incompatible"
    actions: list[HubAction] = ["view_details", "open_project"]
    if installing:
        actions.append("cancel_install")
    elif compatible != "unsupported" and not ready:
        actions.append("repair" if installed else "install")
    if installed:
        actions.append("check_health")
    return ProviderHubItem(
        id=_LOCAL_PACKAGE_ID, provider_id="fixture_local_image", name="本地基础生图",
        description="用于词汇图片、教学插图和课件配图的安全小型能力包演练。",
        provider_type="offline", capabilities=["text_to_image", "teaching_illustration", "vocabulary_image"],
        trust_level="official_verified", registry_source="official_registry", status=status,
        installed=installed, configured=installed, ready=ready, compatible=compatible,
        available_actions=actions, recommended=True, requires_download=True,
        runs_locally=True, uploads_data=False, version="1.0.0", publisher="HanClassStudio",
        source_links=SourceLinks(
            project_url="https://github.com/xueyang-dev/HanClassStudio",
            license_url="https://github.com/xueyang-dev/HanClassStudio/blob/main/LICENSE",
        ),
        license=LicenseInfo(
            name="MIT", url="https://github.com/xueyang-dev/HanClassStudio/blob/main/LICENSE",
            redistribution_allowed=True, clear=True,
        ),
        capability_package=CapabilityPackageSpec(
            id=_LOCAL_PACKAGE_ID, name="本地基础生图", description="安全 fixture 验证安装、校验、健康检查和失败清理。",
            runtime=RuntimeSpec(id="fixture-runtime", name="Fixture Runtime", version="1.0.0", execution="local_fixture"),
            model_packages=[ModelPackageSpec(id="fixture-safe-image-model", name="安全测试模型元数据", version="1.0.0", format="json", safe_format=True)],
            workflow_packs=[WorkflowPackSpec(id="teaching-illustration-fixture-v1", name="教学插图测试工作流", version="1.0.0", capabilities=["teaching_illustration", "vocabulary_image"])],
            healthcheck="installed fixture digest and deterministic smoke test",
        ),
        last_health_check_at=state.get("checked_at"), technical_error=state.get("error"),
    )


def _video_package_item(hardware: HardwareCapability) -> ProviderHubItem:
    ffmpeg = shutil.which("ffmpeg")
    ready = bool(ffmpeg)
    return ProviderHubItem(
        id=_VIDEO_PACKAGE_ID, provider_id="ffmpeg_basic", name="教学视频基础版",
        description="使用图片、字幕、TTS 时间轴、简单转场与 FFmpeg 合成教学视频。",
        provider_type="offline", capabilities=["teaching_video", "subtitle_timeline", "ffmpeg_composition"],
        trust_level="official_verified", registry_source="builtin", status="ready" if ready else "unavailable",
        installed=ready, configured=ready, ready=ready, compatible=hardware.status,
        available_actions=["view_details", "open_project", "check_health"] if ready else ["view_details", "open_project"],
        recommended=True, requires_download=False, runs_locally=True, uploads_data=False,
        publisher="FFmpeg contributors", source_links=SourceLinks(
            official_website_url="https://ffmpeg.org/", project_url="https://github.com/FFmpeg/FFmpeg",
            license_url="https://ffmpeg.org/legal.html",
        ),
        license=LicenseInfo(name="LGPL/GPL (build dependent)", url="https://ffmpeg.org/legal.html", clear=True),
        capability_package=CapabilityPackageSpec(
            id=_VIDEO_PACKAGE_ID, name="教学视频基础版", description="非生成式视频合成能力。",
            runtime=RuntimeSpec(id="ffmpeg", name="FFmpeg", version="system", execution="local_process"),
            workflow_packs=[WorkflowPackSpec(id="teaching-video-basic-v1", name="基础教学视频合成", version="1.0.0", capabilities=["subtitle_timeline", "simple_transitions"])],
            healthcheck="ffmpeg executable availability",
        ),
    )


def _online_package_item(hardware: HardwareCapability) -> ProviderHubItem:
    settings = storage.read_provider_settings()
    configured = settings.image.provider == _ONLINE_PROVIDER_ID and bool(settings.image.api_key.strip())
    state = _hub_state()
    disabled = bool(state.get("online_disabled"))
    health = state.get("online_health") if isinstance(state.get("online_health"), dict) else {}
    status: HubStatus
    ready = configured and health.get("status") == "ready" and not disabled
    if disabled:
        status = "disabled"
    elif not configured:
        status = "not_configured"
    elif health.get("status") == "checking":
        status = "checking"
    elif health.get("status") == "degraded":
        status = "degraded"
    elif ready:
        status = "ready"
    else:
        status = "configured"
    actions: list[HubAction] = ["view_details", "open_project", "open_api_application"]
    if disabled:
        actions.append("enable")
    else:
        actions.extend(["configure", "disable"])
        if configured:
            actions.extend(["test_connection", "delete_configuration"])
    return ProviderHubItem(
        id=_ONLINE_PACKAGE_ID, provider_id=_ONLINE_PROVIDER_ID, name="在线高质量生图",
        description="通过用户自己的 OpenAI API Key 生成或编辑教学图片；内容会上传到第三方服务。",
        provider_type="online", capabilities=["text_to_image", "image_edit", "teaching_illustration"],
        trust_level="community_verified", registry_source="builtin", status=status,
        configured=configured, ready=ready, compatible=hardware.status, available_actions=actions,
        recommended=True, requires_api_key=True, paid_service=True, runs_locally=False, uploads_data=True,
        version="api", publisher="OpenAI", source_links=SourceLinks(
            official_website_url="https://openai.com/api/", api_application_url="https://platform.openai.com/api-keys",
            api_docs_url="https://platform.openai.com/docs/", pricing_url="https://openai.com/api/pricing/",
            terms_url="https://openai.com/policies/service-terms/", privacy_url="https://openai.com/policies/privacy-policy/",
        ),
        license=LicenseInfo(name="Service terms", url="https://openai.com/policies/service-terms/", clear=True),
        capability_package=CapabilityPackageSpec(
            id=_ONLINE_PACKAGE_ID, name="在线高质量生图", description="在线图片生成与编辑能力。",
            workflow_packs=[WorkflowPackSpec(id="online-teaching-image-v1", name="在线教学图片", version="1.0.0", capabilities=["text_to_image", "image_edit"])],
            healthcheck="authenticated model endpoint request",
        ),
        last_health_check_at=health.get("checked_at"), technical_error=health.get("error"),
    )


def isolate_provider_manifests(raw_items: list[dict[str, Any]]) -> tuple[list[ProviderHubItem], list[dict[str, str]]]:
    """Validate entries independently so one malformed item cannot hide peers."""
    valid: list[ProviderHubItem] = []
    errors: list[dict[str, str]] = []
    for index, raw in enumerate(raw_items):
        try:
            valid.append(ProviderHubItem.model_validate(raw))
        except ValueError:
            errors.append({
                "code": "invalid_manifest",
                "entry": str(raw.get("id") or raw.get("provider_id") or index)[:160],
            })
    return valid, errors


def _adapt_existing_providers(existing_ids: set[str]) -> tuple[list[ProviderHubItem], list[dict[str, str]]]:
    items: list[ProviderHubItem] = []
    errors: list[dict[str, str]] = []
    try:
        descriptors = provider_capability_catalog(storage.read_provider_settings())
    except ProviderRegistryError:
        descriptors = []
    for descriptor in descriptors:
        item_id = f"provider.{descriptor.capability}.{descriptor.provider_id}"
        if descriptor.provider_id == _ONLINE_PROVIDER_ID or item_id in existing_ids:
            continue
        local = descriptor.category == "local"
        requires_key = any(field.get("required") and field.get("type") == "password" for field in descriptor.configuration_schema)
        if not descriptor.implemented:
            status: HubStatus = "unavailable"
        elif descriptor.available and (descriptor.configured or not descriptor.configuration_schema):
            status = "ready"
        elif requires_key and not descriptor.configured:
            status = "not_configured"
        else:
            status = "available"
        actions: list[HubAction] = ["view_details"]
        if descriptor.repository_url or descriptor.official_homepage_url:
            actions.append("open_project")
        if descriptor.api_signup_url:
            actions.append("open_api_application")
        if descriptor.configurable:
            actions.append("configure")
        raw = ProviderHubItem(
            id=item_id, provider_id=descriptor.provider_id, name=descriptor.display_name,
            description=descriptor.description, provider_type="offline" if local else "online",
            capabilities=[descriptor.capability, *descriptor.supported_operations],
            trust_level="official_verified" if descriptor.provider_id.startswith("hcs_") or descriptor.provider_id in {"deterministic", "placeholder"} else "community_verified",
            registry_source="official_registry" if descriptor.install_state else "builtin", status=status,
            installed=descriptor.install_state in {"installed", "configuring", "available"},
            configured=descriptor.configured, ready=status == "ready", compatible="unknown",
            available_actions=actions, requires_api_key=requires_key, runs_locally=local, uploads_data=not local,
            version=descriptor.installed_version or descriptor.available_version,
            update_channel="experimental" if descriptor.experimental else "stable",
            source_links=SourceLinks(
                official_website_url=descriptor.official_homepage_url,
                project_url=descriptor.repository_url,
                api_application_url=descriptor.api_signup_url,
                api_docs_url=descriptor.api_docs_url,
                terms_url=descriptor.terms_url,
                privacy_url=descriptor.privacy_url,
                model_url=descriptor.model_card_url,
                license_url=descriptor.code_license_url,
            ),
            license=LicenseInfo(
                name=descriptor.code_license_name, url=descriptor.code_license_url,
                redistribution_allowed=False, clear=bool(descriptor.code_license_name and descriptor.code_license_url),
            ),
            technical_error=descriptor.failure,
        ).model_dump(mode="json")
        valid, isolated = isolate_provider_manifests([raw])
        items.extend(valid)
        errors.extend(isolated)
    return items, errors


def hub_catalog() -> ProviderHubCatalog:
    hardware = detect_hardware()
    featured = [_video_package_item(hardware), _local_package_item(hardware), _online_package_item(hardware)]
    adapted, errors = _adapt_existing_providers({item.id for item in featured})
    providers = [*featured, *adapted]
    return ProviderHubCatalog(providers=providers, hardware=hardware, last_refresh_at=_last_refresh_at(), isolated_errors=errors)


_install_lock = threading.RLock()
_install_threads: dict[str, threading.Thread] = {}
_cancelled_tasks: set[str] = set()


def _save_install_task(task: ProviderInstallTask) -> None:
    _update_mapping(_INSTALL_TASK_FILE, lambda current: {**current, task.task_id: task.model_dump(mode="json")})


def get_install_task(task_id: str) -> ProviderInstallTask:
    raw = _read_mapping(_INSTALL_TASK_FILE).get(task_id)
    if not isinstance(raw, dict):
        raise ProviderHubError("task_not_found", "Installation task was not found")
    return ProviderInstallTask.model_validate(raw)


def latest_install_task(package_id: str, *, recover_interrupted: bool = False) -> ProviderInstallTask | None:
    tasks: list[ProviderInstallTask] = []
    for raw in _read_mapping(_INSTALL_TASK_FILE).values():
        if isinstance(raw, dict):
            try:
                task = ProviderInstallTask.model_validate(raw)
            except ValueError:
                continue
            if task.package_id == package_id:
                tasks.append(task)
    if not tasks:
        return None
    task = max(tasks, key=lambda item: item.started_at)
    if recover_interrupted and task.state in {"queued", "running"} and task.task_id not in _install_threads:
        task.state, task.phase, task.cancellable = "failed", "failed", False
        task.finished_at = task.updated_at = _iso()
        task.error = {"code": "installation_failed", "message": "Installation was interrupted; start again."}
        task.recoverable_actions = ["repair"]
        _save_install_task(task)
    return task


def _update_install_task(task_id: str, *, state: TaskState | None = None, phase: InstallPhase | None = None, progress: int | None = None, message: str | None = None, downloaded_bytes: int | None = None, total_bytes: int | None = None, current_file_progress: int | None = None, error: dict[str, Any] | None = None) -> ProviderInstallTask:
    task = get_install_task(task_id)
    if state is not None:
        task.state = state
    if phase is not None:
        task.phase = phase
    if progress is not None:
        task.progress = progress
    if message is not None:
        task.message = message
    if downloaded_bytes is not None:
        task.downloaded_bytes = downloaded_bytes
    if total_bytes is not None:
        task.total_bytes = total_bytes
    if current_file_progress is not None:
        task.current_file_progress = current_file_progress
    task.error = error
    task.cancel_requested = task_id in _cancelled_tasks
    task.updated_at = _iso()
    if task.state in {"completed", "failed", "cancelled"}:
        task.finished_at = task.updated_at
        task.cancellable = False
        task.recoverable_actions = ["repair"] if task.state == "failed" else []
    _save_install_task(task)
    return task


def _check_cancelled(task_id: str) -> None:
    if task_id in _cancelled_tasks:
        raise ProviderHubError("cancelled", "Installation was cancelled")


def _phase(task_id: str, phase: InstallPhase, progress: int, message: str) -> None:
    _check_cancelled(task_id)
    _update_install_task(task_id, state="running", phase=phase, progress=progress, message=message)
    time.sleep(_INSTALL_STEP_DELAY_SECONDS)


def _run_fixture_install(task_id: str) -> None:
    target_file: Path | None = None
    staged_target: Path | None = None
    previous_bytes: bytes | None = None
    previous_local_state: Any = None

    def restore_previous_target() -> None:
        if staged_target is not None:
            try:
                staged_target.unlink()
            except FileNotFoundError:
                pass
        if target_file is None:
            return
        try:
            if previous_bytes is None:
                target_file.unlink()
            else:
                restore_file = target_file.with_suffix(".restore.tmp")
                restore_file.write_bytes(previous_bytes)
                os.replace(restore_file, target_file)
        except (FileNotFoundError, OSError):
            pass

    def restore_previous_state() -> None:
        def restore(current: dict[str, Any]) -> dict[str, Any]:
            restored = dict(current)
            if isinstance(previous_local_state, dict):
                restored["local_image"] = previous_local_state
            else:
                restored.pop("local_image", None)
            return restored

        try:
            _update_mapping(_HUB_STATE_FILE, restore)
        except ProviderRegistryError:
            pass

    try:
        previous_local_state = _hub_state().get("local_image")
        _phase(task_id, "preflight", 4, "正在检查设备和安装目录")
        hardware = detect_hardware()
        if hardware.free_disk_mb is not None and hardware.free_disk_mb < 1:
            raise ProviderHubError("insufficient_disk", "可用磁盘空间不足")
        if not _FIXTURE_PATH.is_file() or _FIXTURE_PATH.suffix != ".json":
            raise ProviderHubError("unsafe_artifact", "测试能力包文件类型不安全")
        size = _FIXTURE_PATH.stat().st_size
        if size > _FIXTURE_MAX_BYTES:
            raise ProviderHubError("unsafe_artifact", "测试能力包超过大小上限")
        _phase(task_id, "resolving", 10, "正在解析固定版本能力包")
        temp_root = storage.RUNTIME_DIR / "provider-installs"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="hcs-local-image-", dir=temp_root) as temp_name:
            staged = Path(temp_name) / "package.json"
            _update_install_task(task_id, state="running", phase="downloading", progress=15, message="正在复制安全测试能力包", total_bytes=size)
            copied = 0
            with _FIXTURE_PATH.open("rb") as source, staged.open("wb") as destination:
                while True:
                    _check_cancelled(task_id)
                    chunk = source.read(4096)
                    if not chunk:
                        break
                    destination.write(chunk)
                    copied += len(chunk)
                    _update_install_task(task_id, downloaded_bytes=copied, total_bytes=size, current_file_progress=int(copied * 100 / size), message="正在复制安全测试能力包")
                    time.sleep(_INSTALL_STEP_DELAY_SECONDS)
                destination.flush()
                os.fsync(destination.fileno())
            _phase(task_id, "verifying", 35, "正在校验 SHA-256")
            digest = hashlib.sha256(staged.read_bytes()).hexdigest()
            if digest != _FIXTURE_SHA256:
                raise ProviderHubError("checksum_mismatch", "能力包 SHA-256 校验失败")
            _phase(task_id, "extracting", 48, "正在验证能力包结构（JSON fixture 无压缩解包）")
            try:
                payload = json.loads(staged.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderHubError("invalid_manifest", "能力包清单无效") from exc
            if payload.get("schema") != "hanclassstudio.capability_fixture.v1" or payload.get("package_id") != _LOCAL_PACKAGE_ID:
                raise ProviderHubError("invalid_manifest", "能力包身份或 schema 无效")
            if payload.get("runtime", {}).get("bind_host") != "127.0.0.1":
                raise ProviderHubError("unsafe_artifact", "本地 Runtime 必须绑定 127.0.0.1")
            _phase(task_id, "installing_runtime", 60, "正在安装测试 Runtime 元数据")
            if payload.get("runtime", {}).get("id") != "fixture-runtime":
                raise ProviderHubError("invalid_manifest", "Runtime 声明无效")
            _phase(task_id, "installing_model", 70, "正在安装安全模型元数据")
            if payload.get("model_package", {}).get("format") != "json" or payload.get("model_package", {}).get("executable_code") is not False:
                raise ProviderHubError("unsafe_artifact", "模型格式或可执行代码声明不安全")
            _phase(task_id, "installing_workflow", 80, "正在安装教学插图测试工作流")
            if payload.get("workflow_pack", {}).get("id") != "teaching-illustration-fixture-v1":
                raise ProviderHubError("invalid_manifest", "Workflow Pack 声明无效")
            _phase(task_id, "starting", 86, "正在激活测试能力包")
            target_root = (storage.RUNTIME_DIR / "providers" / _LOCAL_PACKAGE_ID / "1.0.0").resolve()
            allowed_root = (storage.RUNTIME_DIR / "providers").resolve()
            if not target_root.is_relative_to(allowed_root):
                raise ProviderHubError("unsafe_artifact", "安装目标越出允许目录")
            target_root.mkdir(parents=True, exist_ok=True)
            target_file = target_root / "package.json"
            previous_bytes = target_file.read_bytes() if target_file.is_file() else None
            staged_target = target_root / ".package.json.tmp"
            shutil.copyfile(staged, staged_target)
            os.replace(staged_target, target_file)
            _phase(task_id, "health_check", 92, "正在检查已安装文件")
            if hashlib.sha256(target_file.read_bytes()).hexdigest() != _FIXTURE_SHA256:
                raise ProviderHubError("health_check_failed", "安装后的文件校验失败")
            _phase(task_id, "smoke_test", 97, "正在运行确定性教学插图冒烟测试")
            if json.loads(target_file.read_text(encoding="utf-8")).get("smoke_test") != "deterministic-teaching-illustration-ok":
                raise ProviderHubError("health_check_failed", "能力包冒烟测试失败")
        checked_at = _iso()
        _update_hub_state("local_image", {"installed": True, "ready": True, "version": "1.0.0", "sha256": _FIXTURE_SHA256, "checked_at": checked_at})
        _update_install_task(task_id, state="completed", phase="completed", progress=100, current_file_progress=100, message="本地基础生图测试能力包已安装并通过健康检查")
    except ProviderHubError as exc:
        restore_previous_target()
        restore_previous_state()
        state: TaskState = "cancelled" if exc.code == "cancelled" else "failed"
        phase: InstallPhase = "cancelled" if exc.code == "cancelled" else "failed"
        _update_install_task(task_id, state=state, phase=phase, message=exc.message, error={"code": exc.code, "message": exc.message})
    except Exception:
        restore_previous_target()
        restore_previous_state()
        _update_install_task(task_id, state="failed", phase="failed", message="安装任务意外失败", error={"code": "internal_error", "message": "安装任务意外失败"})
    finally:
        with _install_lock:
            _install_threads.pop(task_id, None)
            _cancelled_tasks.discard(task_id)


def start_fixture_install(package_id: str) -> ProviderInstallStartResponse:
    if package_id != _LOCAL_PACKAGE_ID:
        raise ProviderHubError("installation_failed", "This capability package does not have an installer")
    with _install_lock:
        active = latest_install_task(package_id)
        if active and active.state in {"queued", "running"} and active.task_id in _install_threads:
            raise ProviderHubError("task_conflict", "An installation task is already running")
        now = _iso()
        task = ProviderInstallTask(
            task_id=uuid.uuid4().hex, package_id=package_id, state="queued", phase="preflight",
            message="安装任务已排队", started_at=now, updated_at=now,
            log_ref=f"provider-hub-install:{package_id}",
        )
        _save_install_task(task)
        thread = threading.Thread(target=_run_fixture_install, args=(task.task_id,), daemon=True, name=f"hcs-install-{task.task_id[:8]}")
        _install_threads[task.task_id] = thread
        provider = _local_package_item(detect_hardware())
        thread.start()
        return ProviderInstallStartResponse(task=task, provider=provider)


def cancel_fixture_install(task_id: str) -> ProviderInstallTask:
    task = get_install_task(task_id)
    if task.state not in {"queued", "running"} or not task.cancellable:
        raise ProviderHubError("cancelled", "This installation task can no longer be cancelled")
    with _install_lock:
        _cancelled_tasks.add(task_id)
    task.cancel_requested = True
    task.message = "正在安全取消安装"
    task.updated_at = _iso()
    _save_install_task(task)
    return task


def check_local_health(package_id: str) -> ProviderHubItem:
    if package_id == _VIDEO_PACKAGE_ID:
        return _video_package_item(detect_hardware())
    if package_id != _LOCAL_PACKAGE_ID:
        raise ProviderHubError("health_check_failed", "Health check is unavailable for this Provider")
    target = storage.RUNTIME_DIR / "providers" / _LOCAL_PACKAGE_ID / "1.0.0" / "package.json"
    healthy = target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == _FIXTURE_SHA256
    checked_at = _iso()
    if healthy:
        _update_hub_state("local_image", {"installed": True, "ready": True, "version": "1.0.0", "sha256": _FIXTURE_SHA256, "checked_at": checked_at})
    else:
        _update_hub_state("local_image", {"installed": target.exists(), "ready": False, "checked_at": checked_at, "error": {"code": "health_check_failed", "message": "Installed fixture is missing or invalid"}})
        raise ProviderHubError("health_check_failed", "Installed fixture is missing or invalid")
    return _local_package_item(detect_hardware())


_refresh_lock = threading.Lock()
_refresh_threads: dict[str, threading.Thread] = {}


def _save_refresh_task(task: ProviderRefreshTask) -> None:
    _update_mapping(_REFRESH_TASK_FILE, lambda current: {**current, task.task_id: task.model_dump(mode="json")})


def get_refresh_task(task_id: str) -> ProviderRefreshTask:
    raw = _read_mapping(_REFRESH_TASK_FILE).get(task_id)
    if not isinstance(raw, dict):
        raise ProviderHubError("task_not_found", "Refresh task was not found")
    task = ProviderRefreshTask.model_validate(raw)
    if task.state in {"queued", "running"} and task_id not in _refresh_threads:
        task.state = "failed"
        task.finished_at = task.updated_at = _iso()
        task.error = {"code": "internal_error", "message": "Provider refresh was interrupted; start it again"}
        _save_refresh_task(task)
    return task


def _refresh_builtin_source() -> tuple[RefreshSourceResult, int, int, int]:
    return (
        RefreshSourceResult(
            source_id="builtin_catalog",
            status="unchanged",
            message="应用内置 Provider 目录可用",
        ),
        0,
        0,
        0,
    )


def _refresh_official_source() -> tuple[RefreshSourceResult, int, int, int]:
    before = {item.entry.provider_id: item.entry.version for item in registry_status().providers}
    result = refresh_registry()
    after = {item.entry.provider_id: item.entry.version for item in result.catalog.providers}
    added = set(after) - set(before)
    # The registry computes digests across each complete manifest, so a change
    # in trust, license, source metadata, or artifacts counts even if the item
    # version string was accidentally left unchanged. Removed entries are also
    # surfaced as changes instead of being hidden in the "unchanged" count.
    updated = set(result.changed_provider_ids) - added
    unchanged = len((set(after) & set(before)) - updated)
    return (
        RefreshSourceResult(
            source_id="official_registry",
            status="updated" if added or updated else "unchanged",
            message="HanClassStudio 官方注册表已检查",
        ),
        len(added),
        len(updated),
        unchanged,
    )


# A source adapter returns its status and item-level change counts. Adding a
# GitHub, Hugging Face, or ComfyUI source requires a new reviewed adapter here;
# remote manifests never supply executable commands.
_REFRESH_SOURCE_ADAPTERS: tuple[Callable[[], tuple[RefreshSourceResult, int, int, int]], ...] = (
    _refresh_builtin_source,
    _refresh_official_source,
)


def _run_refresh(task_id: str) -> None:
    task = get_refresh_task(task_id)
    task.state, task.updated_at = "running", _iso()
    _save_refresh_task(task)
    summary = RefreshSummary()
    error_code: str | None = None
    for adapter in _REFRESH_SOURCE_ADAPTERS:
        try:
            source, added, updated, unchanged = adapter()
            summary.sources.append(source)
            summary.added += added
            summary.updated += updated
            summary.unchanged += unchanged
        except ProviderRegistryError as exc:
            summary.failed_sources += 1
            summary.sources.append(RefreshSourceResult(
                source_id="official_registry", status="failed",
                message="官方注册表暂时不可用，已保留上一次结果",
                retained_previous_snapshot=True,
            ))
            error_code = "network_error" if exc.code == "provider_registry_fetch_failed" else "invalid_manifest"
        except Exception:
            summary.failed_sources += 1
            summary.sources.append(RefreshSourceResult(
                source_id="unknown_source", status="failed",
                message="Provider 来源刷新失败，已保留本地结果",
                retained_previous_snapshot=True,
            ))
            error_code = "internal_error"
    task.summary = summary
    task.state = "partial" if summary.failed_sources else "completed"
    if error_code:
        task.error = {"code": error_code, "message": "Provider refresh was not fully completed"}
    task.finished_at = task.updated_at = _iso()
    _save_refresh_task(task)


def _run_refresh_guarded(task_id: str) -> None:
    try:
        _run_refresh(task_id)
    finally:
        with _refresh_lock:
            _refresh_threads.pop(task_id, None)


def start_refresh() -> ProviderRefreshTask:
    with _refresh_lock:
        if _refresh_threads:
            raise ProviderHubError("task_conflict", "A Provider refresh is already in progress")
        now = _iso()
        task = ProviderRefreshTask(task_id=uuid.uuid4().hex, started_at=now, updated_at=now)
        _save_refresh_task(task)
        thread = threading.Thread(target=_run_refresh_guarded, args=(task.task_id,), daemon=True, name=f"hcs-provider-refresh-{task.task_id[:8]}")
        _refresh_threads[task.task_id] = thread
        thread.start()
        return task
