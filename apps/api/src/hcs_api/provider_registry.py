"""Backend-authoritative provider registry and safe local installation lifecycle.

The registry in this module is deliberately first-party and mock-only.  It is a
contract and lifecycle fixture for the WebUI; it never clones arbitrary URLs or
executes provider supplied shell commands.  A real installer can replace the
executor behind the same structured interface after a separate security review.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import storage


TrustLevel = Literal["first_party", "verified_maintainer"]
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


class ProviderRegistryError(RuntimeError):
    def __init__(self, code: str, message: str, *, blockers: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = blockers or []


class EnvironmentRequirement(BaseModel):
    platforms: list[str] = Field(default_factory=lambda: ["linux", "macos", "windows"])
    architectures: list[str] = Field(default_factory=lambda: ["x86_64", "arm64"])
    python: str = ">=3.11,<3.12"
    min_memory_mb: int = 256
    min_disk_mb: int = 128
    requires_gpu: bool = False
    runtime: str = "isolated virtual environment"
    model_files: list[str] = Field(default_factory=list)
    api_key_required: bool = False


class RegistryConfigField(BaseModel):
    key: str
    label: str
    type: Literal["text", "password", "url"] = "text"
    required: bool = False
    secret: bool = False
    placeholder: str | None = None


class RegistryManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.provider_manifest.v1", alias="schema")
    provider_id: str
    version: str
    source_ref: str
    steps: list[InstallStepKind]


class ProviderRegistryEntry(BaseModel):
    """A fixed, verifiable registry record safe to expose to the client."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str
    capability: Literal["llm", "image", "tts", "ocr", "video"]
    display_name: str
    description: str = ""
    source_url: str
    repository: str
    publisher: str
    license: str
    trust_level: TrustLevel
    version: str
    source_ref: str
    checksum_sha256: str
    manifest_version: str
    manifest_digest: str
    manifest: RegistryManifest
    configuration_schema: list[RegistryConfigField] = Field(default_factory=list)
    requirements: EnvironmentRequirement = Field(default_factory=EnvironmentRequirement)
    supported_operations: list[str] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _validate_manifest(self) -> "ProviderRegistryEntry":
        if self.manifest.provider_id != self.provider_id or self.manifest.version != self.version:
            raise ValueError("manifest identity does not match registry entry")
        digest = _digest(self.manifest.model_dump(mode="json", by_alias=True))
        if digest != self.manifest_digest:
            raise ValueError("manifest digest cannot be verified")
        if self.trust_level not in {"first_party", "verified_maintainer"}:
            raise ValueError("registry source is not trusted")
        host = urlparse(self.source_url).hostname or ""
        if host not in {"github.com", "huggingface.co"}:
            raise ValueError("registry source host is not trusted")
        if self.trust_level == "first_party" and not self.repository.startswith("xueyang-dev/HanClassStudio"):
            raise ValueError("first-party entries must point to the HanClassStudio repository")
        if not self.checksum_sha256:
            raise ValueError("artifact checksum is required")
        if not self.manifest.steps:
            raise ValueError("provider manifest must contain structured steps")
        if any(step == "activate_version" for step in self.manifest.steps) and "cleanup_temp_environment" not in self.manifest.steps:
            raise ValueError("activation plans must include cleanup")
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


class RegistryProviderStatus(BaseModel):
    entry: ProviderRegistryEntry
    installation: ProviderInstallationRecord
    environment: EnvironmentReport
    install_actions: list[InstallAction] = Field(default_factory=list)


class RegistryCatalogResponse(BaseModel):
    providers: list[RegistryProviderStatus]


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


def _artifact_checksum(provider_id: str, version: str, source_ref: str) -> str:
    return hashlib.sha256(f"{provider_id}:{version}:{source_ref}".encode("utf-8")).hexdigest()


def _fixture(
    *, provider_id: str, capability: Literal["llm", "image", "tts", "ocr", "video"], display_name: str,
    description: str, operations: list[str], fields: list[RegistryConfigField], requirements: EnvironmentRequirement,
) -> ProviderRegistryEntry:
    version = "0.1.0"
    source_ref = "v0.1.0"
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
        source_url="https://github.com/xueyang-dev/HanClassStudio/tree/main/providers",
        repository="xueyang-dev/HanClassStudio",
        publisher="HanClassStudio first-party",
        license="MIT",
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


def registry_entries() -> list[ProviderRegistryEntry]:
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


def validate_registry(entries: list[ProviderRegistryEntry] | None = None) -> list[ProviderRegistryEntry]:
    entries = entries or registry_entries()
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
_provider_locks: dict[str, threading.Lock] = {}


def _provider_lock(provider_id: str) -> threading.Lock:
    with _persistence_lock:
        return _provider_locks.setdefault(provider_id, threading.Lock())


def _read_mapping(name: str) -> dict[str, Any]:
    path = _state_path(name)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_mapping(name: str, value: dict[str, Any]) -> None:
    path = _state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _append_jsonl(name: str, payload: BaseModel) -> None:
    path = _state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _persistence_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _record_from_json(provider_id: str, entry: ProviderRegistryEntry, payload: Any) -> ProviderInstallationRecord:
    if isinstance(payload, dict):
        try:
            return ProviderInstallationRecord.model_validate(payload)
        except ValueError:
            pass
    return ProviderInstallationRecord(provider_id=provider_id, capability=entry.capability, available_version=entry.version, updated_at=_iso())


def _environment(entry: ProviderRegistryEntry) -> EnvironmentReport:
    storage.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    platform_id = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(system, system)
    arch = platform.machine().lower() or "unknown"
    blockers: list[EnvironmentBlocker] = []
    if platform_id not in entry.requirements.platforms:
        blockers.append(EnvironmentBlocker(code="platform_unsupported", message=f"Platform {platform_id} is not supported", requirement=", ".join(entry.requirements.platforms)))
    if arch not in {item.lower() for item in entry.requirements.architectures} and arch not in {"amd64", "x86_64", "aarch64", "arm64"}:
        blockers.append(EnvironmentBlocker(code="architecture_unsupported", message=f"Architecture {arch} is not supported", requirement=", ".join(entry.requirements.architectures)))
    try:
        free_disk_mb = int(shutil.disk_usage(storage.CONFIG_DIR).free / (1024 * 1024))
    except OSError:
        free_disk_mb = 0
    if free_disk_mb < entry.requirements.min_disk_mb:
        blockers.append(EnvironmentBlocker(code="disk_space_insufficient", message="Not enough free disk space for this provider", requirement=f">={entry.requirements.min_disk_mb} MB"))
    return EnvironmentReport(
        platform=platform_id,
        architecture=arch,
        python_version=platform.python_version(),
        free_disk_mb=free_disk_mb,
        blockers=blockers,
        checked_at=_iso(),
    )


TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"ready"},
    "ready": {"installing", "failed"},
    "installing": {"installed", "failed"},
    "installed": {"configuring", "available", "installing", "failed"},
    "configuring": {"available", "failed"},
    "available": {"installing", "configuring"},
    "failed": {"ready"},
}


def _transition(record: ProviderInstallationRecord, target: ProviderInstallState) -> None:
    if target not in TRANSITIONS.get(record.install_state, set()):
        raise ProviderRegistryError(
            "provider_invalid_state_transition",
            f"Cannot transition {record.provider_id} from {record.install_state} to {target}",
        )
    record.install_state = target
    record.updated_at = _iso()


def _save_record(record: ProviderInstallationRecord) -> None:
    with _persistence_lock:
        data = _read_mapping("provider_installations.json")
        data[record.provider_id] = record.model_dump(mode="json")
        _write_mapping("provider_installations.json", data)


def _load_record(entry: ProviderRegistryEntry) -> ProviderInstallationRecord:
    record = _record_from_json(entry.provider_id, entry, _read_mapping("provider_installations.json").get(entry.provider_id))
    record.available_version = entry.version
    report = _environment(entry)
    record.environment_blockers = report.blockers
    if record.install_state == "discovered" and report.available:
        _transition(record, "ready")
        _save_record(record)
    return record


def _actions(record: ProviderInstallationRecord, report: EnvironmentReport) -> list[InstallAction]:
    if not report.available:
        return ["view_logs"] if record.install_state in {"failed", "installing"} else []
    state = record.install_state
    if state in {"discovered", "ready"}:
        return ["prepare_install"]
    if state == "failed":
        actions: list[InstallAction] = ["retry_install", "view_logs"]
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
        statuses.append(RegistryProviderStatus(entry=entry, installation=record, environment=report, install_actions=_actions(record, report)))
    return RegistryCatalogResponse(providers=statuses)


def _entry(provider_id: str) -> ProviderRegistryEntry:
    entry = _provider_map().get(provider_id)
    if entry is None:
        raise ProviderRegistryError("provider_not_registered", "Provider is not present in the trusted registry")
    return entry


def _log(provider_id: str, stage: str, operation: str, message: str, *, plan_id: str | None = None, success: bool | None = None, failure_code: str | None = None) -> None:
    sanitized = message.replace("api_key", "credential").replace("API key", "credential")
    _append_jsonl("provider_install_logs.jsonl", ProviderInstallLog(
        timestamp=_iso(), provider_id=provider_id, plan_id=plan_id, stage=stage,
        operation=operation, message=sanitized[:500], success=success, failure_code=failure_code,
    ))


def _audit(provider_id: str, *, plan: InstallationPlan | None, stage: str, operation: str, success: bool, previous_version: str | None = None, failure_code: str | None = None, rollback: bool = False) -> None:
    _append_jsonl("provider_audit_events.jsonl", ProviderAuditEvent(
        event_id=uuid.uuid4().hex, timestamp=_iso(), provider_id=provider_id,
        plan_id=plan.plan_id if plan else None, manifest_digest=plan.manifest_digest if plan else None,
        source=plan.source_ref if plan else None,
        previous_version=previous_version, target_version=plan.version if plan else None,
        stage=stage, operation=operation, success=success, failure_code=failure_code, rollback=rollback,
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


def _build_plan(entry: ProviderRegistryEntry, report: EnvironmentReport) -> InstallationPlan:
    if not report.available:
        raise ProviderRegistryError("provider_environment_blocked", "Provider cannot be installed in this environment", blockers=[item.model_dump(mode="json") for item in report.blockers])
    now = _now()
    steps = [InstallStep(kind=kind, label=kind.replace("_", " ").capitalize()) for kind in entry.manifest.steps]
    return InstallationPlan(
        plan_id=uuid.uuid4().hex,
        provider_id=entry.provider_id,
        version=entry.version,
        source_ref=entry.source_ref,
        checksum_sha256=entry.checksum_sha256,
        manifest_digest=entry.manifest_digest,
        steps=steps,
        environment=report,
        rollback_strategy="retain previous active version until atomic activation succeeds",
        created_at=_iso(now), expires_at=_iso(now + timedelta(minutes=5)),
    )


def prepare_install(provider_id: str) -> InstallPrepareResponse:
    entry = _entry(provider_id)
    lock = _provider_lock(provider_id)
    with lock:
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
        if record.install_state == "failed":
            _transition(record, "ready")
        if record.install_state not in {"ready", "available"}:
            raise ProviderRegistryError("provider_not_ready", f"Provider is {record.install_state}; prepare is unavailable")
        plan = _build_plan(entry, report)
        token = secrets.token_urlsafe(32)
        plans = _read_mapping("provider_install_plans.json")
        plans[plan.plan_id] = {
            "plan": plan.model_dump(mode="json"),
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "provider_id": provider_id,
            "expires_at": plan.expires_at,
        }
        _write_mapping("provider_install_plans.json", plans)
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
        plan = InstallationPlan.model_validate(stored.get("plan"))
        if datetime.fromisoformat(plan.expires_at) <= _now():
            raise ProviderRegistryError("provider_plan_expired", "Installation confirmation has expired")
        expected_token = str(stored.get("token_hash", ""))
        if not secrets.compare_digest(expected_token, hashlib.sha256(request.confirmation_token.encode("utf-8")).hexdigest()):
            raise ProviderRegistryError("provider_confirmation_invalid", "Installation confirmation token is invalid")
        if plan.manifest_digest != entry.manifest_digest or plan.checksum_sha256 != entry.checksum_sha256 or plan.version != entry.version:
            raise ProviderRegistryError("provider_plan_stale", "Installation plan no longer matches the registry manifest")
        record = _load_record(entry)
        if record.install_state == "installing":
            raise ProviderRegistryError("provider_install_in_progress", "An installation is already running")
        if record.install_state not in {"ready", "available"}:
            raise ProviderRegistryError("provider_not_ready", f"Provider is {record.install_state}; confirmation is unavailable")
        previous = record.active_version
        _transition(record, "installing")
        record.current_plan_id = plan.plan_id
        record.failure = None
        record.blockers = []
        _save_record(record)
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
            record.install_state = "failed"
            record.failure = ProviderFailure(code=exc.code, message=exc.message, stage="installing")
            record.blockers = [EnvironmentBlocker(code=exc.code, message=exc.message)]
            # Keep the old active version visible as a usable fact after an upgrade failure.
            record.installed_version = previous
            record.active_version = previous
            record.rollback_available = bool(previous)
            record.updated_at = _iso()
            _save_record(record)
            _log(provider_id, "failed", "install", exc.message, plan_id=plan.plan_id, success=False, failure_code=exc.code)
            _audit(provider_id, plan=plan, stage="failed", operation="install", success=False, previous_version=previous, failure_code=exc.code)
            raise
        return InstallResult(installation=record, install_actions=_actions(record, _environment(entry)))


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
        return InstallResult(installation=record, install_actions=_actions(record, _environment(entry)))


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
        record.active_version = previous
        record.installed_version = previous
        record.install_state = "available"
        record.rollback_available = False
        record.failure = None
        record.blockers = []
        record.configuration_status = "configured"
        record.updated_at = _iso()
        _save_record(record)
        _log(provider_id, "available", "rollback", "Previous active version restored", plan_id=record.current_plan_id, success=True)
        _audit(provider_id, plan=None, stage="available", operation="rollback", success=True, previous_version=record.active_version, rollback=True)
        return InstallResult(installation=record, install_actions=_actions(record, _environment(entry)))


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
