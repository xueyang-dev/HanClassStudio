"""Backend-authoritative provider registry and safe local installation lifecycle.

The registry in this module is deliberately first-party and mock-only.  It is a
contract and lifecycle fixture for the WebUI; it never clones arbitrary URLs or
executes provider supplied shell commands.  A real installer can replace the
executor behind the same structured interface after a separate security review.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import storage


TrustLevel = Literal["first_party", "verified_maintainer"]
LicenseStatus = Literal["approved", "review_required", "gated"]
ProviderInstallState = Literal[
    "discovered", "ready", "installing", "installed", "configuring", "available", "failed"
]
ConfigurationStatus = Literal["unknown", "missing", "configured", "invalid"]
InstallAction = Literal[
    "prepare_install", "confirm_install", "retry_install", "configure", "rollback", "view_logs"
]
InstallStepKind = Literal[
    "create_isolated_environment",
    "download_and_verify_artifact",
    "checkout_exact_ref",
    "install_controlled_dependencies",
    "verify_model_files",
    "run_configuration_check",
    "run_health_check",
    "activate_version",
    "cleanup_temp_environment",
    "rollback_version",
]


_TRUSTED_SOURCE_REPOSITORIES: dict[str, set[str]] = {
    "github.com": {"xueyang-dev/HanClassStudio"},
    "huggingface.co": set(),
}

_DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/xueyang-dev/HanClassStudio/"
    "main/providers/registry.v1.json"
)
_REGISTRY_SCHEMA = "hanclassstudio.provider_registry.v1"
_REGISTRY_CACHE_FILE = "provider_registry_cache.json"
_MAX_REGISTRY_BYTES = 1_000_000
_MAX_REGISTRY_ENTRIES = 100
_REGISTRY_CONNECT_TIMEOUT_SECONDS = 4.0
_REGISTRY_READ_TIMEOUT_SECONDS = 4.0
_REGISTRY_TOTAL_TIMEOUT_SECONDS = 8.0
_REGISTRY_READ_CHUNK_BYTES = 64 * 1024
_APPROVED_CODE_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
_APPROVED_LINK_HOSTS = {"github.com", "huggingface.co"}
_BUNDLED_CATALOG_VERSION = 1
_BUNDLED_GENERATED_AT = "2026-07-17T00:00:00+00:00"
_BUNDLED_SOURCE_REVISION = "registry-v1.0.0"


class ProviderRegistryError(RuntimeError):
    def __init__(self, code: str, message: str, *, blockers: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = blockers or []


class EnvironmentRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platforms: list[str] = Field(default_factory=lambda: ["linux", "macos", "windows"], min_length=1, max_length=10)
    architectures: list[str] = Field(default_factory=lambda: ["x86_64", "arm64"], min_length=1, max_length=10)
    python: str = Field(default=">=3.11,<3.12", min_length=1, max_length=80)
    min_memory_mb: int = Field(default=256, ge=0, le=1_048_576)
    min_disk_mb: int = Field(default=128, ge=0, le=10_485_760)
    requires_gpu: bool = False
    runtime: str = Field(default="isolated virtual environment", min_length=1, max_length=160)
    model_files: list[str] = Field(default_factory=list, max_length=32)
    api_key_required: bool = False

    @field_validator("platforms", "architectures", "model_files")
    @classmethod
    def _bounded_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError("environment requirement items must be non-empty and bounded")
        return values


class RegistryConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=160)
    type: Literal["text", "password", "url"] = "text"
    required: bool = False
    secret: bool = False
    placeholder: str | None = Field(default=None, max_length=240)


class RegistryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.provider_manifest.v1", alias="schema")
    provider_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=120)
    steps: list[InstallStepKind] = Field(min_length=1, max_length=32)


class ProviderRegistryEntry(BaseModel):
    """A fixed, verifiable registry record safe to expose to the client."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    capability: Literal["llm", "image", "tts", "ocr", "video"]
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    source_url: str = Field(min_length=1, max_length=2048)
    repository: str = Field(min_length=1, max_length=200)
    publisher: str = Field(min_length=1, max_length=160)
    license: str = Field(min_length=1, max_length=120)
    license_status: LicenseStatus
    license_url: str | None = Field(default=None, max_length=2048)
    model_license: str | None = Field(default=None, max_length=120)
    model_license_url: str | None = Field(default=None, max_length=2048)
    trust_level: TrustLevel
    version: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=1, max_length=120)
    checksum_sha256: str
    manifest_version: str
    manifest_digest: str
    manifest: RegistryManifest
    configuration_schema: list[RegistryConfigField] = Field(default_factory=list, max_length=20)
    requirements: EnvironmentRequirement = Field(default_factory=EnvironmentRequirement)
    supported_operations: list[str] = Field(default_factory=list, max_length=20)
    executor: Literal["mock"] = "mock"
    mock_only: bool = True
    experimental: bool = True

    @field_validator("checksum_sha256", "manifest_digest")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("registry digests must be lowercase SHA-256 hex")
        return value.lower()

    @field_validator("source_ref")
    @classmethod
    def _fixed_ref(cls, value: str) -> str:
        if value.lower() in {"main", "master", "latest", "head", "develop"}:
            raise ValueError("floating provider refs are not allowed")
        if not value.strip():
            raise ValueError("provider source_ref is required")
        return value

    @field_validator("version")
    @classmethod
    def _fixed_version(cls, value: str) -> str:
        if not value.strip() or value.lower() in {"main", "master", "latest", "head", "develop"}:
            raise ValueError("provider version must be fixed")
        return value.strip()

    @model_validator(mode="after")
    def _validate_manifest(self) -> "ProviderRegistryEntry":
        if (
            self.manifest.provider_id != self.provider_id
            or self.manifest.version != self.version
            or self.manifest.source_ref != self.source_ref
        ):
            raise ValueError("manifest identity does not match registry entry")
        if self.manifest_version != "1" or self.manifest.schema_ != "hanclassstudio.provider_manifest.v1":
            raise ValueError("unknown provider manifest version")
        digest = _digest(self.manifest.model_dump(mode="json", by_alias=True))
        if digest != self.manifest_digest:
            raise ValueError("manifest digest cannot be verified")
        if self.trust_level not in {"first_party", "verified_maintainer"}:
            raise ValueError("registry source is not trusted")
        source = urlparse(self.source_url)
        host = source.hostname or ""
        if source.scheme != "https" or source.username or source.password or source.port or source.query or source.fragment:
            raise ValueError("registry source must use HTTPS without embedded credentials")
        if host not in {"github.com", "huggingface.co"}:
            raise ValueError("registry source host is not trusted")
        if self.repository not in _TRUSTED_SOURCE_REPOSITORIES.get(host, set()):
            raise ValueError("registry repository is not in the explicit trust store")
        if self.trust_level == "first_party" and self.repository != "xueyang-dev/HanClassStudio":
            raise ValueError("first-party entries must point to the HanClassStudio repository")
        source_parts = [part for part in source.path.strip("/").split("/") if part]
        if len(source_parts) < 2 or "/".join(source_parts[:2]) != self.repository:
            raise ValueError("registry source URL does not match its repository")
        if host == "github.com" and (
            len(source_parts) < 4
            or source_parts[2] not in {"tree", "blob"}
            or source_parts[3] != self.source_ref
        ):
            raise ValueError("registry source URL does not match its fixed source_ref")
        for legal_url in (self.license_url, self.model_license_url):
            if legal_url is None:
                continue
            parsed = urlparse(legal_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in _APPROVED_LINK_HOSTS
                or parsed.username
                or parsed.password
                or parsed.port
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("registry legal links must use an approved HTTPS source")
            legal_parts = [part for part in parsed.path.strip("/").split("/") if part]
            if parsed.hostname == "github.com":
                if len(legal_parts) < 2 or "/".join(legal_parts[:2]) != self.repository:
                    raise ValueError("registry legal link does not match its repository")
                if (
                    len(legal_parts) < 4
                    or legal_parts[2] != "blob"
                    or legal_parts[3] != self.source_ref
                ):
                    raise ValueError("registry legal link does not match its fixed source_ref")
        if self.license_status == "approved":
            if self.license not in _APPROVED_CODE_LICENSES or not self.license_url:
                raise ValueError("approved installation requires a recognized code license and license URL")
            if self.requirements.model_files and (
                self.model_license not in _APPROVED_CODE_LICENSES or not self.model_license_url
            ):
                raise ValueError("approved model installation requires a recognized model-weight license")
        if not self.checksum_sha256:
            raise ValueError("artifact checksum is required")
        if not self.manifest.steps:
            raise ValueError("provider manifest must contain structured steps")
        if any(step == "activate_version" for step in self.manifest.steps) and "cleanup_temp_environment" not in self.manifest.steps:
            raise ValueError("activation plans must include cleanup")
        if any(not operation.strip() or len(operation) > 80 for operation in self.supported_operations):
            raise ValueError("supported operation names must be non-empty and bounded")
        config_keys = [field.key for field in self.configuration_schema]
        if len(config_keys) != len(set(config_keys)):
            raise ValueError("configuration field keys must be unique")
        if any((field.type == "password") != field.secret for field in self.configuration_schema):
            raise ValueError("secret configuration fields must use password controls")
        return self


class EnvironmentBlocker(BaseModel):
    code: str
    message: str
    requirement: str | None = None


class EnvironmentReport(BaseModel):
    platform: str
    architecture: str
    python_version: str
    free_disk_mb: int
    gpu_available: bool = False
    blockers: list[EnvironmentBlocker] = Field(default_factory=list)
    checked_at: str

    @property
    def available(self) -> bool:
        return not self.blockers


class InstallStep(BaseModel):
    kind: InstallStepKind
    label: str


class InstallationPlan(BaseModel):
    plan_id: str
    provider_id: str
    version: str
    source_ref: str
    checksum_sha256: str
    manifest_digest: str
    steps: list[InstallStep]
    environment: EnvironmentReport
    rollback_strategy: str
    created_at: str
    expires_at: str


class ProviderFailure(BaseModel):
    code: str
    message: str
    stage: str | None = None
    recoverable: bool = True


class ProviderInstallationRecord(BaseModel):
    provider_id: str
    capability: str
    install_state: ProviderInstallState = "discovered"
    installed_version: str | None = None
    available_version: str | None = None
    active_version: str | None = None
    previous_version: str | None = None
    configuration_status: ConfigurationStatus = "unknown"
    api_key_present: bool = False
    environment_blockers: list[EnvironmentBlocker] = Field(default_factory=list)
    blockers: list[EnvironmentBlocker] = Field(default_factory=list)
    failure: ProviderFailure | None = None
    rollback_available: bool = False
    current_plan_id: str | None = None
    install_started_at: str | None = None
    updated_at: str = ""


class ProviderInstallLog(BaseModel):
    timestamp: str
    provider_id: str
    plan_id: str | None = None
    stage: str
    operation: str
    message: str
    success: bool | None = None
    failure_code: str | None = None


class ProviderAuditEvent(BaseModel):
    event_id: str
    timestamp: str
    provider_id: str
    plan_id: str | None = None
    manifest_digest: str | None = None
    source: str | None = None
    previous_version: str | None = None
    target_version: str | None = None
    stage: str
    operation: str
    success: bool
    failure_code: str | None = None
    rollback: bool = False
    reason: str | None = None


class RegistryProviderStatus(BaseModel):
    entry: ProviderRegistryEntry
    installation: ProviderInstallationRecord
    environment: EnvironmentReport
    policy_blockers: list[EnvironmentBlocker] = Field(default_factory=list)
    install_actions: list[InstallAction] = Field(default_factory=list)


def _normalize_aware_timestamp(value: str, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


class ProviderRegistryIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: Literal["hanclassstudio.provider_registry.v1"] = Field(
        default=_REGISTRY_SCHEMA,
        alias="schema",
    )
    catalog_version: int = Field(ge=1, le=2_147_483_647)
    generated_at: str = Field(min_length=1, max_length=80)
    source_revision: str = Field(min_length=1, max_length=120)
    content_digest: str = Field(min_length=64, max_length=64)
    providers: list[ProviderRegistryEntry] = Field(min_length=1, max_length=_MAX_REGISTRY_ENTRIES)

    @field_validator("generated_at")
    @classmethod
    def _generated_at_is_aware(cls, value: str) -> str:
        return _normalize_aware_timestamp(value, "catalog generated_at")

    @field_validator("source_revision")
    @classmethod
    def _fixed_catalog_revision(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.lower() in {"main", "master", "latest", "head", "develop"}:
            raise ValueError("floating catalog revisions are not allowed")
        if not (re.fullmatch(r"registry-v\d+\.\d+\.\d+", normalized) or re.fullmatch(r"[0-9a-f]{40}", normalized)):
            raise ValueError("catalog source_revision must be a release revision or commit SHA")
        return normalized

    @field_validator("content_digest")
    @classmethod
    def _content_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("catalog content_digest must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def _verify_catalog_digest(self) -> "ProviderRegistryIndex":
        if self.content_digest != _catalog_digest(
            catalog_version=self.catalog_version,
            generated_at=self.generated_at,
            source_revision=self.source_revision,
            providers=self.providers,
        ):
            raise ValueError("catalog content digest cannot be verified")
        ids = [entry.provider_id for entry in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("Provider IDs must be unique")
        return self


class ProviderRegistryCache(ProviderRegistryIndex):
    source_url: str = Field(min_length=1, max_length=2048)
    fetched_at: str = Field(min_length=1, max_length=80)

    @field_validator("source_url")
    @classmethod
    def _trusted_source_url(cls, value: str) -> str:
        return _validate_registry_feed_url(value)

    @field_validator("fetched_at")
    @classmethod
    def _fetched_at_is_aware(cls, value: str) -> str:
        return _normalize_aware_timestamp(value, "catalog fetched_at")


class RegistrySourceStatus(BaseModel):
    kind: Literal["bundled", "remote"] = "bundled"
    source_url: str | None = None
    fetched_at: str | None = None
    catalog_version: int
    source_revision: str
    content_digest: str


class RegistryCatalogResponse(BaseModel):
    providers: list[RegistryProviderStatus]
    source: RegistrySourceStatus


class RegistryRefreshResponse(BaseModel):
    catalog: RegistryCatalogResponse
    changed_provider_ids: list[str] = Field(default_factory=list)


class InstallPrepareResponse(BaseModel):
    plan: InstallationPlan
    confirmation_token: str
    expires_at: str


class InstallConfirmRequest(BaseModel):
    plan_id: str
    confirmation_token: str


class ProviderConfigureRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class InstallResult(BaseModel):
    installation: ProviderInstallationRecord
    install_actions: list[InstallAction] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _catalog_digest(
    *,
    catalog_version: int,
    generated_at: str,
    source_revision: str,
    providers: list[ProviderRegistryEntry],
) -> str:
    return _digest({
        "schema": _REGISTRY_SCHEMA,
        "catalog_version": catalog_version,
        "generated_at": generated_at,
        "source_revision": source_revision,
        "providers": [entry.model_dump(mode="json", by_alias=True) for entry in providers],
    })


def _build_registry_index(
    providers: list[ProviderRegistryEntry],
    *,
    catalog_version: int,
    generated_at: str,
    source_revision: str,
) -> ProviderRegistryIndex:
    normalized_generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    return ProviderRegistryIndex(
        catalog_version=catalog_version,
        generated_at=normalized_generated_at,
        source_revision=source_revision,
        content_digest=_catalog_digest(
            catalog_version=catalog_version,
            generated_at=normalized_generated_at,
            source_revision=source_revision,
            providers=providers,
        ),
        providers=providers,
    )


_SECRET_KEY_PATTERN = re.compile(
    r"(?i)([\"']?\b(?:api[_-]?key|access[_-]?token|authorization|bearer|password|secret|credential|token)\b[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;}\]]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_URL_SECRET_PATTERN = re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password)=)[^&\s]+")


def _redact_sensitive_text(value: str) -> str:
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    redacted = _SECRET_KEY_PATTERN.sub(r"\1[REDACTED]", redacted)
    return _URL_SECRET_PATTERN.sub(r"\1[REDACTED]", redacted)


def _artifact_checksum(provider_id: str, version: str, source_ref: str) -> str:
    return hashlib.sha256(f"{provider_id}:{version}:{source_ref}".encode("utf-8")).hexdigest()


def _plan_digest(plan: InstallationPlan) -> str:
    return _digest(plan.model_dump(mode="json"))


def _fixture(
    *, provider_id: str, capability: Literal["llm", "image", "tts", "ocr", "video"], display_name: str,
    description: str, operations: list[str], fields: list[RegistryConfigField], requirements: EnvironmentRequirement,
) -> ProviderRegistryEntry:
    version = "0.1.0"
    source_ref = "3bdf0ff2b185aa621c66482ef73bd623e81e9167"
    steps: list[InstallStepKind] = [
        "create_isolated_environment", "download_and_verify_artifact", "checkout_exact_ref",
        "install_controlled_dependencies", "verify_model_files", "run_configuration_check",
        "run_health_check", "activate_version", "cleanup_temp_environment",
    ]
    manifest = RegistryManifest(provider_id=provider_id, version=version, source_ref=source_ref, steps=steps)
    return ProviderRegistryEntry(
        provider_id=provider_id,
        capability=capability,
        display_name=display_name,
        description=description,
        source_url=f"https://github.com/xueyang-dev/HanClassStudio/tree/{source_ref}/providers",
        repository="xueyang-dev/HanClassStudio",
        publisher="HanClassStudio first-party",
        license="MIT",
        license_status="approved",
        license_url=f"https://github.com/xueyang-dev/HanClassStudio/blob/{source_ref}/LICENSE",
        trust_level="first_party",
        version=version,
        source_ref=source_ref,
        checksum_sha256=_artifact_checksum(provider_id, version, source_ref),
        manifest_version="1",
        manifest_digest=_digest(manifest.model_dump(mode="json", by_alias=True)),
        manifest=manifest,
        configuration_schema=fields,
        requirements=requirements,
        supported_operations=operations,
    )


def _bundled_registry_entries() -> list[ProviderRegistryEntry]:
    """Return the repository-controlled mock registry fixture.

    ponytail: two fixtures cover the no-secret and secret-required paths without
    pretending that a real external provider was installed.
    """
    return [
        _fixture(
            provider_id="hcs_mock_ocr",
            capability="ocr",
            display_name="HanClassStudio OCR Sandbox",
            description="Deterministic first-party OCR sandbox for lifecycle testing",
            operations=["source_intake", "ocr"],
            fields=[],
            requirements=EnvironmentRequirement(min_memory_mb=128, min_disk_mb=32, runtime="isolated mock environment"),
        ),
        _fixture(
            provider_id="hcs_mock_llm",
            capability="llm",
            display_name="HanClassStudio LLM Sandbox",
            description="Deterministic first-party LLM sandbox; no external network calls",
            operations=["blueprint"],
            fields=[RegistryConfigField(key="api_key", label="API key", type="password", required=True, secret=True)],
            requirements=EnvironmentRequirement(min_memory_mb=128, min_disk_mb=32, api_key_required=True, runtime="isolated mock environment"),
        ),
    ]


def _bundled_registry_index() -> ProviderRegistryIndex:
    return _build_registry_index(
        _bundled_registry_entries(),
        catalog_version=_BUNDLED_CATALOG_VERSION,
        generated_at=_BUNDLED_GENERATED_AT,
        source_revision=_BUNDLED_SOURCE_REVISION,
    )


def _trusted_registry_index() -> ProviderRegistryIndex:
    """Read the last validated local catalog without attempting recovery online."""
    cache_path = _state_path(_REGISTRY_CACHE_FILE)
    if not cache_path.exists():
        return _bundled_registry_index()
    cached = _read_mapping(_REGISTRY_CACHE_FILE)
    if not cached:
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            "Provider Registry cache could not be validated safely",
        )
    try:
        return ProviderRegistryCache.model_validate(cached)
    except ValueError as exc:
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            "Provider Registry cache could not be validated safely",
        ) from exc


def registry_entries() -> list[ProviderRegistryEntry]:
    """Read the last validated Registry cache without performing network I/O."""
    return _trusted_registry_index().providers


def validate_registry(entries: list[ProviderRegistryEntry] | None = None) -> list[ProviderRegistryEntry]:
    entries = registry_entries() if entries is None else entries
    if not entries:
        raise ProviderRegistryError("provider_registry_empty", "Provider Registry cannot be empty")
    ids = [entry.provider_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ProviderRegistryError("registry_duplicate_provider", "Provider IDs must be unique")
    return entries


def _provider_map() -> dict[str, ProviderRegistryEntry]:
    return {entry.provider_id: entry for entry in validate_registry()}


def _state_path(name: str) -> Path:
    storage.ensure_runtime()
    return storage.CONFIG_DIR / name


_persistence_lock = threading.RLock()
_registry_refresh_lock = threading.Lock()
_provider_locks: dict[str, threading.Lock] = {}
_INSTALL_RECOVERY_AFTER = timedelta(minutes=15)


def _provider_lock(provider_id: str) -> threading.Lock:
    with _persistence_lock:
        return _provider_locks.setdefault(provider_id, threading.Lock())


def _read_mapping(name: str) -> dict[str, Any]:
    path = _state_path(name)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            f"Provider persistence file {path.name} could not be read safely",
        ) from exc
    if not isinstance(value, dict):
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            f"Provider persistence file {path.name} has an invalid shape",
        )
    return value


def _write_mapping(name: str, value: dict[str, Any]) -> None:
    path = _state_path(name)
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    temporary_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        code = "provider_registry_cache_write_failed" if name == _REGISTRY_CACHE_FILE else "provider_persistence_write_failed"
        message = "Provider Registry cache could not be committed safely" if name == _REGISTRY_CACHE_FILE else "Provider persistence could not be committed safely"
        raise ProviderRegistryError(code, message) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _update_mapping(name: str, update: Any) -> dict[str, Any]:
    """Atomically read, transform and replace one mapping under one process lock.

    The lock is intentionally process-local.  The current API is deployed as a
    single worker; multi-worker deployments must add an external lock before
    advertising cross-process installation concurrency.
    """
    with _persistence_lock:
        current = _read_mapping(name)
        next_value = update(current)
        if not isinstance(next_value, dict):
            raise ProviderRegistryError("provider_persistence_invalid_update", "Provider persistence update was invalid")
        _write_mapping(name, next_value)
        return next_value


def _registry_feed_url() -> str:
    return os.environ.get("HCS_PROVIDER_REGISTRY_URL", _DEFAULT_REGISTRY_URL).strip()


def _validate_registry_feed_url(value: str) -> str:
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "raw.githubusercontent.com"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
        or len(parts) < 4
        or parts[:2] != ["xueyang-dev", "HanClassStudio"]
        or parts[-2:] != ["providers", "registry.v1.json"]
    ):
        raise ProviderRegistryError(
            "provider_registry_source_untrusted",
            "Provider Registry refresh source is not an approved HanClassStudio HTTPS feed",
        )
    return value


def _validate_public_registry_host(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderRegistryError(
            "provider_registry_fetch_failed",
            "The official Provider Registry could not be reached",
        ) from exc
    if not addresses:
        raise ProviderRegistryError(
            "provider_registry_fetch_failed",
            "The official Provider Registry could not be reached",
        )
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError as exc:
            raise ProviderRegistryError(
                "provider_registry_source_untrusted",
                "Provider Registry refresh resolved to an unapproved network address",
            ) from exc
        if not ip.is_global:
            raise ProviderRegistryError(
                "provider_registry_source_untrusted",
                "Provider Registry refresh resolved to an unapproved network address",
            )


def _download_registry_index(source_url: str) -> tuple[dict[str, Any], str]:
    approved_url = _validate_registry_feed_url(source_url)
    parsed = urlparse(approved_url)
    hostname = parsed.hostname or ""
    started_at = time.monotonic()
    _validate_public_registry_host(hostname)
    connection = http.client.HTTPSConnection(
        hostname,
        443,
        timeout=_REGISTRY_CONNECT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "GET",
            parsed.path,
            headers={"Accept": "application/json", "User-Agent": "HanClassStudio-ProviderRegistry/1"},
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ProviderRegistryError(
                "provider_registry_source_untrusted",
                "Provider Registry refresh refused an unexpected redirect",
            )
        if response.status != 200:
            raise ProviderRegistryError(
                "provider_registry_fetch_failed",
                "The official Provider Registry could not be reached",
            )
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise ProviderRegistryError(
                    "provider_registry_invalid",
                    "Provider Registry response had invalid metadata",
                ) from exc
            if declared_length < 0 or declared_length > _MAX_REGISTRY_BYTES:
                raise ProviderRegistryError(
                    "provider_registry_too_large",
                    "Provider Registry response exceeded the size limit",
                )
        if connection.sock is not None:
            connection.sock.settimeout(_REGISTRY_READ_TIMEOUT_SECONDS)
        chunks: list[bytes] = []
        bytes_read = 0
        while True:
            if time.monotonic() - started_at > _REGISTRY_TOTAL_TIMEOUT_SECONDS:
                raise ProviderRegistryError(
                    "provider_registry_fetch_failed",
                    "The official Provider Registry request timed out",
                )
            chunk = response.read(_REGISTRY_READ_CHUNK_BYTES)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > _MAX_REGISTRY_BYTES:
                raise ProviderRegistryError(
                    "provider_registry_too_large",
                    "Provider Registry response exceeded the size limit",
                )
            chunks.append(chunk)
        body = b"".join(chunks)
    except ProviderRegistryError:
        raise
    except (TimeoutError, OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise ProviderRegistryError(
            "provider_registry_fetch_failed",
            "The official Provider Registry could not be reached",
        ) from exc
    finally:
        connection.close()
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRegistryError(
            "provider_registry_invalid",
            "Provider Registry response was not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderRegistryError(
            "provider_registry_invalid",
            "Provider Registry response had an invalid shape",
        )
    return payload, approved_url


def registry_source_status() -> RegistrySourceStatus:
    cache_path = _state_path(_REGISTRY_CACHE_FILE)
    if not cache_path.exists():
        bundled = _bundled_registry_index()
        return RegistrySourceStatus(
            catalog_version=bundled.catalog_version,
            source_revision=bundled.source_revision,
            content_digest=bundled.content_digest,
        )
    cached = _read_mapping(_REGISTRY_CACHE_FILE)
    if not cached:
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            "Provider Registry cache could not be validated safely",
        )
    try:
        parsed = ProviderRegistryCache.model_validate(cached)
    except ValueError as exc:
        raise ProviderRegistryError(
            "provider_persistence_corrupt",
            "Provider Registry cache could not be validated safely",
        ) from exc
    return RegistrySourceStatus(
        kind="remote",
        source_url=parsed.source_url,
        fetched_at=parsed.fetched_at,
        catalog_version=parsed.catalog_version,
        source_revision=parsed.source_revision,
        content_digest=parsed.content_digest,
    )


def _append_jsonl(name: str, payload: BaseModel) -> None:
    path = _state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _persistence_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _record_from_json(provider_id: str, entry: ProviderRegistryEntry, payload: Any) -> ProviderInstallationRecord:
    if payload is None:
        return ProviderInstallationRecord(provider_id=provider_id, capability=entry.capability, available_version=entry.version, updated_at=_iso())
    if isinstance(payload, dict):
        try:
            record = ProviderInstallationRecord.model_validate(payload)
            if record.provider_id != provider_id or record.capability != entry.capability:
                raise ValueError("persisted provider identity does not match its registry entry")
            return record
        except ValueError:
            return ProviderInstallationRecord(
                provider_id=provider_id,
                capability=entry.capability,
                available_version=entry.version,
                install_state="failed",
                blockers=[EnvironmentBlocker(code="provider_state_corrupt", message="Persisted provider state is invalid and must be repaired")],
                failure=ProviderFailure(code="provider_state_corrupt", message="Persisted provider state is invalid and must be repaired", stage="persistence", recoverable=True),
                updated_at=_iso(),
            )
    return ProviderInstallationRecord(
        provider_id=provider_id,
        capability=entry.capability,
        available_version=entry.version,
        install_state="failed",
        blockers=[EnvironmentBlocker(code="provider_state_corrupt", message="Persisted provider state is invalid and must be repaired")],
        failure=ProviderFailure(code="provider_state_corrupt", message="Persisted provider state is invalid and must be repaired", stage="persistence", recoverable=True),
        updated_at=_iso(),
    )


def _environment(entry: ProviderRegistryEntry) -> EnvironmentReport:
    storage.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    platform_id = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)
    raw_arch = platform.machine().lower() or "unknown"
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(raw_arch, raw_arch)
    blockers: list[EnvironmentBlocker] = []
    if platform_id not in entry.requirements.platforms:
        blockers.append(EnvironmentBlocker(code="platform_unsupported", message=f"Platform {platform_id} is not supported", requirement=", ".join(entry.requirements.platforms)))
    required_architectures = { {"amd64": "x86_64", "aarch64": "arm64"}.get(item.lower(), item.lower()) for item in entry.requirements.architectures }
    if arch not in required_architectures:
        blockers.append(EnvironmentBlocker(code="architecture_unsupported", message=f"Architecture {arch} is not supported", requirement=", ".join(entry.requirements.architectures)))
    python_version = platform.python_version()
    if entry.requirements.python == ">=3.11,<3.12" and not ((sys.version_info.major, sys.version_info.minor) >= (3, 11) and (sys.version_info.major, sys.version_info.minor) < (3, 12)):
        blockers.append(EnvironmentBlocker(code="python_unsupported", message=f"Python {python_version} is not supported", requirement=entry.requirements.python))
    try:
        free_disk_mb = int(shutil.disk_usage(storage.CONFIG_DIR).free / (1024 * 1024))
    except OSError:
        free_disk_mb = 0
    if free_disk_mb < entry.requirements.min_disk_mb:
        blockers.append(EnvironmentBlocker(code="disk_space_insufficient", message="Not enough free disk space for this provider", requirement=f">={entry.requirements.min_disk_mb} MB"))
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
        memory_mb = int(page_size * page_count / (1024 * 1024))
    except (AttributeError, OSError, ValueError):
        memory_mb = 0
    if memory_mb and memory_mb < entry.requirements.min_memory_mb:
        blockers.append(EnvironmentBlocker(code="memory_insufficient", message="Not enough memory for this provider", requirement=f">={entry.requirements.min_memory_mb} MB"))
    gpu_available = False
    if entry.requirements.requires_gpu and not gpu_available:
        blockers.append(EnvironmentBlocker(code="gpu_unavailable", message="A compatible GPU is required for this provider", requirement="GPU"))
    return EnvironmentReport(
        platform=platform_id,
        architecture=arch,
        python_version=python_version,
        free_disk_mb=free_disk_mb,
        gpu_available=gpu_available,
        blockers=blockers,
        checked_at=_iso(),
    )


TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"ready"},
    "ready": {"installing", "failed"},
    "installing": {"installed", "failed"},
    "installed": {"configuring", "available", "installing", "failed"},
    "configuring": {"available", "failed"},
    "available": {"available", "installing", "configuring"},
    "failed": {"ready", "available"},
}


def _transition(record: ProviderInstallationRecord, target: ProviderInstallState) -> None:
    if target not in TRANSITIONS.get(record.install_state, set()):
        raise ProviderRegistryError(
            "provider_invalid_state_transition",
            f"Cannot transition {record.provider_id} from {record.install_state} to {target}",
        )
    record.install_state = target
    if target == "installing":
        record.install_started_at = _iso()
    elif target in {"installed", "configuring", "available", "failed", "ready"}:
        record.install_started_at = None
    record.updated_at = _iso()


def _save_record(record: ProviderInstallationRecord) -> None:
    _update_mapping(
        "provider_installations.json",
        lambda data: {**data, record.provider_id: record.model_dump(mode="json")},
    )


def _recover_interrupted_installation(record: ProviderInstallationRecord, entry: ProviderRegistryEntry) -> ProviderInstallationRecord:
    if record.install_state != "installing":
        return record
    timestamp = record.install_started_at or record.updated_at
    try:
        started_at = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        started_at = _now() - _INSTALL_RECOVERY_AFTER - timedelta(seconds=1)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if _now() - started_at <= _INSTALL_RECOVERY_AFTER:
        return record
    previous = record.active_version
    record.install_state = "failed"
    record.install_started_at = None
    record.installed_version = previous
    record.active_version = previous
    record.rollback_available = bool(previous)
    record.failure = ProviderFailure(
        code="provider_install_interrupted",
        message="Provider installation was interrupted and must be retried",
        stage="installing",
        recoverable=True,
    )
    record.blockers = [EnvironmentBlocker(code="provider_install_interrupted", message="Provider installation was interrupted and must be retried")]
    record.updated_at = _iso()
    _save_record(record)
    _log(entry.provider_id, "failed", "recover", record.failure.message, plan_id=record.current_plan_id, success=False, failure_code=record.failure.code)
    return record


def _load_record(entry: ProviderRegistryEntry) -> ProviderInstallationRecord:
    record = _record_from_json(entry.provider_id, entry, _read_mapping("provider_installations.json").get(entry.provider_id))
    record.available_version = entry.version
    report = _environment(entry)
    record.environment_blockers = report.blockers
    if record.install_state == "available" and (
        record.configuration_status != "configured"
        or not record.active_version
        or record.blockers
    ):
        record.install_state = "failed"
        record.install_started_at = None
        record.failure = ProviderFailure(
            code="provider_state_inconsistent",
            message="Persisted provider state is inconsistent and must be repaired",
            stage="persistence",
            recoverable=False,
        )
        record.blockers = [EnvironmentBlocker(code="provider_state_inconsistent", message="Persisted provider state is inconsistent and must be repaired")]
        record.rollback_available = False
        record.updated_at = _iso()
        _save_record(record)
    if record.install_state == "discovered" and report.available and not _license_policy_blockers(entry):
        _transition(record, "ready")
        _save_record(record)
    return _recover_interrupted_installation(record, entry)


def _license_policy_blockers(entry: ProviderRegistryEntry) -> list[EnvironmentBlocker]:
    if entry.license_status == "approved":
        return []
    code = "provider_license_gated" if entry.license_status == "gated" else "provider_license_review_required"
    return [EnvironmentBlocker(
        code=code,
        message="Provider installation is unavailable until its code and model licenses are explicitly approved",
        requirement=entry.license_status,
    )]


def _actions(entry: ProviderRegistryEntry, record: ProviderInstallationRecord, report: EnvironmentReport) -> list[InstallAction]:
    if _license_policy_blockers(entry):
        return ["view_logs"] if record.install_state in {"failed", "installing"} else []
    if not report.available:
        return ["view_logs"] if record.install_state in {"failed", "installing"} else []
    state = record.install_state
    if state in {"discovered", "ready"}:
        return ["prepare_install"]
    if state == "failed":
        actions: list[InstallAction] = ["retry_install", "view_logs"]
        if record.failure and record.failure.code in {"provider_state_corrupt", "provider_state_inconsistent"}:
            return ["view_logs"]
        if record.rollback_available:
            actions.append("rollback")
        return actions
    if state in {"installed", "configuring"}:
        return ["configure", "view_logs"] if record.blockers else ["configure", "view_logs"]
    if state == "available":
        actions = ["prepare_install", "view_logs"]
        if record.rollback_available:
            actions.append("rollback")
        return actions
    if state == "installing":
        return ["view_logs"]
    return []


def registry_status() -> RegistryCatalogResponse:
    statuses: list[RegistryProviderStatus] = []
    for entry in validate_registry():
        report = _environment(entry)
        record = _load_record(entry)
        policy_blockers = _license_policy_blockers(entry)
        statuses.append(RegistryProviderStatus(
            entry=entry,
            installation=record,
            environment=report,
            policy_blockers=policy_blockers,
            install_actions=_actions(entry, record, report),
        ))
    return RegistryCatalogResponse(providers=statuses, source=registry_source_status())


def refresh_registry() -> RegistryRefreshResponse:
    """Fetch and atomically activate the official Registry only on explicit request."""
    if not _registry_refresh_lock.acquire(blocking=False):
        raise ProviderRegistryError(
            "provider_registry_refresh_in_progress",
            "A Provider Registry refresh is already in progress",
        )
    try:
        payload, final_url = _download_registry_index(_registry_feed_url())
        try:
            index = ProviderRegistryIndex.model_validate(payload)
        except ValueError as exc:
            raise ProviderRegistryError(
                "provider_registry_invalid",
                "Provider Registry response failed schema validation",
            ) from exc
        entries = validate_registry(index.providers)
        trusted = _trusted_registry_index()
        if index.catalog_version < trusted.catalog_version:
            raise ProviderRegistryError(
                "provider_registry_rollback_rejected",
                "Provider Registry refresh was older than the active trusted catalog",
            )
        if index.catalog_version == trusted.catalog_version and index.content_digest != trusted.content_digest:
            raise ProviderRegistryError(
                "provider_registry_revision_conflict",
                "Provider Registry reused an active catalog version with different content",
            )
        previous = {
            entry.provider_id: _digest(entry.model_dump(mode="json", by_alias=True))
            for entry in trusted.providers
        }
        current = {
            entry.provider_id: _digest(entry.model_dump(mode="json", by_alias=True))
            for entry in entries
        }
        changed = sorted(
            provider_id
            for provider_id in set(previous) | set(current)
            if previous.get(provider_id) != current.get(provider_id)
        )
        cache = ProviderRegistryCache(
            catalog_version=index.catalog_version,
            generated_at=index.generated_at,
            source_revision=index.source_revision,
            content_digest=index.content_digest,
            providers=entries,
            source_url=final_url,
            fetched_at=_iso(),
        )
        _update_mapping(
            _REGISTRY_CACHE_FILE,
            lambda _current: cache.model_dump(mode="json", by_alias=True),
        )
        return RegistryRefreshResponse(
            catalog=registry_status(),
            changed_provider_ids=changed,
        )
    finally:
        _registry_refresh_lock.release()


def _entry(provider_id: str) -> ProviderRegistryEntry:
    entry = _provider_map().get(provider_id)
    if entry is None:
        raise ProviderRegistryError("provider_not_registered", "Provider is not present in the trusted registry")
    return entry


def _log(provider_id: str, stage: str, operation: str, message: str, *, plan_id: str | None = None, success: bool | None = None, failure_code: str | None = None) -> None:
    sanitized = _redact_sensitive_text(message)[:500]
    _append_jsonl("provider_install_logs.jsonl", ProviderInstallLog(
        timestamp=_iso(), provider_id=provider_id, plan_id=plan_id, stage=stage,
        operation=operation, message=sanitized, success=success, failure_code=failure_code,
    ))


def _audit(provider_id: str, *, plan: InstallationPlan | None, stage: str, operation: str, success: bool, previous_version: str | None = None, target_version: str | None = None, failure_code: str | None = None, rollback: bool = False, reason: str | None = None) -> None:
    _append_jsonl("provider_audit_events.jsonl", ProviderAuditEvent(
        event_id=uuid.uuid4().hex, timestamp=_iso(), provider_id=provider_id,
        plan_id=plan.plan_id if plan else None, manifest_digest=plan.manifest_digest if plan else None,
        source=plan.source_ref if plan else None,
        previous_version=previous_version, target_version=target_version if target_version is not None else (plan.version if plan else None),
        stage=stage, operation=operation, success=success, failure_code=failure_code, rollback=rollback,
        reason=reason,
    ))


class ProviderExecutor:
    def execute(self, entry: ProviderRegistryEntry, plan: InstallationPlan) -> None:
        raise NotImplementedError


class MockProviderExecutor(ProviderExecutor):
    def __init__(self, fail_step: InstallStepKind | None = None) -> None:
        self.fail_step = fail_step

    def execute(self, entry: ProviderRegistryEntry, plan: InstallationPlan) -> None:
        for step in plan.steps:
            _log(entry.provider_id, step.kind, "execute", step.label, plan_id=plan.plan_id, success=True)
            if step.kind == self.fail_step:
                raise ProviderRegistryError("provider_install_step_failed", f"Mock executor failed at {step.kind}")
        expected = _artifact_checksum(entry.provider_id, entry.version, entry.source_ref)
        if expected != entry.checksum_sha256:
            raise ProviderRegistryError("provider_checksum_mismatch", "Artifact checksum verification failed")


EXECUTOR: ProviderExecutor = MockProviderExecutor()


def _install_steps(entry: ProviderRegistryEntry) -> list[InstallStep]:
    sandbox_labels: dict[InstallStepKind, str] = {
        "create_isolated_environment": "Sandbox: simulate an isolated environment",
        "download_and_verify_artifact": "Sandbox: validate fixture checksum (no download)",
        "checkout_exact_ref": "Sandbox: validate fixed source reference (no checkout)",
        "install_controlled_dependencies": "Sandbox: simulate dependency step (no installation)",
        "verify_model_files": "Sandbox: validate fixture metadata (no model files)",
        "run_configuration_check": "Sandbox: run lifecycle configuration check",
        "run_health_check": "Sandbox: run fixture health check",
        "activate_version": "Sandbox: simulate lifecycle activation",
        "cleanup_temp_environment": "Sandbox: simulate cleanup",
        "rollback_version": "Sandbox: simulate lifecycle rollback",
    }
    return [InstallStep(
        kind=kind,
        label=sandbox_labels[kind] if entry.mock_only else kind.replace("_", " ").capitalize(),
    ) for kind in entry.manifest.steps]


def _build_plan(entry: ProviderRegistryEntry, report: EnvironmentReport) -> InstallationPlan:
    if not report.available:
        raise ProviderRegistryError("provider_environment_blocked", "Provider cannot be installed in this environment", blockers=[item.model_dump(mode="json") for item in report.blockers])
    now = _now()
    steps = _install_steps(entry)
    return InstallationPlan(
        plan_id=uuid.uuid4().hex,
        provider_id=entry.provider_id,
        version=entry.version,
        source_ref=entry.source_ref,
        checksum_sha256=entry.checksum_sha256,
        manifest_digest=entry.manifest_digest,
        steps=steps,
        environment=report,
        rollback_strategy=(
            "sandbox lifecycle state retains its prior simulated version; no third-party files are changed"
            if entry.mock_only
            else "retain previous active version until atomic activation succeeds"
        ),
        created_at=_iso(now), expires_at=_iso(now + timedelta(minutes=5)),
    )


def _update_plan_record(plan_id: str, **updates: Any) -> None:
    def update(plans: dict[str, Any]) -> dict[str, Any]:
        stored = plans.get(plan_id)
        if not isinstance(stored, dict):
            raise ProviderRegistryError("provider_plan_invalid", "Installation plan is not available")
        next_stored = {**stored, **updates}
        return {**plans, plan_id: next_stored}

    _update_mapping("provider_install_plans.json", update)


def _mark_install_failed(
    record: ProviderInstallationRecord,
    provider_id: str,
    plan: InstallationPlan,
    previous: str | None,
    failure: ProviderRegistryError,
    *,
    unexpected: Exception | None = None,
) -> None:
    del unexpected  # Never persist or expose an arbitrary executor exception.
    record.install_state = "failed"
    record.install_started_at = None
    record.failure = ProviderFailure(code=failure.code, message=_redact_sensitive_text(failure.message), stage="installing")
    record.blockers = [EnvironmentBlocker(code=failure.code, message=_redact_sensitive_text(failure.message))]
    # Keep the old active version visible as a usable fact after an upgrade failure.
    record.installed_version = previous
    record.active_version = previous
    record.rollback_available = bool(previous)
    record.updated_at = _iso()
    _save_record(record)
    _log(provider_id, "failed", "install", failure.message, plan_id=plan.plan_id, success=False, failure_code=failure.code)
    _audit(provider_id, plan=plan, stage="failed", operation="install", success=False, previous_version=previous, failure_code=failure.code)


def prepare_install(provider_id: str) -> InstallPrepareResponse:
    entry = _entry(provider_id)
    lock = _provider_lock(provider_id)
    with lock:
        if _license_policy_blockers(entry):
            raise ProviderRegistryError(
                "provider_license_not_approved",
                "Provider installation is unavailable until its licenses are explicitly approved",
                blockers=[item.model_dump(mode="json") for item in _license_policy_blockers(entry)],
            )
        report = _environment(entry)
        if not report.available:
            raise ProviderRegistryError(
                "provider_environment_blocked",
                "Provider cannot be installed in this environment",
                blockers=[item.model_dump(mode="json") for item in report.blockers],
            )
        record = _load_record(entry)
        if record.install_state == "installing":
            raise ProviderRegistryError("provider_install_in_progress", "An installation is already running")
        if record.failure and record.failure.code in {"provider_state_corrupt", "provider_state_inconsistent"}:
            raise ProviderRegistryError(record.failure.code, record.failure.message)
        if record.install_state == "failed":
            _transition(record, "ready")
        if record.install_state not in {"ready", "available"}:
            raise ProviderRegistryError("provider_not_ready", f"Provider is {record.install_state}; prepare is unavailable")
        plan = _build_plan(entry, report)
        token = secrets.token_urlsafe(32)
        def save_plan(plans: dict[str, Any]) -> dict[str, Any]:
            if record.current_plan_id and isinstance(plans.get(record.current_plan_id), dict):
                previous_plan = {**plans[record.current_plan_id], "superseded_at": _iso()}
                plans = {**plans, record.current_plan_id: previous_plan}
            plans[plan.plan_id] = {
                "plan": plan.model_dump(mode="json"),
                "plan_digest": _plan_digest(plan),
                "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "provider_id": provider_id,
                "expires_at": plan.expires_at,
            }
            return plans

        _update_mapping("provider_install_plans.json", save_plan)
        record.current_plan_id = plan.plan_id
        record.blockers = []
        record.failure = None
        record.updated_at = _iso()
        _save_record(record)
        _audit(provider_id, plan=plan, stage="ready", operation="prepare", success=True, previous_version=record.active_version)
        return InstallPrepareResponse(plan=plan, confirmation_token=token, expires_at=plan.expires_at)


def confirm_install(provider_id: str, request: InstallConfirmRequest) -> InstallResult:
    entry = _entry(provider_id)
    lock = _provider_lock(provider_id)
    with lock:
        plans = _read_mapping("provider_install_plans.json")
        stored = plans.get(request.plan_id)
        if not isinstance(stored, dict) or stored.get("provider_id") != provider_id:
            raise ProviderRegistryError("provider_plan_invalid", "Installation plan is not bound to this provider")
        if stored.get("superseded_at"):
            raise ProviderRegistryError("provider_plan_stale", "Installation plan has been superseded by a newer plan")
        if stored.get("consumed_at"):
            raise ProviderRegistryError("provider_plan_consumed", "Installation plan has already been confirmed")
        try:
            plan = InstallationPlan.model_validate(stored.get("plan"))
        except ValueError as exc:
            raise ProviderRegistryError("provider_plan_invalid", "Installation plan is invalid") from exc
        try:
            expires_at = datetime.fromisoformat(plan.expires_at)
        except ValueError as exc:
            raise ProviderRegistryError("provider_plan_invalid", "Installation plan expiry is invalid") from exc
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= _now():
            raise ProviderRegistryError("provider_plan_expired", "Installation confirmation has expired")
        expected_token = str(stored.get("token_hash", ""))
        if not secrets.compare_digest(expected_token, hashlib.sha256(request.confirmation_token.encode("utf-8")).hexdigest()):
            raise ProviderRegistryError("provider_confirmation_invalid", "Installation confirmation token is invalid")
        expected_steps = [step.model_dump(mode="json") for step in _install_steps(entry)]
        actual_steps = [step.model_dump(mode="json") for step in plan.steps]
        if (
            plan.provider_id != provider_id
            or plan.source_ref != entry.source_ref
            or plan.manifest_digest != entry.manifest_digest
            or plan.checksum_sha256 != entry.checksum_sha256
            or plan.version != entry.version
            or actual_steps != expected_steps
            or stored.get("plan_digest") != _plan_digest(plan)
        ):
            raise ProviderRegistryError("provider_plan_stale", "Installation plan no longer matches the registry manifest")
        record = _load_record(entry)
        if record.current_plan_id != plan.plan_id:
            raise ProviderRegistryError("provider_plan_stale", "Installation plan is no longer the active plan")
        if record.install_state == "installing":
            raise ProviderRegistryError("provider_install_in_progress", "An installation is already running")
        if record.install_state not in {"ready", "available"}:
            raise ProviderRegistryError("provider_not_ready", f"Provider is {record.install_state}; confirmation is unavailable")
        report = _environment(entry)
        if not report.available:
            raise ProviderRegistryError(
                "provider_environment_blocked",
                "Provider cannot be installed in this environment",
                blockers=[item.model_dump(mode="json") for item in report.blockers],
            )
        previous = record.active_version
        _transition(record, "installing")
        record.current_plan_id = plan.plan_id
        record.failure = None
        record.blockers = []
        _save_record(record)
        _update_plan_record(plan.plan_id, consumed_at=_iso())
        _audit(provider_id, plan=plan, stage="installing", operation="confirm", success=True, previous_version=previous)
        try:
            EXECUTOR.execute(entry, plan)
            _transition(record, "installed")
            record.installed_version = entry.version
            record.previous_version = previous
            record.active_version = entry.version
            record.rollback_available = bool(previous and previous != entry.version)
            _transition(record, "configuring")
            required = [field for field in entry.configuration_schema if field.required]
            if required:
                record.configuration_status = "missing"
                record.blockers = [EnvironmentBlocker(code="configuration_required", message="Provider configuration is required before activation")]
                _log(provider_id, "configuring", "await_configuration", "Provider installed; configuration is required", plan_id=plan.plan_id, success=True)
            else:
                record.configuration_status = "configured"
                record.blockers = []
                _transition(record, "available")
            _save_record(record)
            _audit(provider_id, plan=plan, stage=record.install_state, operation="activate", success=True, previous_version=previous)
        except ProviderRegistryError as exc:
            _mark_install_failed(record, provider_id, plan, previous, exc)
            raise
        except Exception as exc:
            failure = ProviderRegistryError("provider_install_failed", "Provider installation failed unexpectedly")
            _mark_install_failed(record, provider_id, plan, previous, failure, unexpected=exc)
            raise failure from exc
        return InstallResult(installation=record, install_actions=_actions(entry, record, _environment(entry)))


def configure_install(provider_id: str, request: ProviderConfigureRequest) -> InstallResult:
    entry = _entry(provider_id)
    lock = _provider_lock(provider_id)
    with lock:
        record = _load_record(entry)
        if record.install_state not in {"installed", "configuring"}:
            raise ProviderRegistryError("provider_configuration_unavailable", f"Provider is {record.install_state}; configuration is unavailable")
        values = request.values or {}
        for field in entry.configuration_schema:
            if field.required and not str(values.get(field.key, "")).strip():
                raise ProviderRegistryError("provider_configuration_missing", f"Required field {field.key} is missing", blockers=[{"code": "configuration_required", "message": field.label}])
        record.api_key_present = any(field.secret and bool(str(values.get(field.key, "")).strip()) for field in entry.configuration_schema)
        record.configuration_status = "configured"
        record.blockers = []
        record.failure = None
        if record.install_state == "installed":
            _transition(record, "configuring")
        _transition(record, "available")
        _save_record(record)
        _log(provider_id, "available", "configure", "Configuration validated without persisting secret values", plan_id=record.current_plan_id, success=True)
        _audit(provider_id, plan=None, stage="available", operation="configure", success=True, previous_version=record.previous_version)
        return InstallResult(installation=record, install_actions=_actions(entry, record, _environment(entry)))


def retry_install(provider_id: str) -> InstallPrepareResponse:
    entry = _entry(provider_id)
    record = _load_record(entry)
    if record.install_state != "failed":
        raise ProviderRegistryError("provider_retry_unavailable", "Retry is only available after a failed installation")
    return prepare_install(provider_id)


def rollback_install(provider_id: str) -> InstallResult:
    entry = _entry(provider_id)
    lock = _provider_lock(provider_id)
    with lock:
        record = _load_record(entry)
        if not record.rollback_available or not record.previous_version:
            raise ProviderRegistryError("provider_rollback_unavailable", "No previous active version is available for rollback")
        previous = record.previous_version
        active_before = record.active_version
        record.active_version = previous
        record.installed_version = previous
        _transition(record, "available")
        record.rollback_available = False
        record.previous_version = None
        record.failure = None
        record.blockers = []
        record.configuration_status = "configured"
        _save_record(record)
        _log(provider_id, "available", "rollback", "Previous active version restored", plan_id=record.current_plan_id, success=True)
        _audit(
            provider_id,
            plan=None,
            stage="available",
            operation="rollback",
            success=True,
            previous_version=active_before,
            target_version=previous,
            rollback=True,
            reason="restore_previous_active_version",
        )
        return InstallResult(installation=record, install_actions=_actions(entry, record, _environment(entry)))


def install_logs(provider_id: str) -> list[ProviderInstallLog]:
    _entry(provider_id)
    path = _state_path("provider_install_logs.jsonl")
    if not path.exists():
        return []
    result: list[ProviderInstallLog] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = ProviderInstallLog.model_validate_json(line)
        except ValueError:
            continue
        if item.provider_id == provider_id:
            result.append(item)
    return result[-200:]


def audit_events(provider_id: str | None = None) -> list[ProviderAuditEvent]:
    path = _state_path("provider_audit_events.jsonl")
    if not path.exists():
        return []
    result: list[ProviderAuditEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = ProviderAuditEvent.model_validate_json(line)
        except ValueError:
            continue
        if provider_id is None or item.provider_id == provider_id:
            result.append(item)
    return result[-500:]
