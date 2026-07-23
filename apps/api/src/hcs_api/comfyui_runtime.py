"""Controlled ComfyUI runtime installation, recovery, and process lifecycle."""

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
import signal
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import storage
from .comfyui_archive import (
    ComfyUIArchiveError,
    ComfyUIRuntimeManifest,
    custom_node_tree_is_pristine,
    extract_tar_gz,
    load_runtime_manifest,
    secure_dirfd_extraction_supported,
    sha256_file,
)


RuntimeStatus = Literal[
    "not_installed", "installing", "installed", "starting", "runtime_ready",
    "stopping", "stopped", "crashed", "degraded", "repair_required",
    "incompatible", "failed", "unsupported_modified",
]
RuntimeOperation = Literal["install", "repair", "uninstall"]
RuntimeJournalPhase = Literal[
    "prepared", "downloading", "downloaded", "archive_validated", "tree_extracted",
    "environment_created", "dependencies_installed", "runtime_validated",
    "publish_prepared", "runtime_published", "state_committed", "completed",
    "rolling_back", "rolled_back", "failed", "cancelled",
]
ProcessState = Literal["starting", "running", "stopping", "stopped", "crashed", "identity_mismatch"]
RuntimeAction = Literal[
    "install_runtime", "cancel_install", "start_runtime", "stop_runtime",
    "force_stop_runtime", "check_runtime", "repair_runtime", "uninstall_runtime",
    "view_runtime_logs", "open_runtime_directory",
]

_STATE_FILE = "comfyui_runtime_state.json"
_JOURNAL_FILE = "comfyui_runtime_journal.json"
_PROCESS_FILE = "comfyui_runtime_process.json"
_WORKER_PROCESS_FILE = "comfyui_runtime_worker.json"
_MAX_DOWNLOAD_SECONDS = 10 * 60
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 30
_LOG_MAX_BYTES = 1024 * 1024
_LOG_BACKUPS = 2
_CONFIG_LOCK = threading.RLock()
_MUTATION_LOCK = threading.RLock()
_PROCESS_LOCK = threading.RLock()
_CONFIRMATION_LOCK = threading.RLock()
_PROCESS_HANDLES: dict[int, subprocess.Popen[bytes]] = {}
_WORKER_HANDLES: dict[int, subprocess.Popen[str]] = {}
_LOG_THREADS: dict[int, threading.Thread] = {}
_DESTRUCTIVE_CONFIRMATIONS: dict[str, "RuntimeDestructiveConfirmationRecord"] = {}
_CONFIRMATION_TTL_SECONDS = 5 * 60
PUBLIC_ERROR_CODES = frozenset({
    "runtime_manifest_invalid", "unsupported_platform", "hardware_incompatible",
    "insufficient_disk", "download_failed", "download_cancelled", "checksum_mismatch",
    "unsafe_archive", "archive_too_large", "archive_too_many_files",
    "archive_path_escape", "archive_link_rejected", "extraction_failed",
    "python_environment_failed", "dependency_install_failed", "runtime_validation_failed",
    "port_conflict", "runtime_start_failed", "runtime_start_timeout",
    "runtime_identity_mismatch", "runtime_crashed", "runtime_stop_failed",
    "runtime_health_failed", "runtime_modified", "repair_failed", "uninstall_failed",
    "confirmation_invalid", "confirmation_expired", "confirmation_stale",
    "task_conflict", "cancelled", "internal_error",
})


class ComfyUIRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeDirectoryIdentity(_StrictModel):
    device: int = Field(ge=0)
    inode: int = Field(gt=0)


class LockedWheel(_StrictModel):
    name: str
    version: str
    filename: str
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("filename")
    @classmethod
    def _wheel_filename(cls, value: str) -> str:
        if (
            not value.endswith(".whl")
            or "/" in value
            or "\\" in value
            or value in {".", ".."}
        ):
            raise ValueError("dependency artifact must be one wheel filename")
        return value


class WheelArtifactLock(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_wheel_artifacts.v1"] = Field(alias="schema")
    operating_system: Literal["macos"]
    architecture: Literal["arm64"]
    python_version: str
    wheels: list[LockedWheel]


class VerifiedPythonToolchain(_StrictModel):
    uv: Path
    python: Path
    wheelhouse: Path
    identity_sha256: str


class RuntimeInstallationRecord(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_installation.v2"] = Field(
        default="hanclassstudio.comfyui_runtime_installation.v2", alias="schema"
    )
    runtime_id: Literal["comfyui"] = "comfyui"
    version: str
    source_commit: str
    manifest_sha256: str
    dependency_lock_sha256: str
    environment_fingerprint: str
    source_tree_sha256: str
    python_executable_sha256: str
    environment_manager_version: str
    toolchain_identity_sha256: str
    uv_artifact_sha256: str
    python_runtime_sha256: str
    wheelhouse_sha256: str
    wheel_artifact_lock_sha256: str
    platform_adapter: str
    managed_root_identity: RuntimeDirectoryIdentity
    parent_directory_identity: RuntimeDirectoryIdentity
    version_directory_identity: RuntimeDirectoryIdentity
    managed_path_identities: dict[str, RuntimeDirectoryIdentity] = Field(default_factory=dict)
    installed_at: str

    @field_validator("managed_path_identities")
    @classmethod
    def _managed_paths(cls, value: dict[str, RuntimeDirectoryIdentity]) -> dict[str, RuntimeDirectoryIdentity]:
        if any(name not in {"python", "uv-cache", "home"} for name in value):
            raise ValueError("installation record contains an unmanaged cleanup path")
        return value


class RuntimeStateRecord(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_state.v1"] = Field(
        default="hanclassstudio.comfyui_runtime_state.v1", alias="schema"
    )
    installed: bool = False
    version: str | None = None
    status: RuntimeStatus = "not_installed"
    platform_adapter: str | None = None
    manifest_sha256: str | None = None
    environment_fingerprint: str | None = None
    installed_at: str | None = None
    checked_at: str | None = None
    error: dict[str, Any] | None = None


class RuntimeInstallJournal(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_journal.v2"] = Field(
        default="hanclassstudio.comfyui_runtime_journal.v2", alias="schema"
    )
    transaction_id: str
    task_id: str
    operation: RuntimeOperation
    runtime_id: Literal["comfyui"] = "comfyui"
    runtime_version: str
    manifest_sha256: str
    platform_adapter: str
    phase: RuntimeJournalPhase = "prepared"
    staging_relative_path: str
    final_relative_path: str
    backup_relative_path: str | None = None
    archive_relative_path: str
    expected_archive_sha256: str
    managed_root_identity: RuntimeDirectoryIdentity
    staging_directory_identity: RuntimeDirectoryIdentity | None = None
    published_paths: list[str] = Field(default_factory=list)
    process_state: str | None = None
    created_at: str
    updated_at: str
    error_code: str | None = None
    recovery_strategy: Literal["cleanup_or_restore_then_retry"] = "cleanup_or_restore_then_retry"

    @field_validator(
        "staging_relative_path", "final_relative_path", "backup_relative_path", "archive_relative_path"
    )
    @classmethod
    def _managed_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        path = PurePosixPath(value)
        if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("journal path must remain relative to the managed runtime root")
        return path.as_posix()


class RuntimeProcessOwnership(_StrictModel):
    pid: int = Field(gt=0)
    process_start_token: str
    process_group_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    executable_sha256: str
    runtime_version: str
    runtime_root_relative_path: str
    cwd_relative_path: str
    installation_identity_sha256: str
    port: int = Field(ge=1024, le=65535)
    nonce: str
    expected_argv_sha256: str
    runtime_argv_sha256: str
    supervisor_script_sha256: str
    source_tree_sha256: str
    listener_pid: int | None = Field(default=None, gt=0)
    listener_start_token: str | None = None
    started_at: str

    @field_validator(
        "executable_sha256",
        "expected_argv_sha256",
        "runtime_argv_sha256",
        "supervisor_script_sha256",
        "source_tree_sha256",
        "installation_identity_sha256",
    )
    @classmethod
    def _sha256_identity(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("process identities must be lowercase SHA-256")
        return value

    @field_validator("nonce")
    @classmethod
    def _nonce_identity(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError("process nonce must be 128-bit lowercase hex")
        return value

    @field_validator("runtime_root_relative_path")
    @classmethod
    def _runtime_root_identity(cls, value: str) -> str:
        path = PurePosixPath(value)
        if len(path.parts) != 2 or path.parts[0] != "versions" or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("process Runtime root identity is invalid")
        return value

    @field_validator("cwd_relative_path")
    @classmethod
    def _cwd_identity(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            len(path.parts) != 3
            or path.parts[0] != "versions"
            or path.parts[2] != "source"
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("process working-directory identity is invalid")
        return value


class ComfyUIRuntimeProcess(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_process.v1"] = Field(
        default="hanclassstudio.comfyui_runtime_process.v1", alias="schema"
    )
    state: ProcessState
    ownership: RuntimeProcessOwnership
    updated_at: str
    exit_code: int | None = None
    error: dict[str, str] | None = None


class RuntimeWorkerOwnership(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_worker.v1"] = Field(
        default="hanclassstudio.comfyui_runtime_worker.v1", alias="schema"
    )
    pid: int = Field(gt=0)
    process_start_token: str
    process_group_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    argv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    argv: list[str]
    cwd_relative_path: str
    managed_root_identity: RuntimeDirectoryIdentity
    started_at: str

    @field_validator("argv")
    @classmethod
    def _worker_argv(cls, value: list[str]) -> list[str]:
        if not value or len(value) > 256 or any(not item or len(item) > 4096 for item in value):
            raise ValueError("worker argv is invalid")
        return value

    @field_validator("cwd_relative_path")
    @classmethod
    def _worker_cwd(cls, value: str) -> str:
        if value == ".":
            return value
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("worker working directory must remain managed")
        return path.as_posix()


class RuntimeHealthSnapshot(_StrictModel):
    healthy: bool
    checked_at: str
    status: RuntimeStatus
    version: str | None = None
    port: int | None = None
    core_api_available: bool = False
    custom_nodes_pristine: bool = False
    identity_verified: bool = False
    error: dict[str, str] | None = None


class RuntimeOperationSummary(_StrictModel):
    operation: Literal["repair", "uninstall"]
    runtime_id: Literal["comfyui"] = "comfyui"
    version: str
    installation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    tree_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    modified: bool
    replaces_runtime_files: bool
    preserves_models: Literal[True] = True
    preserves_runtime_data: Literal[True] = True
    preserves_logs: Literal[True] = True


class RuntimeOperationConfirmation(_StrictModel):
    summary: RuntimeOperationSummary
    confirmation_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: str


class RuntimeDestructiveConfirmationRecord(_StrictModel):
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: RuntimeOperationSummary
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    expires_at_epoch: float


class RuntimeSnapshot(_StrictModel):
    runtime_id: Literal["comfyui"] = "comfyui"
    package_id: Literal["hcs.comfyui-runtime"] = "hcs.comfyui-runtime"
    name: str = "ComfyUI 本地运行环境"
    status: RuntimeStatus
    installed: bool
    runtime_ready: bool
    generation_ready: Literal[False] = False
    version: str
    source_commit: str
    platform_adapter: str
    platform_support: Literal["experimental", "contract_only", "unavailable"]
    compatible: bool
    available_actions: list[RuntimeAction]
    actual_port: int | None = None
    estimated_download_bytes: int
    no_model_message: str = "运行环境可用，但尚未安装图片模型。"
    modified: bool = False
    last_health: RuntimeHealthSnapshot | None = None
    technical_error: dict[str, Any] | None = None


ProgressCallback = Callable[[str, int, str, int | None, int | None], None]
CancellationCheck = Callable[[], None]


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_manifest() -> ComfyUIRuntimeManifest:
    try:
        return load_runtime_manifest()
    except ComfyUIArchiveError as exc:
        raise ComfyUIRuntimeError("runtime_manifest_invalid", "ComfyUI Runtime manifest or dependency lock is invalid") from exc


def _public_archive_error_code(code: str) -> str:
    if code == "checksum_mismatch":
        return code
    if code in {"archive_entry_limit"}:
        return "archive_too_many_files"
    if code in {"archive_file_limit", "archive_expanded_size_limit", "archive_compression_ratio", "archive_size_mismatch"}:
        return "archive_too_large"
    if code in {"unsafe_archive_path", "archive_root_mismatch", "archive_path_collision"}:
        return "archive_path_escape"
    if code in {"archive_special_file"}:
        return "archive_link_rejected"
    if code in {"archive_extraction_failed", "archive_tree_mismatch", "archive_size_changed", "staging_conflict"}:
        return "extraction_failed"
    if code in {"critical_file_mismatch", "custom_node_baseline_mismatch"}:
        return "runtime_validation_failed"
    return "unsafe_archive"


def _managed_root() -> Path:
    return storage.RUNTIME_DIR / "providers" / "hcs.comfyui-runtime"


def _version_root(manifest: ComfyUIRuntimeManifest) -> Path:
    return _managed_root() / "versions" / manifest.version


def _source_root(manifest: ComfyUIRuntimeManifest) -> Path:
    return _version_root(manifest) / "source"


def _environment_root(manifest: ComfyUIRuntimeManifest) -> Path:
    return _version_root(manifest) / "environment"


def _environment_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _models_root() -> Path:
    return storage.RUNTIME_DIR / "provider-models" / "comfyui"


def _runtime_data_root() -> Path:
    return storage.RUNTIME_DIR / "provider-data" / "comfyui"


def _logs_root() -> Path:
    return storage.RUNTIME_DIR / "logs" / "comfyui"


def _config_path(name: str) -> Path:
    return storage.CONFIG_DIR / name


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _directory_identity(info: os.stat_result) -> RuntimeDirectoryIdentity:
    return RuntimeDirectoryIdentity(device=info.st_dev, inode=info.st_ino)


def _same_directory(actual: RuntimeDirectoryIdentity, expected: RuntimeDirectoryIdentity) -> bool:
    return actual.device == expected.device and actual.inode == expected.inode


def _open_child_directory(parent_fd: int, name: str, *, create: bool = False) -> int:
    if not name or name in {".", ".."} or "/" in name:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime directory name is invalid")
    try:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime path is not a real directory")
        fd = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
        after = os.fstat(fd)
        if _directory_identity(before) != _directory_identity(after):
            os.close(fd)
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime directory identity changed")
        return fd
    except ComfyUIRuntimeError:
        raise
    except OSError as exc:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime directory cannot be opened safely") from exc


def _open_runtime_directory(*, create: bool = False) -> int:
    path = storage.RUNTIME_DIR
    try:
        parent_info = path.parent.lstat()
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Runtime parent is not a real directory")
        parent_fd = os.open(path.parent, _DIRECTORY_OPEN_FLAGS)
    except ComfyUIRuntimeError:
        raise
    except OSError as exc:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Runtime parent cannot be opened safely") from exc
    try:
        if _directory_identity(os.fstat(parent_fd)) != _directory_identity(parent_info):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Runtime parent identity changed")
        return _open_child_directory(parent_fd, path.name, create=create)
    finally:
        os.close(parent_fd)


@contextmanager
def _open_managed_root(
    *,
    create: bool = False,
    expected: RuntimeDirectoryIdentity | None = None,
) -> Iterator[tuple[int, RuntimeDirectoryIdentity]]:
    if not secure_dirfd_extraction_supported() or not shutil.rmtree.avoids_symlink_attacks:
        raise ComfyUIRuntimeError("unsupported_platform", "Safe managed-directory operations are unavailable")
    runtime_fd = _open_runtime_directory(create=create)
    try:
        providers_fd = _open_child_directory(runtime_fd, "providers", create=create)
    finally:
        os.close(runtime_fd)
    try:
        managed_fd = _open_child_directory(providers_fd, "hcs.comfyui-runtime", create=create)
    finally:
        os.close(providers_fd)
    identity = _directory_identity(os.fstat(managed_fd))
    try:
        if expected is not None and not _same_directory(identity, expected):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime root identity changed")
        yield managed_fd, identity
    finally:
        os.close(managed_fd)


def _managed_relative_parts(path: Path) -> tuple[str, ...]:
    try:
        relative = path.relative_to(_managed_root())
    except ValueError as exc:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime path escaped its root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime path is not a removable child")
    return relative.parts


@contextmanager
def _open_managed_directory(
    path: Path,
    *,
    expected_root: RuntimeDirectoryIdentity | None = None,
) -> Iterator[tuple[int, RuntimeDirectoryIdentity, RuntimeDirectoryIdentity]]:
    parts = _managed_relative_parts(path)
    with _open_managed_root(expected=expected_root) as (root_fd, root_identity):
        current = os.dup(root_fd)
        try:
            for part in parts:
                child = _open_child_directory(current, part)
                os.close(current)
                current = child
            yield current, root_identity, _directory_identity(os.fstat(current))
        finally:
            os.close(current)


def _managed_directory_identity(path: Path, *, expected_root: RuntimeDirectoryIdentity | None = None) -> RuntimeDirectoryIdentity:
    with _open_managed_directory(path, expected_root=expected_root) as (_fd, _root, identity):
        return identity


def _current_managed_root_identity() -> RuntimeDirectoryIdentity:
    with _open_managed_root() as (_fd, identity):
        return identity


def _optional_managed_directory_identity(
    path: Path,
    *,
    root_identity: RuntimeDirectoryIdentity,
) -> RuntimeDirectoryIdentity | None:
    parts = _managed_relative_parts(path)
    with _open_managed_root(expected=root_identity) as (root_fd, _root):
        parent_fd = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                try:
                    info = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return None
                if not stat.S_ISDIR(info.st_mode):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Managed Runtime path is not a real directory"
                    )
                child = _open_child_directory(parent_fd, part)
                os.close(parent_fd)
                parent_fd = child
            try:
                info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            if not stat.S_ISDIR(info.st_mode):
                raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime path is not a real directory")
            return _directory_identity(info)
        finally:
            os.close(parent_fd)


def _ensure_managed_directory(
    path: Path,
    *,
    root_identity: RuntimeDirectoryIdentity,
) -> RuntimeDirectoryIdentity:
    parts = _managed_relative_parts(path)
    with _open_managed_root(expected=root_identity) as (root_fd, _root):
        current = os.dup(root_fd)
        try:
            for part in parts:
                child = _open_child_directory(current, part, create=True)
                os.close(current)
                current = child
            return _directory_identity(os.fstat(current))
        finally:
            os.close(current)


@contextmanager
def _open_managed_parent(
    path: Path,
    *,
    root_identity: RuntimeDirectoryIdentity,
) -> Iterator[tuple[int, str]]:
    parts = _managed_relative_parts(path)
    with _open_managed_root(expected=root_identity) as (root_fd, _root):
        current = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                child = _open_child_directory(current, part)
                os.close(current)
                current = child
            yield current, parts[-1]
        finally:
            os.close(current)


def _secure_replace_managed(
    source: Path,
    destination: Path,
    *,
    root_identity: RuntimeDirectoryIdentity,
) -> None:
    with _open_managed_parent(source, root_identity=root_identity) as (source_fd, source_name):
        with _open_managed_parent(destination, root_identity=root_identity) as (destination_fd, destination_name):
            try:
                source_info = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
                if not stat.S_ISDIR(source_info.st_mode):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Managed Runtime publish source is not a real directory"
                    )
                try:
                    destination_info = os.stat(destination_name, dir_fd=destination_fd, follow_symlinks=False)
                except FileNotFoundError:
                    destination_info = None
                if destination_info is not None and not stat.S_ISDIR(destination_info.st_mode):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Managed Runtime publish destination is not a real directory"
                    )
                os.rename(
                    source_name,
                    destination_name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=destination_fd,
                )
            except ComfyUIRuntimeError:
                raise
            except OSError as exc:
                raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime publish failed safely") from exc


def _assert_safe_removal_tree(directory_fd: int) -> None:
    try:
        for _root, directory_names, file_names, current_fd in os.fwalk(
            ".", topdown=True, follow_symlinks=False, dir_fd=directory_fd
        ):
            for name in [*directory_names, *file_names]:
                info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch",
                        "Managed Runtime cleanup refused a link or special file",
                    )
    except ComfyUIRuntimeError:
        raise
    except OSError as exc:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime cleanup tree changed") from exc


def _secure_remove_managed_directory(
    path: Path,
    *,
    root_identity: RuntimeDirectoryIdentity,
    target_identity: RuntimeDirectoryIdentity,
) -> bool:
    parts = _managed_relative_parts(path)
    with _open_managed_root(expected=root_identity) as (root_fd, _root):
        parent_fd = os.dup(root_fd)
        try:
            for part in parts[:-1]:
                child = _open_child_directory(parent_fd, part)
                os.close(parent_fd)
                parent_fd = child
            name = parts[-1]
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISDIR(current.st_mode) or not _same_directory(
                _directory_identity(current), target_identity
            ):
                raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime cleanup target identity changed")
            target_fd = _open_child_directory(parent_fd, name)
            try:
                if not _same_directory(_directory_identity(os.fstat(target_fd)), target_identity):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Managed Runtime cleanup target identity changed"
                    )
                _assert_safe_removal_tree(target_fd)
                quarantine = f".hcs-delete-{uuid.uuid4().hex}"
                os.rename(name, quarantine, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                moved = os.stat(quarantine, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISDIR(moved.st_mode) or not _same_directory(
                    _directory_identity(moved), target_identity
                ):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Managed Runtime cleanup rename identity changed"
                    )
            finally:
                os.close(target_fd)
            shutil.rmtree(quarantine, dir_fd=parent_fd)
            return True
        except ComfyUIRuntimeError:
            raise
        except OSError as exc:
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime cleanup failed safely") from exc
        finally:
            os.close(parent_fd)


def _manifest_sha256() -> str:
    return sha256_file(storage.ROOT_DIR / "providers/comfyui/runtime-manifest.v1.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    os.replace(temporary, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass


def _read_state() -> RuntimeStateRecord:
    raw = _read_json(_config_path(_STATE_FILE))
    try:
        return RuntimeStateRecord.model_validate(raw) if raw else RuntimeStateRecord()
    except ValueError:
        return RuntimeStateRecord(status="repair_required", error={"code": "runtime_state_invalid"})


def _write_state(state: RuntimeStateRecord) -> None:
    with _CONFIG_LOCK:
        _atomic_json(_config_path(_STATE_FILE), state.model_dump(mode="json", by_alias=True))


def _journals() -> dict[str, Any]:
    return _read_json(_config_path(_JOURNAL_FILE))


def _save_journal(journal: RuntimeInstallJournal) -> None:
    with _CONFIG_LOCK:
        current = _journals()
        current[journal.transaction_id] = journal.model_dump(mode="json", by_alias=True)
        _atomic_json(_config_path(_JOURNAL_FILE), current)


def _update_journal(
    journal: RuntimeInstallJournal,
    phase: RuntimeJournalPhase,
    *,
    error_code: str | None = None,
    published_paths: list[str] | None = None,
) -> None:
    journal.phase = phase
    journal.updated_at = _iso()
    journal.error_code = error_code
    if published_paths is not None:
        journal.published_paths = published_paths
    _save_journal(journal)


def _resolve_journal_path(relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ComfyUIRuntimeError("runtime_journal_invalid", "Runtime journal path escaped its managed root")
    return _managed_root().joinpath(*path.parts)


def platform_adapter(manifest: ComfyUIRuntimeManifest) -> tuple[str, str, bool]:
    system = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(
        platform.system().lower(), "unknown"
    )
    architecture = {"aarch64": "arm64", "amd64": "x86_64"}.get(
        platform.machine().lower(), platform.machine().lower()
    )
    for item in manifest.platforms:
        if item.operating_system == system and item.architecture == architecture:
            return item.adapter, item.support, item.install_enabled and secure_dirfd_extraction_supported()
    return "unsupported", "unavailable", False


def _redact(value: str) -> str:
    redacted = value.replace(str(storage.RUNTIME_DIR), "<runtime>").replace(str(Path.home()), "<user>")
    redacted = re.sub(
        r"(?i)(api[_-]?key|token|password|secret|authorization)(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        redacted,
    )
    return redacted[:16_384]


def _rotate_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size < _LOG_MAX_BYTES:
        return
    oldest = path.with_suffix(path.suffix + f".{_LOG_BACKUPS}")
    oldest.unlink(missing_ok=True)
    for index in range(_LOG_BACKUPS - 1, 0, -1):
        source = path.with_suffix(path.suffix + f".{index}")
        if source.exists():
            os.replace(source, path.with_suffix(path.suffix + f".{index + 1}"))
    os.replace(path, path.with_suffix(path.suffix + ".1"))


def _append_log(kind: Literal["install", "runtime"], message: str) -> None:
    path = _logs_root() / f"{kind}.log"
    with _CONFIG_LOCK:
        _rotate_log(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{_iso()} {_redact(message).rstrip()}\n")


def log_summary(kind: Literal["install", "runtime"], *, max_lines: int = 120) -> list[str]:
    path = _logs_root() / f"{kind}.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [_redact(line) for line in lines[-max(1, min(max_lines, 500)):]]


def _validate_public_host(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ComfyUIRuntimeError("download_failed", "The official ComfyUI source could not be reached") from exc
    if not addresses:
        raise ComfyUIRuntimeError("download_failed", "The official ComfyUI source could not be reached")
    for address in addresses:
        try:
            resolved = ipaddress.ip_address(address[4][0])
        except ValueError as exc:
            raise ComfyUIRuntimeError("download_source_untrusted", "ComfyUI source resolved unexpectedly") from exc
        if not resolved.is_global:
            raise ComfyUIRuntimeError("download_source_untrusted", "ComfyUI source resolved to a non-public address")


def download_official_archive(
    destination: Path,
    manifest: ComfyUIRuntimeManifest,
    progress: Callable[[int, int], None],
    cancel: CancellationCheck,
) -> None:
    parsed = urlparse(manifest.source.archive_url)
    expected_path = f"/Comfy-Org/ComfyUI/tar.gz/{manifest.source_commit}"
    if (
        parsed.scheme != "https" or parsed.hostname != "codeload.github.com"
        or parsed.path != expected_path or parsed.username or parsed.password or parsed.port
        or parsed.query or parsed.fragment
    ):
        raise ComfyUIRuntimeError("download_source_untrusted", "ComfyUI source URL is not an approved commit-pinned origin")
    _validate_public_host(parsed.hostname)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = time.monotonic()
    connection = http.client.HTTPSConnection(
        parsed.hostname,
        443,
        timeout=_CONNECT_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("GET", parsed.path, headers={"User-Agent": "HanClassStudio-ComfyUIRuntime/1"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ComfyUIRuntimeError("download_source_untrusted", "ComfyUI archive download refused an unexpected redirect")
        if response.status != 200:
            raise ComfyUIRuntimeError("download_failed", "The official ComfyUI archive could not be downloaded")
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise ComfyUIRuntimeError("download_failed", "ComfyUI archive response metadata was invalid") from exc
            if declared_size != manifest.source.archive_size:
                raise ComfyUIRuntimeError("archive_size_mismatch", "ComfyUI archive response size differs from the manifest")
        if connection.sock is not None:
            connection.sock.settimeout(_READ_TIMEOUT_SECONDS)
        digest = hashlib.sha256()
        received = 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as output:
                while True:
                    cancel()
                    if time.monotonic() - started > _MAX_DOWNLOAD_SECONDS:
                        raise ComfyUIRuntimeError("download_failed", "ComfyUI archive download timed out")
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > manifest.archive_policy.max_compressed_bytes:
                        raise ComfyUIRuntimeError("archive_too_large", "ComfyUI archive exceeded its size limit")
                    digest.update(chunk)
                    output.write(chunk)
                    progress(received, manifest.source.archive_size)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(fd)
        if received != manifest.source.archive_size:
            raise ComfyUIRuntimeError("archive_size_mismatch", "Downloaded ComfyUI archive size differs from the manifest")
        if digest.hexdigest() != manifest.source.archive_sha256:
            raise ComfyUIRuntimeError("checksum_mismatch", "Downloaded ComfyUI archive SHA-256 differs from the manifest")
    except ComfyUIRuntimeError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        destination.unlink(missing_ok=True)
        raise ComfyUIRuntimeError("download_failed", "The official ComfyUI archive download failed") from exc
    finally:
        connection.close()


ARCHIVE_DOWNLOADER = download_official_archive


def _controlled_environment() -> dict[str, str]:
    allowed = ("TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    environment.update({
        "HOME": str(_managed_root() / "home"),
        "PATH": os.defpath,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_NO_CONFIG": "1",
        "UV_PYTHON_PREFERENCE": "only-managed",
        "UV_PYTHON_DOWNLOADS": "automatic",
        "UV_CACHE_DIR": str(_managed_root() / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(_managed_root() / "python"),
    })
    return environment


def _terminate_controlled_process(process: subprocess.Popen[str], *, force: bool = False) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        else:
            process.kill() if force else process.terminate()
        process.wait(timeout=5)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        if not force:
            _terminate_controlled_process(process, force=True)


def _run_controlled(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    error_code: str,
    cancel: CancellationCheck,
    environment: dict[str, str] | None = None,
    persist_ownership: bool = False,
) -> subprocess.CompletedProcess[str]:
    cancel()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment or _controlled_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        raise ComfyUIRuntimeError(error_code, "Controlled ComfyUI environment command failed") from exc
    if persist_ownership:
        token = None
        group_identity = None
        identity_deadline = time.monotonic() + 3
        while (
            (token is None or group_identity is None)
            and process.poll() is None
            and time.monotonic() < identity_deadline
        ):
            token = _process_start_token(process.pid)
            group_identity = _process_group_identity(process.pid)
            if token is None or group_identity is None:
                time.sleep(0.02)
        try:
            relative_cwd = cwd.relative_to(_managed_root()).as_posix() or "."
            executable = Path(argv[0])
            root_identity = _current_managed_root_identity()
            if (
                token is None
                or group_identity != (process.pid, process.pid)
                or not executable.is_absolute()
                or not executable.is_file()
            ):
                raise ComfyUIRuntimeError(
                    "runtime_identity_mismatch", "Controlled Runtime worker identity could not be recorded"
                )
            _write_worker_process(RuntimeWorkerOwnership(
                pid=process.pid,
                process_start_token=token,
                process_group_id=group_identity[0],
                session_id=group_identity[1],
                executable_sha256=sha256_file(executable),
                argv_sha256=_argv_digest(argv),
                argv=argv,
                cwd_relative_path=relative_cwd,
                managed_root_identity=root_identity,
                started_at=_iso(),
            ))
            _WORKER_HANDLES[process.pid] = process
        except (OSError, ValueError, ComfyUIRuntimeError):
            _terminate_controlled_process(process, force=True)
            _write_worker_process(None)
            raise ComfyUIRuntimeError(
                "runtime_identity_mismatch", "Controlled Runtime worker identity could not be recorded"
            )
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                cancel()
                if time.monotonic() >= deadline:
                    _terminate_controlled_process(process, force=True)
                    raise ComfyUIRuntimeError(error_code, "Controlled ComfyUI environment command timed out")
    except BaseException:
        _terminate_controlled_process(process)
        raise
    finally:
        if persist_ownership:
            _WORKER_HANDLES.pop(process.pid, None)
            _write_worker_process(None)
    cancel()
    if stdout:
        _append_log("install", stdout[-16_384:])
    if stderr:
        _append_log("install", stderr[-16_384:])
    if process.returncode != 0:
        raise ComfyUIRuntimeError(error_code, "Controlled ComfyUI environment command failed")
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _expected_dependencies(lock_path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)", line)
        if match:
            expected[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    if not expected:
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "ComfyUI dependency lock contains no packages")
    return expected


_PACKAGE_QUERY = (
    "import importlib.metadata,json,platform;"
    "print(json.dumps({'python':platform.python_version(),'packages':sorted((d.metadata['Name'].lower().replace('_','-').replace('.','-'),d.version) "
    "for d in importlib.metadata.distributions())},separators=(',',':')))"
)


def _installed_environment(environment: Path) -> tuple[str, dict[str, str]]:
    python = _environment_python(environment)
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", _PACKAGE_QUERY],
            cwd=environment,
            env=_controlled_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        values = json.loads(result.stdout) if result.returncode == 0 else None
        if not isinstance(values, dict) or not isinstance(values.get("python"), str) or not isinstance(values.get("packages"), list):
            raise ValueError
        installed = {
            re.sub(r"[-_.]+", "-", str(name)).lower(): str(version)
            for name, version in values["packages"]
        }
        return values["python"], installed
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError, TypeError) as exc:
        raise ComfyUIRuntimeError("runtime_validation_failed", "ComfyUI isolated environment cannot be inspected") from exc


def environment_fingerprint(environment: Path, manifest: ComfyUIRuntimeManifest) -> str:
    expected = _expected_dependencies(storage.ROOT_DIR / manifest.python.lock_file)
    python_version, installed = _installed_environment(environment)
    if python_version != manifest.python.version or installed != expected:
        raise ComfyUIRuntimeError("dependency_install_failed", "ComfyUI isolated dependencies differ from the fixed lock")
    identity = {
        "python": python_version,
        "lock_sha256": manifest.python.lock_sha256,
        "packages": sorted(installed.items()),
    }
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _project_artifact(relative_name: str, *, directory: bool) -> Path:
    target = storage.ROOT_DIR.joinpath(*PurePosixPath(relative_name).parts)
    try:
        current = storage.ROOT_DIR
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise OSError
        for part in PurePosixPath(relative_name).parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise OSError
        final = target.lstat()
        if directory and not stat.S_ISDIR(final.st_mode):
            raise OSError
        if not directory and not stat.S_ISREG(final.st_mode):
            raise OSError
    except OSError as exc:
        raise ComfyUIRuntimeError(
            "python_environment_failed", "A fixed Python toolchain artifact is unavailable"
        ) from exc
    return target


def _regular_tree_identity(root: Path) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    try:
        for current_root, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
            directory_names.sort()
            file_names.sort()
            current = Path(current_root)
            for name in directory_names:
                target = current / name
                info = target.lstat()
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise OSError
                relative = target.relative_to(root).as_posix().encode()
                digest.update(b"D\0" + relative + b"\0")
            for name in file_names:
                target = current / name
                info = target.lstat()
                if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise OSError
                relative = target.relative_to(root).as_posix().encode()
                total += info.st_size
                digest.update(b"F\0" + relative + b"\0" + str(info.st_size).encode() + b"\0")
                with target.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        digest.update(chunk)
                digest.update(b"\0")
    except OSError as exc:
        raise ComfyUIRuntimeError(
            "python_environment_failed", "A fixed Python toolchain tree cannot be verified"
        ) from exc
    return total, digest.hexdigest()


def _read_wheel_artifact_lock(path: Path) -> WheelArtifactLock:
    try:
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise OSError
        return WheelArtifactLock.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ComfyUIRuntimeError(
            "dependency_lock_mismatch", "The fixed wheel artifact lock is invalid"
        ) from exc


def verify_python_toolchain(manifest: ComfyUIRuntimeManifest) -> VerifiedPythonToolchain:
    python_contract = manifest.python
    if python_contract.toolchain_status != "ready":
        raise ComfyUIRuntimeError(
            "unsupported_platform", "A complete reviewed wheel-only Python toolchain is unavailable"
        )
    uv_artifact = python_contract.uv_artifact
    python_artifact = python_contract.python_runtime
    wheelhouse_artifact = python_contract.wheelhouse
    if uv_artifact is None or python_artifact is None or wheelhouse_artifact is None:
        raise ComfyUIRuntimeError("python_environment_failed", "The fixed Python toolchain is incomplete")

    uv = _project_artifact(uv_artifact.relative_path, directory=False)
    if uv.stat().st_size != uv_artifact.size or sha256_file(uv) != uv_artifact.sha256:
        raise ComfyUIRuntimeError("python_environment_failed", "The fixed uv identity does not match")
    if _environment_manager_version(str(uv)) != python_contract.environment_manager_version:
        raise ComfyUIRuntimeError("python_environment_failed", "The fixed uv version does not match")

    python_root = _project_artifact(python_artifact.relative_path, directory=True)
    python_size, python_identity = _regular_tree_identity(python_root)
    if python_size != python_artifact.size or python_identity != python_artifact.tree_sha256:
        raise ComfyUIRuntimeError("python_environment_failed", "The fixed Python Runtime identity does not match")
    python = python_root.joinpath(*PurePosixPath(python_artifact.executable_relative_path).parts)
    try:
        if not stat.S_ISREG(python.lstat().st_mode):
            raise OSError
    except OSError as exc:
        raise ComfyUIRuntimeError("python_environment_failed", "The fixed Python executable is invalid") from exc

    wheelhouse = _project_artifact(wheelhouse_artifact.relative_path, directory=True)
    wheelhouse_size, wheelhouse_identity = _regular_tree_identity(wheelhouse)
    if wheelhouse_size != wheelhouse_artifact.size or wheelhouse_identity != wheelhouse_artifact.sha256:
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "The fixed wheelhouse identity does not match")
    artifact_lock_path = _project_artifact(wheelhouse_artifact.artifact_lock_file, directory=False)
    artifact_lock = _read_wheel_artifact_lock(artifact_lock_path)
    if (
        sha256_file(artifact_lock_path) != wheelhouse_artifact.artifact_lock_sha256
        or artifact_lock.python_version != python_contract.version
        or (artifact_lock.operating_system, artifact_lock.architecture) != ("macos", "arm64")
    ):
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "The fixed wheel artifact lock does not match")
    expected = _expected_dependencies(storage.ROOT_DIR / python_contract.lock_file)
    locked = {
        re.sub(r"[-_.]+", "-", wheel.name).lower(): wheel.version
        for wheel in artifact_lock.wheels
    }
    if len(locked) != len(artifact_lock.wheels) or locked != expected:
        raise ComfyUIRuntimeError(
            "dependency_lock_mismatch", "The wheel artifact set is not a complete dependency lock"
        )
    expected_filenames = {wheel.filename for wheel in artifact_lock.wheels}
    if len(expected_filenames) != len(artifact_lock.wheels):
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "The wheel artifact lock contains duplicates")
    try:
        actual_filenames = {item.name for item in wheelhouse.iterdir()}
    except OSError as exc:
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "The fixed wheelhouse cannot be inspected") from exc
    if actual_filenames != expected_filenames:
        raise ComfyUIRuntimeError("dependency_lock_mismatch", "The fixed wheelhouse contains an unexpected artifact")
    for wheel in artifact_lock.wheels:
        target = wheelhouse / wheel.filename
        try:
            info = target.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size != wheel.size
                or sha256_file(target) != wheel.sha256
            ):
                raise OSError
        except OSError as exc:
            raise ComfyUIRuntimeError(
                "dependency_lock_mismatch", "A fixed wheel artifact identity does not match"
            ) from exc
    identity = _toolchain_contract_identity(manifest)
    return VerifiedPythonToolchain(
        uv=uv,
        python=python,
        wheelhouse=wheelhouse,
        identity_sha256=identity,
    )


def _toolchain_contract_identity(manifest: ComfyUIRuntimeManifest) -> str:
    return hashlib.sha256(
        json.dumps(manifest.python.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def create_python_environment(
    environment: Path,
    manifest: ComfyUIRuntimeManifest,
    cancel: CancellationCheck,
) -> str:
    toolchain = verify_python_toolchain(manifest)
    uv = str(toolchain.uv)
    manager_environment = _controlled_environment()
    manager_environment.update({
        "PATH": str(toolchain.uv.parent),
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_NO_CONFIG": "1",
    })
    _run_controlled(
        [
            uv, "venv", "--offline", "--relocatable",
            "--python", str(toolchain.python), str(environment),
        ],
        cwd=_managed_root(), timeout=120,
        error_code="python_environment_failed", cancel=cancel, environment=manager_environment,
        persist_ownership=True,
    )
    _run_controlled(
        [
            uv, "pip", "install", "--python", str(_environment_python(environment)),
            "--offline", "--no-index", "--find-links", str(toolchain.wheelhouse),
            "--require-hashes", "--only-binary=:all:", "--no-build-isolation", "--no-deps",
            "-r", str(storage.ROOT_DIR / manifest.python.lock_file),
        ],
        cwd=_managed_root(), timeout=45 * 60,
        error_code="dependency_install_failed", cancel=cancel, environment=manager_environment,
        persist_ownership=True,
    )
    fingerprint = environment_fingerprint(environment, manifest)
    for package, version in sorted(_expected_dependencies(storage.ROOT_DIR / manifest.python.lock_file).items()):
        _append_log("install", f"locked dependency {package}=={version}")
    return fingerprint


ENVIRONMENT_BUILDER = create_python_environment


def _environment_manager_version(executable: str | None = None) -> str:
    if executable is None:
        return "unavailable"
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={"PATH": os.defpath, "UV_NO_CONFIG": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    match = re.fullmatch(r"uv\s+(\d+\.\d+\.\d+)(?:\s+.*)?", result.stdout.strip())
    return match.group(1) if result.returncode == 0 and match else "unavailable"


def _installation_record_path(version_root: Path) -> Path:
    return version_root / "installation.json"


def source_tree_fingerprint(source: Path) -> str:
    digest = hashlib.sha256()
    try:
        for current_root, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
            directory_names.sort()
            file_names.sort()
            current = Path(current_root)
            for name in directory_names:
                target = current / name
                if target.is_symlink() or not target.is_dir():
                    raise ComfyUIRuntimeError("runtime_modified", "ComfyUI source tree contains a link or special directory")
                relative = target.relative_to(source).as_posix().encode("utf-8")
                digest.update(b"D\0" + relative + b"\0")
            for name in file_names:
                target = current / name
                if target.is_symlink() or not target.is_file():
                    raise ComfyUIRuntimeError("runtime_modified", "ComfyUI source tree contains a link or special file")
                relative = target.relative_to(source).as_posix().encode("utf-8")
                digest.update(b"F\0" + relative + b"\0" + str(target.stat().st_size).encode() + b"\0")
                digest.update(bytes.fromhex(sha256_file(target)))
    except OSError as exc:
        raise ComfyUIRuntimeError("runtime_validation_failed", "ComfyUI source tree cannot be verified") from exc
    return digest.hexdigest()


def installed_tree_fingerprint(version_root: Path) -> str:
    digest = hashlib.sha256()
    try:
        for current_root, directory_names, file_names, current_fd in os.fwalk(
            version_root, topdown=True, follow_symlinks=False
        ):
            directory_names.sort()
            file_names.sort()
            current = Path(current_root)
            for name in [*directory_names, *file_names]:
                info = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                relative = (current / name).relative_to(version_root).as_posix().encode()
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(name, dir_fd=current_fd).encode()
                    digest.update(b"L\0" + relative + b"\0" + target + b"\0")
                elif stat.S_ISDIR(info.st_mode):
                    digest.update(b"D\0" + relative + b"\0")
                elif stat.S_ISREG(info.st_mode):
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
                    try:
                        opened = os.fstat(fd)
                        if (
                            opened.st_dev != info.st_dev
                            or opened.st_ino != info.st_ino
                            or opened.st_size != info.st_size
                        ):
                            raise OSError
                        digest.update(
                            b"F\0" + relative + b"\0" + str(info.st_size).encode() + b"\0"
                        )
                        while chunk := os.read(fd, 1024 * 1024):
                            digest.update(chunk)
                        digest.update(b"\0")
                    finally:
                        os.close(fd)
                else:
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch",
                        "Managed Runtime contains an unsupported filesystem object",
                    )
    except ComfyUIRuntimeError:
        raise
    except OSError as exc:
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "Managed Runtime tree identity changed while it was inspected"
        ) from exc
    return digest.hexdigest()


def _read_owned_installation_record(
    version_root: Path,
) -> tuple[RuntimeInstallationRecord, RuntimeDirectoryIdentity, RuntimeDirectoryIdentity]:
    try:
        with _open_managed_directory(version_root) as (directory_fd, root_identity, version_identity):
            record_fd = os.open("installation.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                record_info = os.fstat(record_fd)
                if not stat.S_ISREG(record_info.st_mode) or record_info.st_size > 256 * 1024:
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "ComfyUI installation record is not a bounded regular file"
                    )
                payload = bytearray()
                while chunk := os.read(record_fd, 64 * 1024):
                    payload.extend(chunk)
            finally:
                os.close(record_fd)
        record = RuntimeInstallationRecord.model_validate_json(bytes(payload))
    except ComfyUIRuntimeError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "ComfyUI installation record is invalid") from exc
    if not _same_directory(record.managed_root_identity, root_identity):
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime root identity changed")
    if not _same_directory(record.version_directory_identity, version_identity):
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime version identity changed")
    return record, root_identity, version_identity


def validate_runtime_tree(version_root: Path, manifest: ComfyUIRuntimeManifest) -> RuntimeInstallationRecord:
    record, root_identity, _version_identity = _read_owned_installation_record(version_root)
    uv_artifact = manifest.python.uv_artifact
    python_artifact = manifest.python.python_runtime
    wheelhouse_artifact = manifest.python.wheelhouse
    if (
        record.version != manifest.version
        or record.source_commit != manifest.source_commit
        or record.manifest_sha256 != _manifest_sha256()
        or record.dependency_lock_sha256 != manifest.python.lock_sha256
        or manifest.python.toolchain_status != "ready"
        or uv_artifact is None
        or python_artifact is None
        or wheelhouse_artifact is None
        or record.environment_manager_version != manifest.python.environment_manager_version
        or record.toolchain_identity_sha256 != _toolchain_contract_identity(manifest)
        or record.uv_artifact_sha256 != uv_artifact.sha256
        or record.python_runtime_sha256 != python_artifact.tree_sha256
        or record.wheelhouse_sha256 != wheelhouse_artifact.sha256
        or record.wheel_artifact_lock_sha256 != wheelhouse_artifact.artifact_lock_sha256
        or record.source_tree_sha256 != manifest.source.source_tree_sha256
    ):
        raise ComfyUIRuntimeError("runtime_validation_failed", "ComfyUI installation identity differs from the manifest")
    if version_root == _version_root(manifest):
        parent_identity = _managed_directory_identity(version_root.parent, expected_root=root_identity)
        if not _same_directory(parent_identity, record.parent_directory_identity):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Managed Runtime parent identity changed")
    source = version_root / "source"
    python = _environment_python(version_root / "environment")
    if not python.is_file() or sha256_file(python) != record.python_executable_sha256:
        raise ComfyUIRuntimeError("runtime_modified", "ComfyUI managed Python executable was modified")
    for relative, digest in manifest.critical_files.items():
        target = source.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file() or sha256_file(target) != digest:
            raise ComfyUIRuntimeError("runtime_modified", "ComfyUI source files were modified outside HanClassStudio")
    if not custom_node_tree_is_pristine(source, manifest):
        raise ComfyUIRuntimeError("runtime_modified", "ComfyUI custom_nodes contains unapproved changes")
    if source_tree_fingerprint(source) != record.source_tree_sha256:
        raise ComfyUIRuntimeError("runtime_modified", "ComfyUI source tree was modified")
    actual_fingerprint = environment_fingerprint(version_root / "environment", manifest)
    if actual_fingerprint != record.environment_fingerprint:
        raise ComfyUIRuntimeError("runtime_modified", "ComfyUI isolated environment was modified")
    return record


def _source_contract_pristine(version_root: Path, manifest: ComfyUIRuntimeManifest) -> bool:
    source = version_root / "source"
    try:
        for relative, digest in manifest.critical_files.items():
            target = source.joinpath(*PurePosixPath(relative).parts)
            if not target.is_file() or sha256_file(target) != digest:
                return False
        record = RuntimeInstallationRecord.model_validate_json(
            _installation_record_path(version_root).read_text(encoding="utf-8")
        )
        return (
            custom_node_tree_is_pristine(source, manifest)
            and record.source_tree_sha256 == manifest.source.source_tree_sha256
            and source_tree_fingerprint(source) == manifest.source.source_tree_sha256
        )
    except (OSError, ValueError, ComfyUIRuntimeError):
        return False


RUNTIME_VALIDATOR = validate_runtime_tree


def _runtime_operation_summary(
    operation: Literal["repair", "uninstall"],
    manifest: ComfyUIRuntimeManifest,
) -> RuntimeOperationSummary:
    version_root = _version_root(manifest)
    record, _root_identity, _version_identity = _read_owned_installation_record(version_root)
    if (
        record.runtime_id != manifest.runtime_id
        or record.version != manifest.version
        or record.source_commit != manifest.source_commit
        or record.manifest_sha256 != _manifest_sha256()
    ):
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "Runtime installation identity does not match the current manifest"
        )
    modified = False
    try:
        RUNTIME_VALIDATOR(version_root, manifest)
    except ComfyUIRuntimeError as exc:
        if exc.code != "runtime_modified":
            raise
        modified = True
    return RuntimeOperationSummary(
        operation=operation,
        version=manifest.version,
        installation_identity=_installation_identity(record),
        tree_identity=installed_tree_fingerprint(version_root),
        modified=modified,
        replaces_runtime_files=operation == "repair",
    )


def prepare_runtime_operation(
    operation: Literal["repair", "uninstall"],
) -> RuntimeOperationConfirmation:
    summary = _runtime_operation_summary(operation, _runtime_manifest())
    token = secrets.token_hex(32)
    expires_at_epoch = time.time() + _CONFIRMATION_TTL_SECONDS
    record = RuntimeDestructiveConfirmationRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        summary=summary,
        nonce=secrets.token_hex(16),
        expires_at_epoch=expires_at_epoch,
    )
    with _CONFIRMATION_LOCK:
        now = time.time()
        for key, existing in list(_DESTRUCTIVE_CONFIRMATIONS.items()):
            if existing.expires_at_epoch <= now:
                _DESTRUCTIVE_CONFIRMATIONS.pop(key, None)
        _DESTRUCTIVE_CONFIRMATIONS[record.token_sha256] = record
    return RuntimeOperationConfirmation(
        summary=summary,
        confirmation_token=token,
        expires_at=datetime.fromtimestamp(expires_at_epoch, timezone.utc).isoformat(),
    )


def consume_runtime_operation_confirmation(
    operation: Literal["repair", "uninstall"],
    confirmation_token: str,
    expected_runtime_identity: str,
) -> RuntimeOperationSummary:
    token_sha256 = hashlib.sha256(confirmation_token.encode()).hexdigest()
    with _CONFIRMATION_LOCK:
        record = _DESTRUCTIVE_CONFIRMATIONS.pop(token_sha256, None)
    if record is None or not secrets.compare_digest(record.token_sha256, token_sha256):
        raise ComfyUIRuntimeError(
            "confirmation_invalid", "A valid one-time Runtime confirmation is required"
        )
    if record.expires_at_epoch <= time.time():
        raise ComfyUIRuntimeError("confirmation_expired", "The Runtime confirmation expired")
    if (
        record.summary.operation != operation
        or not secrets.compare_digest(
            record.summary.installation_identity, expected_runtime_identity
        )
    ):
        raise ComfyUIRuntimeError(
            "confirmation_invalid", "The Runtime confirmation does not match this operation"
        )
    current = _runtime_operation_summary(operation, _runtime_manifest())
    if current != record.summary:
        raise ComfyUIRuntimeError(
            "confirmation_stale", "The Runtime changed after confirmation was prepared"
        )
    return current


def assert_runtime_operation_identity(summary: RuntimeOperationSummary) -> None:
    current = _runtime_operation_summary(summary.operation, _runtime_manifest())
    if current != summary:
        raise ComfyUIRuntimeError(
            "confirmation_stale", "The Runtime changed before the confirmed operation started"
        )


def _write_installation_record(path: Path, record: RuntimeInstallationRecord) -> None:
    directory = path.parent
    with _open_managed_directory(
        directory, expected_root=record.managed_root_identity
    ) as (directory_fd, _root, directory_identity):
        if not _same_directory(directory_identity, record.version_directory_identity):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "Installation record directory identity changed")
        temporary = f".installation.{uuid.uuid4().hex}.tmp"
        encoded = json.dumps(
            record.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2
        ).encode("utf-8")
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
        os.rename(temporary, "installation.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)


def _remove_owned_runtime_tree(path: Path, manifest: ComfyUIRuntimeManifest) -> RuntimeInstallationRecord:
    record = RUNTIME_VALIDATOR(path, manifest)
    _secure_remove_managed_directory(
        path,
        root_identity=record.managed_root_identity,
        target_identity=record.version_directory_identity,
    )
    return record


def _remove_recorded_managed_paths(record: RuntimeInstallationRecord) -> None:
    for relative, identity in record.managed_path_identities.items():
        _secure_remove_managed_directory(
            _managed_root() / relative,
            root_identity=record.managed_root_identity,
            target_identity=identity,
        )


def _validate_journal_contract(
    journal: RuntimeInstallJournal,
    manifest: ComfyUIRuntimeManifest,
) -> None:
    expected_staging = f"staging/{journal.transaction_id}"
    expected_final = f"versions/{manifest.version}"
    expected_archive = f"{expected_staging}/source.tar.gz"
    expected_backup = f"backups/{manifest.version}-{journal.transaction_id}"
    if (
        journal.runtime_version != manifest.version
        or journal.manifest_sha256 != _manifest_sha256()
        or journal.expected_archive_sha256 != manifest.source.archive_sha256
        or journal.staging_relative_path != expected_staging
        or journal.final_relative_path != expected_final
        or journal.archive_relative_path not in {expected_archive, f"{expected_staging}/unused.tar.gz"}
        or (
            journal.operation in {"install", "repair"}
            and journal.backup_relative_path != expected_backup
        )
        or (journal.operation == "uninstall" and journal.backup_relative_path is not None)
    ):
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Runtime journal identity is not authoritative")
    with _open_managed_root(expected=journal.managed_root_identity):
        pass


def _remove_journal_staging(journal: RuntimeInstallJournal) -> None:
    if journal.staging_directory_identity is None:
        return
    _secure_remove_managed_directory(
        _managed_root() / journal.staging_relative_path,
        root_identity=journal.managed_root_identity,
        target_identity=journal.staging_directory_identity,
    )


def _default_progress(_phase: str, _percent: int, _message: str, _current: int | None, _total: int | None) -> None:
    return


def run_runtime_install(
    task_id: str,
    *,
    operation: Literal["install", "repair"] = "install",
    progress: ProgressCallback = _default_progress,
    cancel: CancellationCheck = lambda: None,
    confirmation: RuntimeOperationSummary | None = None,
) -> None:
    manifest = _runtime_manifest()
    adapter, _support, enabled = platform_adapter(manifest)
    with _MUTATION_LOCK:
        if operation == "repair":
            if confirmation is None or confirmation.operation != "repair":
                raise ComfyUIRuntimeError(
                    "confirmation_invalid", "Repair requires a valid backend confirmation"
                )
            assert_runtime_operation_identity(confirmation)
            try:
                stop_runtime(force=False)
            except ComfyUIRuntimeError as exc:
                if exc.code not in {"runtime_not_running", "runtime_not_installed"}:
                    raise
        if not enabled:
            raise ComfyUIRuntimeError(
                "unsupported_platform", "Current platform is not enabled for ComfyUI Runtime installation"
            )
        with _open_managed_root(create=True) as (_managed_fd, managed_root_identity):
            pass
        transaction_id = uuid.uuid4().hex
        staging_rel = f"staging/{transaction_id}"
        final_rel = f"versions/{manifest.version}"
        backup_rel = f"backups/{manifest.version}-{transaction_id}"
        archive_rel = f"{staging_rel}/source.tar.gz"
        now = _iso()
        journal = RuntimeInstallJournal(
            transaction_id=transaction_id,
            task_id=task_id,
            operation=operation,
            runtime_version=manifest.version,
            manifest_sha256=_manifest_sha256(),
            platform_adapter=adapter,
            staging_relative_path=staging_rel,
            final_relative_path=final_rel,
            backup_relative_path=backup_rel,
            archive_relative_path=archive_rel,
            expected_archive_sha256=manifest.source.archive_sha256,
            managed_root_identity=managed_root_identity,
            created_at=now,
            updated_at=now,
        )
        _save_journal(journal)
        staging = _resolve_journal_path(staging_rel)
        payload = staging / "payload"
        archive = _resolve_journal_path(archive_rel)
        final = _resolve_journal_path(final_rel)
        backup = _resolve_journal_path(backup_rel)
        try:
            progress("preflight", 3, "正在检查设备和受控安装目录", None, None)
            disk = shutil.disk_usage(storage.RUNTIME_DIR)
            required_free = max(8 * 1024**3, manifest.archive_policy.max_total_file_bytes * 8)
            if disk.free < required_free:
                raise ComfyUIRuntimeError("insufficient_disk", "ComfyUI Runtime installation needs at least 8 GB free disk space")
            staging_identity = _ensure_managed_directory(
                staging, root_identity=managed_root_identity
            )
            journal.staging_directory_identity = staging_identity
            _save_journal(journal)
            payload_identity = _ensure_managed_directory(
                payload, root_identity=managed_root_identity
            )
            cancel()
            _update_journal(journal, "downloading")
            progress("downloading", 8, "正在下载固定版本 ComfyUI", 0, manifest.source.archive_size)
            ARCHIVE_DOWNLOADER(
                archive,
                manifest,
                lambda current, total: progress(
                    "downloading", 8 + int(current * 17 / max(total, 1)), "正在下载固定版本 ComfyUI", current, total
                ),
                cancel,
            )
            _update_journal(journal, "downloaded")
            progress("verifying_download", 27, "正在校验下载文件", manifest.source.archive_size, manifest.source.archive_size)
            cancel()
            _update_journal(journal, "archive_validated")
            progress("inspecting_archive", 32, "正在扫描 archive 安全边界", None, None)
            source = payload / "source"
            extract_tar_gz(archive, source, manifest)
            _update_journal(journal, "tree_extracted")
            progress("verifying_extracted_tree", 48, "正在复核解压后的文件树", None, None)
            cancel()
            environment = payload / "environment"
            progress("creating_python_environment", 53, "正在创建隔离 Python 环境", None, None)
            toolchain = verify_python_toolchain(manifest)
            uv_artifact = manifest.python.uv_artifact
            python_artifact = manifest.python.python_runtime
            wheelhouse_artifact = manifest.python.wheelhouse
            if uv_artifact is None or python_artifact is None or wheelhouse_artifact is None:
                raise ComfyUIRuntimeError("python_environment_failed", "The fixed Python toolchain is incomplete")
            environment_fingerprint_value = ENVIRONMENT_BUILDER(environment, manifest, cancel)
            _update_journal(journal, "environment_created")
            progress("installing_dependencies", 78, "正在安装固定且校验过的依赖", None, None)
            _update_journal(journal, "dependencies_installed")
            source_tree_sha256 = source_tree_fingerprint(source)
            if source_tree_sha256 != manifest.source.source_tree_sha256:
                raise ComfyUIRuntimeError(
                    "runtime_validation_failed", "Extracted ComfyUI source tree differs from the pinned manifest"
                )
            _ensure_managed_directory(final.parent, root_identity=managed_root_identity)
            _ensure_managed_directory(backup.parent, root_identity=managed_root_identity)
            managed_path_identities = {
                relative: identity
                for relative in ("python", "uv-cache", "home")
                if (
                    identity := _optional_managed_directory_identity(
                        _managed_root() / relative,
                        root_identity=managed_root_identity,
                    )
                )
                is not None
            }
            record = RuntimeInstallationRecord(
                version=manifest.version,
                source_commit=manifest.source_commit,
                manifest_sha256=_manifest_sha256(),
                dependency_lock_sha256=manifest.python.lock_sha256,
                environment_fingerprint=environment_fingerprint_value,
                source_tree_sha256=source_tree_sha256,
                python_executable_sha256=sha256_file(_environment_python(environment)),
                environment_manager_version=manifest.python.environment_manager_version,
                toolchain_identity_sha256=toolchain.identity_sha256,
                uv_artifact_sha256=uv_artifact.sha256,
                python_runtime_sha256=python_artifact.tree_sha256,
                wheelhouse_sha256=wheelhouse_artifact.sha256,
                wheel_artifact_lock_sha256=wheelhouse_artifact.artifact_lock_sha256,
                platform_adapter=adapter,
                managed_root_identity=managed_root_identity,
                parent_directory_identity=_managed_directory_identity(
                    final.parent, expected_root=managed_root_identity
                ),
                version_directory_identity=payload_identity,
                managed_path_identities=managed_path_identities,
                installed_at=_iso(),
            )
            _write_installation_record(payload / "installation.json", record)
            progress("validating_runtime", 86, "正在验证受控运行环境", None, None)
            RUNTIME_VALIDATOR(payload, manifest)
            _update_journal(journal, "runtime_validated")
            cancel()
            _update_journal(journal, "publish_prepared")
            progress("publishing_runtime", 92, "正在发布受控运行环境", None, None)
            backup_identity = _optional_managed_directory_identity(
                backup, root_identity=managed_root_identity
            )
            if backup_identity is not None:
                _remove_owned_runtime_tree(backup, manifest)
            final_identity = _optional_managed_directory_identity(
                final, root_identity=managed_root_identity
            )
            if final_identity is not None:
                RUNTIME_VALIDATOR(final, manifest)
                _secure_replace_managed(final, backup, root_identity=managed_root_identity)
            _secure_replace_managed(payload, final, root_identity=managed_root_identity)
            _update_journal(journal, "runtime_published", published_paths=[final_rel])
            RUNTIME_VALIDATOR(final, manifest)
            state = RuntimeStateRecord(
                installed=True,
                version=manifest.version,
                status="stopped",
                platform_adapter=adapter,
                manifest_sha256=_manifest_sha256(),
                environment_fingerprint=environment_fingerprint_value,
                installed_at=record.installed_at,
                checked_at=_iso(),
            )
            _write_state(state)
            _update_journal(journal, "state_committed")
            if _optional_managed_directory_identity(
                backup, root_identity=managed_root_identity
            ) is not None:
                _remove_owned_runtime_tree(backup, manifest)
            _remove_journal_staging(journal)
            _update_journal(journal, "completed")
            _append_log("install", f"{operation} completed for ComfyUI {manifest.version} ({manifest.source_commit})")
            progress("completed", 100, "ComfyUI 运行环境已安装；尚未安装图片模型", None, None)
        except ComfyUIRuntimeError as exc:
            _append_log("install", f"{operation} failed: {exc.code}")
            _update_journal(journal, "rolling_back", error_code=exc.code)
            try:
                final_present = _optional_managed_directory_identity(
                    final, root_identity=managed_root_identity
                )
                backup_present = _optional_managed_directory_identity(
                    backup, root_identity=managed_root_identity
                )
                if final_present is not None and backup_present is not None:
                    _remove_owned_runtime_tree(final, manifest)
                    _secure_replace_managed(backup, final, root_identity=managed_root_identity)
                elif final_present is None and backup_present is not None:
                    _secure_replace_managed(backup, final, root_identity=managed_root_identity)
                _remove_journal_staging(journal)
                _update_journal(journal, "cancelled" if exc.code == "cancelled" else "rolled_back", error_code=exc.code)
            except (OSError, ComfyUIRuntimeError):
                _update_journal(journal, "failed", error_code="rollback_failed")
                _write_state(RuntimeStateRecord(
                    installed=final.exists(),
                    version=manifest.version if final.exists() else None,
                    status="repair_required",
                    platform_adapter=adapter,
                    error={"code": "rollback_failed"},
                ))
            raise
        except (ComfyUIArchiveError, OSError) as exc:
            code = _public_archive_error_code(exc.code) if isinstance(exc, ComfyUIArchiveError) else "internal_error"
            _append_log("install", f"{operation} failed: {code}")
            _update_journal(journal, "rolling_back", error_code=code)
            try:
                final_present = _optional_managed_directory_identity(
                    final, root_identity=managed_root_identity
                )
                backup_present = _optional_managed_directory_identity(
                    backup, root_identity=managed_root_identity
                )
                if final_present is not None and backup_present is not None:
                    _remove_owned_runtime_tree(final, manifest)
                    _secure_replace_managed(backup, final, root_identity=managed_root_identity)
                elif final_present is None and backup_present is not None:
                    _secure_replace_managed(backup, final, root_identity=managed_root_identity)
                _remove_journal_staging(journal)
                _update_journal(journal, "rolled_back", error_code=code)
            except (OSError, ComfyUIRuntimeError):
                _update_journal(journal, "failed", error_code="rollback_failed")
            raise ComfyUIRuntimeError(code, "ComfyUI Runtime installation failed safely") from exc


def recover_installations() -> list[str]:
    """Idempotently clean or finish durable Runtime transactions after a crash."""
    recovered: list[str] = []
    recovered_uninstall = False
    manifest = _runtime_manifest()
    with _MUTATION_LOCK:
        try:
            _reclaim_runtime_worker()
        except ComfyUIRuntimeError as exc:
            state = _read_state()
            state.status = "repair_required"
            state.error = {"code": exc.code, "message": exc.message}
            _write_state(state)
            raise
        for transaction_id, raw in list(_journals().items()):
            try:
                journal = RuntimeInstallJournal.model_validate(raw)
            except ValueError:
                state = _read_state()
                state.status = "repair_required"
                state.error = {"code": "runtime_identity_mismatch"}
                _write_state(state)
                recovered.append(transaction_id)
                continue
            if journal.transaction_id != transaction_id:
                state = _read_state()
                state.status = "repair_required"
                state.error = {"code": "runtime_identity_mismatch"}
                _write_state(state)
                recovered.append(transaction_id)
                continue
            if journal.phase in {"completed", "rolled_back", "failed", "cancelled"}:
                continue
            staging = _resolve_journal_path(journal.staging_relative_path)
            final = _resolve_journal_path(journal.final_relative_path)
            backup = _resolve_journal_path(journal.backup_relative_path) if journal.backup_relative_path else None
            try:
                _validate_journal_contract(journal, manifest)
                final_present = _optional_managed_directory_identity(
                    final, root_identity=journal.managed_root_identity
                )
                payload_present = _optional_managed_directory_identity(
                    staging / "payload", root_identity=journal.managed_root_identity
                )
                backup_present = (
                    _optional_managed_directory_identity(
                        backup, root_identity=journal.managed_root_identity
                    )
                    if backup is not None
                    else None
                )
                if journal.operation == "uninstall":
                    if final_present is not None:
                        record = _remove_owned_runtime_tree(final, manifest)
                        _remove_recorded_managed_paths(record)
                    _remove_journal_staging(journal)
                    _write_process(None)
                    _write_state(RuntimeStateRecord())
                    _update_journal(journal, "completed")
                    recovered_uninstall = True
                elif (
                    journal.phase in {"publish_prepared", "runtime_published", "state_committed"}
                    and final_present is not None
                    and payload_present is None
                ):
                    record = RUNTIME_VALIDATOR(final, manifest)
                    _write_state(RuntimeStateRecord(
                        installed=True,
                        version=manifest.version,
                        status="stopped",
                        platform_adapter=journal.platform_adapter,
                        manifest_sha256=journal.manifest_sha256,
                        environment_fingerprint=record.environment_fingerprint,
                        installed_at=record.installed_at,
                        checked_at=_iso(),
                    ))
                    if backup is not None and backup_present is not None:
                        _remove_owned_runtime_tree(backup, manifest)
                    _remove_journal_staging(journal)
                    _update_journal(journal, "completed")
                else:
                    if backup is not None and backup_present is not None:
                        if final_present is not None:
                            _remove_owned_runtime_tree(final, manifest)
                        _secure_replace_managed(
                            backup,
                            final,
                            root_identity=journal.managed_root_identity,
                        )
                    elif (
                        journal.phase == "publish_prepared"
                        and final_present is not None
                        and payload_present is None
                    ):
                        _remove_owned_runtime_tree(final, manifest)
                    _remove_journal_staging(journal)
                    _update_journal(journal, "rolled_back", error_code="interrupted")
                recovered.append(transaction_id)
            except (OSError, ComfyUIRuntimeError) as exc:
                code = "runtime_identity_mismatch" if isinstance(exc, ComfyUIRuntimeError) and exc.code == "runtime_identity_mismatch" else "recovery_failed"
                _update_journal(journal, "failed", error_code=code)
                prior_state = _read_state()
                _write_state(RuntimeStateRecord(
                    installed=prior_state.installed,
                    version=prior_state.version,
                    status="repair_required",
                    platform_adapter=journal.platform_adapter,
                    error={"code": code},
                ))
                recovered.append(transaction_id)
    if recovered_uninstall:
        _config_path(_STATE_FILE).unlink(missing_ok=True)
        _config_path(_JOURNAL_FILE).unlink(missing_ok=True)
    return recovered


def runtime_transaction_phase(task_id: str) -> RuntimeJournalPhase | None:
    matching: list[RuntimeInstallJournal] = []
    for raw in _journals().values():
        try:
            journal = RuntimeInstallJournal.model_validate(raw)
        except ValueError:
            continue
        if journal.task_id == task_id:
            matching.append(journal)
    if not matching:
        return None
    return max(matching, key=lambda item: item.created_at).phase


def _read_process() -> ComfyUIRuntimeProcess | None:
    path = _config_path(_PROCESS_FILE)
    if not path.exists():
        return None
    raw = _read_json(path)
    try:
        return ComfyUIRuntimeProcess.model_validate(raw)
    except ValueError as exc:
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "Managed ComfyUI process ownership record is invalid"
        ) from exc


def _write_process(process: ComfyUIRuntimeProcess | None) -> None:
    with _CONFIG_LOCK:
        if process is None:
            _config_path(_PROCESS_FILE).unlink(missing_ok=True)
        else:
            _atomic_json(_config_path(_PROCESS_FILE), process.model_dump(mode="json", by_alias=True))


def _read_worker_process() -> RuntimeWorkerOwnership | None:
    path = _config_path(_WORKER_PROCESS_FILE)
    if not path.exists():
        return None
    try:
        return RuntimeWorkerOwnership.model_validate(_read_json(path))
    except (OSError, ValueError) as exc:
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "Managed Runtime worker ownership record is invalid"
        ) from exc


def _write_worker_process(process: RuntimeWorkerOwnership | None) -> None:
    with _CONFIG_LOCK:
        if process is None:
            _config_path(_WORKER_PROCESS_FILE).unlink(missing_ok=True)
        else:
            _atomic_json(
                _config_path(_WORKER_PROCESS_FILE),
                process.model_dump(mode="json", by_alias=True),
            )


def _process_start_token(pid: int) -> str | None:
    if platform.system().lower() == "linux":
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            return fields[21]
        except (OSError, IndexError):
            return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env={"PATH": os.defpath},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = " ".join(result.stdout.split())
    return token or None


def _process_command(pid: int) -> list[str] | str | None:
    if platform.system().lower() == "linux":
        try:
            return [part.decode("utf-8", errors="replace") for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]
        except OSError:
            return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env={"PATH": os.defpath},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Darwin exposes a single command string rather than Linux's NUL-delimited argv.
    # It is compared byte-for-byte with the HCS-built argv string and combined with
    # start token, executable hash, nonce-bearing paths, port, and API-reported argv.
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _process_cwd(pid: int) -> Path | None:
    if platform.system().lower() == "linux":
        try:
            return Path(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            return None
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env={"PATH": os.defpath},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n/"):
            return Path(line[1:])
    return None


def _process_group_identity(pid: int) -> tuple[int, int] | None:
    if os.name != "posix":
        return None
    try:
        return os.getpgid(pid), os.getsid(pid)
    except (OSError, ProcessLookupError):
        return None


def _process_cwd_matches(pid: int, expected: Path) -> bool:
    actual = _process_cwd(pid)
    if actual is None:
        return False
    try:
        return _directory_identity(actual.stat()) == _directory_identity(expected.stat())
    except OSError:
        return False


def _process_group_alive(process_group_id: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.killpg(process_group_id, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False


def _linux_descendants(pid: int) -> set[int]:
    descendants = {pid}
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text(encoding="utf-8")
        except OSError:
            continue
        for value in children.split():
            child = int(value)
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def _linux_listener_owners(process: ComfyUIRuntimeProcess) -> list[tuple[int, str]]:
    port_hex = f"{process.ownership.port:04X}"
    sockets: dict[str, str] = {}
    for table, ipv6 in ((Path("/proc/net/tcp"), False), (Path("/proc/net/tcp6"), True)):
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            address_hex, candidate_port = fields[1].rsplit(":", 1)
            if candidate_port != port_hex:
                continue
            if ipv6:
                address = "::" if set(address_hex) <= {"0"} else "ipv6"
            else:
                try:
                    address = socket.inet_ntoa(bytes.fromhex(address_hex)[::-1])
                except (OSError, ValueError):
                    address = "invalid"
            sockets[fields[9]] = address
    owners: list[tuple[int, str]] = []
    for pid in _linux_descendants(process.ownership.pid):
        try:
            descriptors = Path(f"/proc/{pid}/fd").iterdir()
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor)
                except OSError:
                    continue
                if target.startswith("socket:[") and target.endswith("]"):
                    inode = target[8:-1]
                    if inode in sockets:
                        owners.append((pid, sockets[inode]))
        except OSError:
            continue
    return sorted(set(owners))


def _darwin_listener_owners(process: ComfyUIRuntimeProcess) -> list[tuple[int, str]]:
    try:
        result = subprocess.run(
            [
                "/usr/sbin/lsof", "-nP",
                f"-iTCP:{process.ownership.port}", "-sTCP:LISTEN", "-Fpfn",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            env={"PATH": os.defpath},
        )
    except (OSError, subprocess.SubprocessError):
        return []
    owners: list[tuple[int, str]] = []
    pid: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif pid is not None and line.startswith("n"):
            endpoint = line[1:].removeprefix("TCP ").removesuffix(" (LISTEN)")
            address = endpoint.rsplit(":", 1)[0].strip("[]")
            owners.append((pid, address))
    return sorted(set(owners))


def _listener_owners(process: ComfyUIRuntimeProcess) -> list[tuple[int, str]]:
    if platform.system().lower() == "linux":
        return _linux_listener_owners(process)
    if platform.system().lower() == "darwin":
        return _darwin_listener_owners(process)
    return []


def _process_alive(pid: int) -> bool:
    handle = _PROCESS_HANDLES.get(pid) or _WORKER_HANDLES.get(pid)
    if handle is not None:
        return handle.poll() is None
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _argv_digest(argv: list[str]) -> str:
    return hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest()


def _installation_identity(record: RuntimeInstallationRecord) -> str:
    return hashlib.sha256(
        json.dumps(record.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _expected_runtime_argv(manifest: ComfyUIRuntimeManifest, port: int, nonce: str) -> list[str]:
    version = _version_root(manifest)
    data = _runtime_data_root()
    return [
        str(_environment_python(version / "environment")),
        "-s",
        str(version / "source" / manifest.launch.entrypoint),
        *manifest.launch.fixed_arguments,
        "--port", str(port),
        "--base-directory", str(data),
        "--input-directory", str(data / "input"),
        "--output-directory", str(data / "output"),
        "--temp-directory", str(data / "temp"),
        "--user-directory", str(data / "user" / nonce),
        "--models-directory", str(_models_root()),
    ]


def _supervisor_script() -> Path:
    return Path(__file__).with_name("comfyui_supervisor.py")


def _supervisor_request_path(nonce: str) -> Path:
    return _runtime_data_root() / "user" / nonce / "supervisor-request.json"


def _expected_supervisor_argv(nonce: str) -> list[str]:
    return [sys.executable, "-I", str(_supervisor_script()), str(_supervisor_request_path(nonce))]


def _ownership_mismatch_reason(
    process: ComfyUIRuntimeProcess, manifest: ComfyUIRuntimeManifest
) -> str | None:
    ownership = process.ownership
    if (
        ownership.runtime_version != manifest.version
        or ownership.runtime_root_relative_path != f"versions/{manifest.version}"
        or ownership.cwd_relative_path != f"versions/{manifest.version}/source"
        or not manifest.launch.port_min <= ownership.port <= manifest.launch.port_max
        or ownership.process_group_id != ownership.pid
        or ownership.session_id != ownership.pid
    ):
        return "runtime_contract"
    if not _process_alive(ownership.pid):
        return "process_not_alive"
    if _process_start_token(ownership.pid) != ownership.process_start_token:
        return "process_start_token"
    if _process_group_identity(ownership.pid) != (
        ownership.process_group_id,
        ownership.session_id,
    ):
        return "process_group"
    expected_runtime_argv = _expected_runtime_argv(manifest, ownership.port, ownership.nonce)
    expected_supervisor_argv = _expected_supervisor_argv(ownership.nonce)
    if _argv_digest(expected_supervisor_argv) != ownership.expected_argv_sha256:
        return "argv_digest"
    if _argv_digest(expected_runtime_argv) != ownership.runtime_argv_sha256:
        return "runtime_argv_digest"
    try:
        installation, _root_identity, _version_identity = _read_owned_installation_record(
            _version_root(manifest)
        )
        if _installation_identity(installation) != ownership.installation_identity_sha256:
            return "installation_identity"
    except ComfyUIRuntimeError:
        return "installation_identity"
    try:
        if source_tree_fingerprint(_source_root(manifest)) != ownership.source_tree_sha256:
            return "source_tree"
    except ComfyUIRuntimeError:
        return "source_tree_unreadable"
    command = _process_command(ownership.pid)
    expected_command: list[str] | str = (
        expected_supervisor_argv if isinstance(command, list) else " ".join(expected_supervisor_argv)
    )
    if command != expected_command:
        return "process_command"
    if not _process_cwd_matches(ownership.pid, _source_root(manifest)):
        return "process_cwd"
    executable = Path(expected_supervisor_argv[0])
    try:
        if not executable.is_file() or sha256_file(executable) != ownership.executable_sha256:
            return "executable"
        if sha256_file(_supervisor_script()) != ownership.supervisor_script_sha256:
            return "supervisor_script"
    except OSError:
        return "executable_unreadable"
    return None


def _ownership_matches(process: ComfyUIRuntimeProcess, manifest: ComfyUIRuntimeManifest) -> bool:
    return _ownership_mismatch_reason(process, manifest) is None


def _orphan_group_is_reclaimable(
    process: ComfyUIRuntimeProcess, manifest: ComfyUIRuntimeManifest
) -> bool:
    ownership = process.ownership
    if (
        ownership.process_group_id != ownership.pid
        or ownership.session_id != ownership.pid
        or ownership.runtime_version != manifest.version
        or ownership.runtime_root_relative_path != f"versions/{manifest.version}"
        or ownership.cwd_relative_path != f"versions/{manifest.version}/source"
        or not _process_group_alive(ownership.process_group_id)
    ):
        return False
    try:
        installation, _root_identity, _version_identity = _read_owned_installation_record(
            _version_root(manifest)
        )
        return (
            _installation_identity(installation) == ownership.installation_identity_sha256
            and source_tree_fingerprint(_source_root(manifest)) == ownership.source_tree_sha256
            and sha256_file(Path(_expected_supervisor_argv(ownership.nonce)[0]))
            == ownership.executable_sha256
            and sha256_file(_supervisor_script()) == ownership.supervisor_script_sha256
            and _argv_digest(_expected_supervisor_argv(ownership.nonce))
            == ownership.expected_argv_sha256
            and _argv_digest(_expected_runtime_argv(manifest, ownership.port, ownership.nonce))
            == ownership.runtime_argv_sha256
        )
    except (OSError, ComfyUIRuntimeError):
        return False


def _runtime_worker_mismatch_reason(worker: RuntimeWorkerOwnership) -> str | None:
    if worker.process_group_id != worker.pid or worker.session_id != worker.pid:
        return "process_group_contract"
    if not _process_alive(worker.pid):
        return "process_not_alive"
    if _process_start_token(worker.pid) != worker.process_start_token:
        return "process_start_token"
    if _process_group_identity(worker.pid) != (worker.process_group_id, worker.session_id):
        return "process_group"
    if _argv_digest(worker.argv) != worker.argv_sha256:
        return "argv_digest"
    try:
        root_identity = _current_managed_root_identity()
        cwd = _managed_root() if worker.cwd_relative_path == "." else (
            _managed_root().joinpath(*PurePosixPath(worker.cwd_relative_path).parts)
        )
        command = _process_command(worker.pid)
        expected_command: list[str] | str = (
            worker.argv if isinstance(command, list) else " ".join(worker.argv)
        )
        if not _same_directory(root_identity, worker.managed_root_identity):
            return "managed_root"
        if not _process_cwd_matches(worker.pid, cwd):
            return "process_cwd"
        if command != expected_command:
            return "process_command"
        if not Path(worker.argv[0]).is_absolute():
            return "executable_path"
        if sha256_file(Path(worker.argv[0])) != worker.executable_sha256:
            return "executable"
    except (OSError, ComfyUIRuntimeError):
        return "identity_unreadable"
    return None


def _reclaim_runtime_worker() -> bool:
    worker = _read_worker_process()
    if worker is None:
        return False
    if not _process_alive(worker.pid) and not _process_group_alive(worker.process_group_id):
        _WORKER_HANDLES.pop(worker.pid, None)
        _write_worker_process(None)
        return True
    mismatch = _runtime_worker_mismatch_reason(worker)
    if mismatch:
        _append_log("install", f"managed worker identity mismatch: {mismatch}")
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "Refusing to reclaim a Runtime worker with mismatched ownership"
        )
    try:
        os.killpg(worker.process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "The owned Runtime worker could not be reclaimed"
        ) from exc
    deadline = time.monotonic() + 5
    while (
        _process_alive(worker.pid) or _process_group_alive(worker.process_group_id)
    ) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_alive(worker.pid) or _process_group_alive(worker.process_group_id):
        raise ComfyUIRuntimeError(
            "runtime_identity_mismatch", "The owned Runtime worker did not stop"
        )
    _WORKER_HANDLES.pop(worker.pid, None)
    _write_worker_process(None)
    return True


def _find_port(manifest: ComfyUIRuntimeManifest) -> int:
    for port in range(manifest.launch.port_min, manifest.launch.port_max + 1):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            candidate.bind((manifest.launch.listen_host, port))
            return port
        except OSError:
            continue
        finally:
            candidate.close()
    raise ComfyUIRuntimeError("port_conflict", "No managed loopback port is available for ComfyUI")


def _read_http_json(port: int, path: str, *, max_bytes: int, timeout: float) -> Any:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ComfyUIRuntimeError("runtime_health_failed", "ComfyUI health API returned an unexpected status")
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ComfyUIRuntimeError("runtime_health_failed", "ComfyUI health response exceeded its size limit")
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ComfyUIRuntimeError("runtime_health_failed", "ComfyUI health response exceeded its size limit")
        return json.loads(body)
    except ComfyUIRuntimeError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException, ValueError, json.JSONDecodeError) as exc:
        raise ComfyUIRuntimeError("runtime_health_failed", "ComfyUI health API could not be verified") from exc
    finally:
        connection.close()


def _listener_identity_mismatch_reason(
    process: ComfyUIRuntimeProcess, manifest: ComfyUIRuntimeManifest
) -> str | None:
    owners = _listener_owners(process)
    if not owners:
        try:
            with socket.create_connection(("127.0.0.1", process.ownership.port), timeout=0.1):
                started = datetime.fromisoformat(process.ownership.started_at).timestamp()
                return "listener_not_ready" if time.time() - started < 1 else "listener_owner"
        except OSError:
            return "listener_not_ready"
        except ValueError:
            return "listener_owner"
    if len(owners) != 1:
        return "listener_owner"
    listener_pid, address = owners[0]
    if address != "127.0.0.1":
        return "listener_address"
    ownership = process.ownership
    if _process_group_identity(listener_pid) != (
        ownership.process_group_id,
        ownership.session_id,
    ):
        return "listener_process_group"
    start_token = _process_start_token(listener_pid)
    if start_token is None:
        return "listener_start_token"
    if ownership.listener_pid is not None and ownership.listener_pid != listener_pid:
        return "listener_pid_changed"
    if (
        ownership.listener_start_token is not None
        and ownership.listener_start_token != start_token
    ):
        return "listener_start_token_changed"
    expected_argv = _expected_runtime_argv(manifest, ownership.port, ownership.nonce)
    if _argv_digest(expected_argv) != ownership.runtime_argv_sha256:
        return "listener_argv_digest"
    command = _process_command(listener_pid)
    expected_command: list[str] | str = (
        expected_argv if isinstance(command, list) else " ".join(expected_argv)
    )
    if command != expected_command:
        return "listener_command"
    if not _process_cwd_matches(listener_pid, _source_root(manifest)):
        return "listener_cwd"
    try:
        installation, _root_identity, _version_identity = _read_owned_installation_record(
            _version_root(manifest)
        )
        if sha256_file(Path(expected_argv[0])) != installation.python_executable_sha256:
            return "listener_executable"
    except (OSError, ComfyUIRuntimeError):
        return "listener_executable"
    ownership.listener_pid = listener_pid
    ownership.listener_start_token = start_token
    return None


def _health_probe(process: ComfyUIRuntimeProcess, manifest: ComfyUIRuntimeManifest) -> RuntimeHealthSnapshot:
    checked_at = _iso()
    if not _process_alive(process.ownership.pid):
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=checked_at,
            status="crashed",
            error={"code": "runtime_crashed", "message": "The managed ComfyUI process exited unexpectedly"},
        )
    ownership_mismatch = _ownership_mismatch_reason(process, manifest)
    if ownership_mismatch:
        _append_log("runtime", f"managed process identity mismatch: {ownership_mismatch}")
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=checked_at,
            status="repair_required",
            port=process.ownership.port,
            error={
                "code": "runtime_identity_mismatch",
                "message": f"The recorded process identity no longer matches ({ownership_mismatch})",
            },
        )
    listener_mismatch = _listener_identity_mismatch_reason(process, manifest)
    if listener_mismatch:
        _append_log("runtime", f"managed listener identity mismatch: {listener_mismatch}")
        listener_not_ready = listener_mismatch == "listener_not_ready"
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=checked_at,
            status="degraded" if listener_not_ready else "repair_required",
            port=process.ownership.port,
            error={
                "code": "runtime_health_failed" if listener_not_ready else "runtime_identity_mismatch",
                "message": f"The Runtime listener identity does not match ({listener_mismatch})",
            },
        )
    if not custom_node_tree_is_pristine(_source_root(manifest), manifest):
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=checked_at,
            status="unsupported_modified",
            port=process.ownership.port,
            identity_verified=True,
            error={"code": "runtime_modified", "message": "Unapproved custom-node changes were detected"},
        )
    try:
        system_stats = _read_http_json(
            process.ownership.port,
            manifest.launch.health_path,
            max_bytes=2 * 1024 * 1024,
            timeout=3,
        )
        if not isinstance(system_stats, dict) or not isinstance(system_stats.get("system"), dict):
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "ComfyUI system response shape is invalid")
        system = system_stats["system"]
        if system.get("comfyui_version") != manifest.version:
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "ComfyUI API version differs from the fixed Runtime")
        api_argv = system.get("argv")
        expected_without_python = _expected_runtime_argv(
            manifest, process.ownership.port, process.ownership.nonce
        )[2:]
        if not isinstance(api_argv, list) or [str(value) for value in api_argv] != expected_without_python:
            raise ComfyUIRuntimeError("runtime_identity_mismatch", "ComfyUI API arguments do not match the managed process")
        object_info = _read_http_json(
            process.ownership.port,
            "/object_info",
            max_bytes=24 * 1024 * 1024,
            timeout=10,
        )
        required_nodes = {"KSampler", "CheckpointLoaderSimple", "SaveImage"}
        if not isinstance(object_info, dict) or not required_nodes.issubset(object_info):
            raise ComfyUIRuntimeError("runtime_health_failed", "Required ComfyUI core nodes are unavailable")
    except ComfyUIRuntimeError as exc:
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=checked_at,
            status="repair_required" if exc.code == "runtime_identity_mismatch" else "degraded",
            version=manifest.version,
            port=process.ownership.port,
            custom_nodes_pristine=True,
            identity_verified=exc.code != "runtime_identity_mismatch",
            error={"code": exc.code, "message": exc.message},
        )
    return RuntimeHealthSnapshot(
        healthy=True,
        checked_at=checked_at,
        status="runtime_ready",
        version=manifest.version,
        port=process.ownership.port,
        core_api_available=True,
        custom_nodes_pristine=True,
        identity_verified=True,
    )


HEALTH_PROBER = _health_probe


def _capture_process_output(pid: int, pipe: Any) -> None:
    try:
        while chunk := pipe.readline():
            _append_log("runtime", chunk.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass
        _LOG_THREADS.pop(pid, None)


def check_runtime_health() -> RuntimeHealthSnapshot:
    manifest = _runtime_manifest()
    state = _read_state()
    if state.installed:
        try:
            RUNTIME_VALIDATOR(_version_root(manifest), manifest)
        except ComfyUIRuntimeError as exc:
            state.status = "unsupported_modified" if exc.code == "runtime_modified" else "repair_required"
            state.checked_at = _iso()
            state.error = {"code": exc.code, "message": exc.message}
            _write_state(state)
            return RuntimeHealthSnapshot(
                healthy=False,
                checked_at=state.checked_at,
                status=state.status,
                version=state.version,
                custom_nodes_pristine=False,
                error=state.error,
            )
    try:
        process = _read_process()
    except ComfyUIRuntimeError as exc:
        state.status = "repair_required"
        state.checked_at = _iso()
        state.error = {"code": exc.code, "message": exc.message}
        _write_state(state)
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=state.checked_at,
            status="repair_required",
            version=state.version,
            error=state.error,
        )
    if process is None:
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=_iso(),
            status="stopped" if state.installed else "not_installed",
            version=state.version,
            custom_nodes_pristine=state.installed and custom_node_tree_is_pristine(_source_root(manifest), manifest),
            error={"code": "runtime_not_running", "message": "ComfyUI Runtime is not running"},
        )
    if (
        not _process_alive(process.ownership.pid)
        and _process_group_alive(process.ownership.process_group_id)
    ):
        try:
            _stop_owned_process(process, manifest, force=True)
        except ComfyUIRuntimeError as exc:
            state.status = "repair_required"
            state.error = {"code": exc.code, "message": exc.message}
            _write_state(state)
            return RuntimeHealthSnapshot(
                healthy=False,
                checked_at=_iso(),
                status="repair_required",
                version=state.version,
                port=process.ownership.port,
                error=state.error,
            )
        _write_process(None)
        state.status = "crashed"
        state.error = {
            "code": "runtime_crashed",
            "message": "The managed supervisor exited; its owned process group was reclaimed",
        }
        state.checked_at = _iso()
        _write_state(state)
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=state.checked_at,
            status="crashed",
            version=state.version,
            port=process.ownership.port,
            identity_verified=True,
            error=state.error,
        )
    health = HEALTH_PROBER(process, manifest)
    state.checked_at = health.checked_at
    state.status = health.status
    state.error = health.error
    _write_state(state)
    if health.status == "crashed":
        handle = _PROCESS_HANDLES.pop(process.ownership.pid, None)
        exit_code = handle.poll() if handle else None
        process.state = "crashed"
        process.exit_code = exit_code
        process.updated_at = _iso()
        process.error = health.error
        _write_process(process)
    elif health.status == "repair_required":
        process.state = "identity_mismatch"
        process.updated_at = _iso()
        process.error = health.error
        _write_process(process)
    elif health.healthy:
        process.state = "running"
        process.updated_at = _iso()
        process.error = None
        _write_process(process)
    return health


def start_runtime() -> RuntimeHealthSnapshot:
    manifest = _runtime_manifest()
    with _PROCESS_LOCK:
        state = _read_state()
        if not state.installed:
            raise ComfyUIRuntimeError("runtime_not_installed", "Install ComfyUI Runtime before starting it")
        existing = _read_process()
        if existing and _process_group_alive(existing.ownership.process_group_id):
            if _process_alive(existing.ownership.pid):
                if not _ownership_matches(existing, manifest):
                    raise ComfyUIRuntimeError(
                        "runtime_identity_mismatch", "Refusing to control a process with mismatched ownership"
                    )
                health = HEALTH_PROBER(existing, manifest)
                if health.healthy:
                    return health
                raise ComfyUIRuntimeError(
                    health.error["code"] if health.error else "runtime_health_failed",
                    "Managed ComfyUI is running but unhealthy",
                )
            _stop_owned_process(existing, manifest, force=True)
            _write_process(None)
        if existing:
            _write_process(None)
        try:
            installation = RUNTIME_VALIDATOR(_version_root(manifest), manifest)
        except ComfyUIRuntimeError as exc:
            state.status = "unsupported_modified" if exc.code == "runtime_modified" else "repair_required"
            state.error = {"code": exc.code, "message": exc.message}
            _write_state(state)
            raise
        port = _find_port(manifest)
        data = _runtime_data_root()
        for directory in (
            data / "input", data / "output", data / "temp", data / "user", _models_root(), _logs_root()
        ):
            directory.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_hex(16)
        (data / "user" / nonce).mkdir(parents=True, exist_ok=True)
        runtime_argv = _expected_runtime_argv(manifest, port, nonce)
        supervisor_argv = _expected_supervisor_argv(nonce)
        supervisor_script = _supervisor_script()
        try:
            executable_sha256 = sha256_file(Path(supervisor_argv[0]))
            supervisor_script_sha256 = sha256_file(supervisor_script)
        except OSError as exc:
            raise ComfyUIRuntimeError("runtime_validation_failed", "Managed process supervisor cannot be verified") from exc
        request_path = _supervisor_request_path(nonce)
        _atomic_json(request_path, {
            "argv": runtime_argv,
            "cwd": str(_source_root(manifest)),
            "environment": {
                **_controlled_environment(),
                "HCS_COMFYUI_RUNTIME_NONCE": nonce,
            },
        })
        request_path.chmod(0o600)
        state.status = "starting"
        state.error = None
        _write_state(state)
        _append_log("runtime", f"starting ComfyUI {manifest.version} on loopback port {port}")
        try:
            process_handle = subprocess.Popen(
                supervisor_argv,
                cwd=_source_root(manifest),
                env=_controlled_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
                shell=False,
            )
        except OSError as exc:
            request_path.unlink(missing_ok=True)
            state.status = "failed"
            state.error = {"code": "runtime_start_failed"}
            _write_state(state)
            raise ComfyUIRuntimeError("runtime_start_failed", "ComfyUI Runtime process could not be started") from exc
        _PROCESS_HANDLES[process_handle.pid] = process_handle
        start_token = None
        group_identity = None
        deadline = time.monotonic() + 3
        while (
            (start_token is None or group_identity is None)
            and process_handle.poll() is None
            and time.monotonic() < deadline
        ):
            start_token = _process_start_token(process_handle.pid)
            group_identity = _process_group_identity(process_handle.pid)
            if start_token is None or group_identity is None:
                time.sleep(0.02)
        if (
            start_token is None
            or group_identity is None
            or group_identity != (process_handle.pid, process_handle.pid)
        ):
            process_handle.terminate()
            process_handle.wait(timeout=5)
            _PROCESS_HANDLES.pop(process_handle.pid, None)
            state.status = "failed"
            state.error = {"code": "runtime_start_failed"}
            _write_state(state)
            raise ComfyUIRuntimeError("runtime_start_failed", "ComfyUI process identity could not be recorded")
        ownership = RuntimeProcessOwnership(
            pid=process_handle.pid,
            process_start_token=start_token,
            process_group_id=group_identity[0],
            session_id=group_identity[1],
            executable_sha256=executable_sha256,
            runtime_version=manifest.version,
            runtime_root_relative_path=f"versions/{manifest.version}",
            cwd_relative_path=f"versions/{manifest.version}/source",
            installation_identity_sha256=_installation_identity(installation),
            port=port,
            nonce=nonce,
            expected_argv_sha256=_argv_digest(supervisor_argv),
            runtime_argv_sha256=_argv_digest(runtime_argv),
            supervisor_script_sha256=supervisor_script_sha256,
            source_tree_sha256=installation.source_tree_sha256,
            started_at=_iso(),
        )
        process = ComfyUIRuntimeProcess(state="starting", ownership=ownership, updated_at=_iso())
        _write_process(process)
        if process_handle.stdout is not None:
            log_thread = threading.Thread(
                target=_capture_process_output,
                args=(process_handle.pid, process_handle.stdout),
                daemon=True,
                name=f"hcs-comfyui-log-{process_handle.pid}",
            )
            _LOG_THREADS[process_handle.pid] = log_thread
            log_thread.start()
        deadline = time.monotonic() + manifest.launch.startup_timeout_seconds
        last_health: RuntimeHealthSnapshot | None = None
        while time.monotonic() < deadline:
            if process_handle.poll() is not None:
                state.status = "crashed"
                state.error = {"code": "runtime_crashed"}
                _write_state(state)
                process.state = "crashed"
                process.exit_code = process_handle.returncode
                process.error = {"code": "runtime_crashed", "message": "ComfyUI exited during startup"}
                process.updated_at = _iso()
                _write_process(process)
                raise ComfyUIRuntimeError("runtime_crashed", "ComfyUI exited during startup")
            last_health = HEALTH_PROBER(process, manifest)
            if last_health.healthy:
                process.state = "running"
                process.updated_at = _iso()
                _write_process(process)
                state.status = "runtime_ready"
                state.checked_at = last_health.checked_at
                state.error = None
                _write_state(state)
                return last_health
            if last_health.status == "repair_required":
                break
            time.sleep(0.25)
        try:
            _stop_owned_process(process, manifest, force=True)
        except ComfyUIRuntimeError:
            pass
        _PROCESS_HANDLES.pop(process.ownership.pid, None)
        _write_process(None)
        error_code = (
            last_health.error["code"]
            if last_health and last_health.error and last_health.status == "repair_required"
            else "runtime_start_timeout"
        )
        state.status = "repair_required" if error_code == "runtime_identity_mismatch" else "failed"
        state.error = {"code": error_code}
        _write_state(state)
        raise ComfyUIRuntimeError(error_code, "ComfyUI Runtime did not become healthy before the startup timeout")


def _stop_owned_process(
    process: ComfyUIRuntimeProcess,
    manifest: ComfyUIRuntimeManifest,
    *,
    force: bool,
) -> None:
    ownership = process.ownership
    leader_alive = _process_alive(ownership.pid)
    if leader_alive and not _ownership_matches(process, manifest):
        raise ComfyUIRuntimeError("runtime_identity_mismatch", "Refusing to stop a process with mismatched ownership")
    group_alive = _process_group_alive(ownership.process_group_id)
    if not leader_alive:
        if not group_alive:
            return
        if not _orphan_group_is_reclaimable(process, manifest):
            raise ComfyUIRuntimeError(
                "runtime_identity_mismatch", "Refusing to reclaim a process group with mismatched ownership"
            )
    pid = ownership.pid
    try:
        if os.name == "posix":
            os.killpg(ownership.process_group_id, signal.SIGKILL if force else signal.SIGTERM)
        else:
            handle = _PROCESS_HANDLES.get(pid)
            if handle is None:
                raise ComfyUIRuntimeError("runtime_stop_failed", "Managed process handle is unavailable")
            handle.kill() if force else handle.terminate()
    except ProcessLookupError:
        return
    except OSError as exc:
        raise ComfyUIRuntimeError("runtime_stop_failed", "ComfyUI Runtime could not be stopped") from exc
    timeout = 5 if force else manifest.launch.shutdown_timeout_seconds
    deadline = time.monotonic() + timeout
    while (
        _process_alive(pid) or _process_group_alive(ownership.process_group_id)
    ) and time.monotonic() < deadline:
        time.sleep(0.05)
    handle = _PROCESS_HANDLES.get(pid)
    if handle is not None:
        try:
            handle.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass
    if _process_alive(pid) or _process_group_alive(ownership.process_group_id):
        raise ComfyUIRuntimeError("runtime_stop_failed", "ComfyUI Runtime did not stop before the timeout")


def stop_runtime(*, force: bool = False) -> RuntimeHealthSnapshot:
    manifest = _runtime_manifest()
    with _PROCESS_LOCK:
        state = _read_state()
        if not state.installed:
            raise ComfyUIRuntimeError("runtime_not_installed", "ComfyUI Runtime is not installed")
        process = _read_process()
        if process is None or (
            not _process_alive(process.ownership.pid)
            and not _process_group_alive(process.ownership.process_group_id)
        ):
            _write_process(None)
            state.status = "stopped"
            state.error = None
            state.checked_at = _iso()
            _write_state(state)
            return RuntimeHealthSnapshot(
                healthy=False,
                checked_at=state.checked_at,
                status="stopped",
                version=state.version,
                error={"code": "runtime_not_running", "message": "ComfyUI Runtime is already stopped"},
            )
        state.status = "stopping"
        _write_state(state)
        process.state = "stopping"
        process.updated_at = _iso()
        _write_process(process)
        _stop_owned_process(process, manifest, force=force)
        _PROCESS_HANDLES.pop(process.ownership.pid, None)
        shutil.rmtree(_runtime_data_root() / "user" / process.ownership.nonce, ignore_errors=True)
        _write_process(None)
        state.status = "stopped"
        state.error = None
        state.checked_at = _iso()
        _write_state(state)
        _append_log("runtime", f"stopped ComfyUI {manifest.version} force={force}")
        return RuntimeHealthSnapshot(
            healthy=False,
            checked_at=state.checked_at,
            status="stopped",
            version=manifest.version,
            custom_nodes_pristine=custom_node_tree_is_pristine(_source_root(manifest), manifest),
            identity_verified=True,
            error={"code": "runtime_not_running", "message": "ComfyUI Runtime is stopped"},
        )


def run_runtime_uninstall(
    task_id: str,
    *,
    progress: ProgressCallback = _default_progress,
    cancel: CancellationCheck = lambda: None,
    confirmation: RuntimeOperationSummary | None = None,
) -> None:
    manifest = _runtime_manifest()
    adapter, _support, _enabled = platform_adapter(manifest)
    with _MUTATION_LOCK:
        if confirmation is None or confirmation.operation != "uninstall":
            raise ComfyUIRuntimeError(
                "confirmation_invalid", "Uninstall requires a valid backend confirmation"
            )
        assert_runtime_operation_identity(confirmation)
        try:
            stop_runtime(force=False)
        except ComfyUIRuntimeError as exc:
            if exc.code not in {"runtime_not_running", "runtime_not_installed"}:
                raise
        cancel()
        final = _version_root(manifest)
        ownership = RUNTIME_VALIDATOR(final, manifest)
        transaction_id = uuid.uuid4().hex
        now = _iso()
        staging_relative = f"staging/{transaction_id}"
        journal = RuntimeInstallJournal(
            transaction_id=transaction_id,
            task_id=task_id,
            operation="uninstall",
            runtime_version=manifest.version,
            manifest_sha256=_manifest_sha256(),
            platform_adapter=adapter,
            staging_relative_path=staging_relative,
            final_relative_path=f"versions/{manifest.version}",
            archive_relative_path=f"{staging_relative}/unused.tar.gz",
            expected_archive_sha256=manifest.source.archive_sha256,
            managed_root_identity=ownership.managed_root_identity,
            created_at=now,
            updated_at=now,
        )
        _save_journal(journal)
        progress("preflight", 10, "正在确认受控运行进程已停止", None, None)
        try:
            cancel()
            _update_journal(journal, "rolling_back")
            progress("uninstalling_runtime", 55, "正在移除 HanClassStudio 管理的 Runtime", None, None)
            removed_record = _remove_owned_runtime_tree(final, manifest)
            _remove_recorded_managed_paths(removed_record)
            # Deliberately retain provider-models/comfyui for Phase 2C ownership separation.
            # Runtime input/output, logs, and unknown managed-root entries are retained
            # because they are not authorized by the installation ownership record.
            _write_process(None)
            _write_state(RuntimeStateRecord())
            _update_journal(journal, "state_committed")
            _update_journal(journal, "completed")
            progress("completed", 100, "ComfyUI 运行环境已卸载", None, None)
            _config_path(_STATE_FILE).unlink(missing_ok=True)
            _config_path(_JOURNAL_FILE).unlink(missing_ok=True)
        except (OSError, ComfyUIRuntimeError) as exc:
            _update_journal(journal, "failed", error_code="uninstall_failed")
            raise ComfyUIRuntimeError("uninstall_failed", "ComfyUI Runtime could not be uninstalled safely") from exc


def runtime_snapshot(*, recover: bool = True) -> RuntimeSnapshot:
    manifest = _runtime_manifest()
    adapter, support, enabled = platform_adapter(manifest)
    if recover:
        try:
            recover_installations()
        except ComfyUIRuntimeError:
            pass
    state = _read_state()
    invalid_process_record = False
    try:
        process = _read_process()
    except ComfyUIRuntimeError as exc:
        process = None
        invalid_process_record = True
        state.status = "repair_required"
        state.error = {"code": exc.code, "message": exc.message}
        _write_state(state)
    last_health: RuntimeHealthSnapshot | None = None
    modified = False
    if state.installed and not _source_contract_pristine(_version_root(manifest), manifest):
        modified = True
        state.status = "unsupported_modified"
        state.error = {"code": "runtime_modified", "message": "Controlled ComfyUI source or custom_nodes was modified"}
        _write_state(state)
    if process:
        if (
            not _process_alive(process.ownership.pid)
            and _process_group_alive(process.ownership.process_group_id)
        ):
            try:
                _stop_owned_process(process, manifest, force=True)
                _write_process(None)
                process = None
                state.status = "crashed"
                state.error = {
                    "code": "runtime_crashed",
                    "message": "The managed supervisor exited; its owned process group was reclaimed",
                }
                _write_state(state)
            except ComfyUIRuntimeError as exc:
                state.status = "repair_required"
                state.error = {"code": exc.code, "message": exc.message}
                _write_state(state)
        if process is None:
            pass
        elif not _process_alive(process.ownership.pid):
            state.status = "crashed"
            state.error = {"code": "runtime_crashed", "message": "The managed ComfyUI process exited unexpectedly"}
            _write_state(state)
        elif process.state == "running":
            identity_ok = _ownership_matches(process, manifest)
            if not identity_ok:
                state.status = "repair_required"
                state.error = {"code": "runtime_identity_mismatch", "message": "The managed process identity changed"}
                _write_state(state)
            elif state.status == "runtime_ready":
                last_health = RuntimeHealthSnapshot(
                    healthy=True,
                    checked_at=state.checked_at or process.updated_at,
                    status="runtime_ready",
                    version=manifest.version,
                    port=process.ownership.port,
                    core_api_available=True,
                    custom_nodes_pristine=True,
                    identity_verified=True,
                )
    if not enabled and not state.installed:
        status: RuntimeStatus = "incompatible"
    else:
        status = state.status
    runtime_ready = status == "runtime_ready" and bool(last_health and last_health.healthy)
    actions: list[RuntimeAction] = ["open_runtime_directory"]
    if invalid_process_record:
        actions = ["view_runtime_logs", "open_runtime_directory"]
    elif not state.installed:
        if enabled:
            actions = ["install_runtime", "view_runtime_logs", "open_runtime_directory"]
    elif status in {"starting", "runtime_ready"}:
        actions = ["stop_runtime", "force_stop_runtime", "check_runtime", "view_runtime_logs", "open_runtime_directory"]
    elif status == "stopping":
        actions = ["force_stop_runtime", "view_runtime_logs"]
    elif status in {"crashed", "degraded", "repair_required", "unsupported_modified", "failed"}:
        actions = [
            "start_runtime", "check_runtime", "repair_runtime", "uninstall_runtime",
            "view_runtime_logs", "open_runtime_directory",
        ]
    else:
        actions = [
            "start_runtime", "check_runtime", "repair_runtime", "uninstall_runtime",
            "view_runtime_logs", "open_runtime_directory",
        ]
    return RuntimeSnapshot(
        status=status,
        installed=state.installed,
        runtime_ready=runtime_ready,
        version=manifest.version,
        source_commit=manifest.source_commit,
        platform_adapter=adapter,
        platform_support=support,
        compatible=enabled,
        available_actions=actions,
        actual_port=process.ownership.port if process and _process_alive(process.ownership.pid) else None,
        estimated_download_bytes=manifest.source.archive_size,
        modified=modified,
        last_health=last_health,
        technical_error=state.error,
    )


def runtime_directory_contract() -> dict[str, str]:
    """Return an opaque backend action target, never a user-machine absolute path."""
    return {"action": "open_managed_runtime_directory", "runtime_id": "comfyui"}
