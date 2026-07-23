"""Strict archive boundary for the pinned ComfyUI runtime source package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import storage


_SHA256 = re.compile(r"[0-9a-f]{64}")
_NESTED_ARCHIVE_SUFFIXES = (
    ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
)
_HAS_SECURE_DIRFD = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)


class ComfyUIArchiveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeSource(_StrictModel):
    project_url: str
    release_url: str
    archive_url: str
    archive_sha256: str
    source_tree_sha256: str
    archive_size: int = Field(gt=0)
    archive_type: Literal["tar.gz"]
    archive_root: str

    @field_validator("archive_sha256", "source_tree_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("source identities must be lowercase SHA-256")
        return value


class RuntimeLicense(_StrictModel):
    spdx: Literal["GPL-3.0-only"]
    name: str
    url: str
    bundled_file: str
    bundled_file_sha256: str
    redistribution_review: Literal["approved_with_gpl_obligations"]


class ArchivePolicy(_StrictModel):
    max_compressed_bytes: int = Field(gt=0)
    max_entries: int = Field(gt=0)
    max_total_file_bytes: int = Field(gt=0)
    max_file_bytes: int = Field(gt=0)
    max_path_bytes: int = Field(gt=0)
    max_depth: int = Field(gt=0)
    max_compression_ratio: int = Field(gt=0)
    reject_links: Literal[True]
    reject_special_files: Literal[True]
    reject_nested_archives: Literal[True]
    require_nfc_names: Literal[True]
    reject_casefold_collisions: Literal[True]


class PythonEnvironment(_StrictModel):
    implementation: Literal["cpython"]
    version: str
    environment_manager: Literal["uv"]
    environment_manager_version: str
    lock_file: str
    lock_sha256: str
    requirements_sha256: str
    toolchain_status: Literal["ready", "unavailable"]
    toolchain_unavailable_reason: str | None = None
    uv_artifact: ToolBinaryArtifact | None = None
    python_runtime: PythonRuntimeArtifact | None = None
    wheelhouse: WheelhouseArtifact | None = None

    @field_validator("version", "environment_manager_version")
    @classmethod
    def _semantic_version(cls, value: str) -> str:
        if not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError("Python environment versions must be exact three-part versions")
        return value

    @model_validator(mode="after")
    def _fixed_toolchain(self) -> "PythonEnvironment":
        artifacts = (self.uv_artifact, self.python_runtime, self.wheelhouse)
        if self.toolchain_status == "ready":
            if any(item is None for item in artifacts) or self.toolchain_unavailable_reason is not None:
                raise ValueError("ready Python toolchains require every fixed artifact")
        elif any(item is not None for item in artifacts) or not self.toolchain_unavailable_reason:
            raise ValueError("unavailable Python toolchains must fail closed without partial artifacts")
        return self


class _PinnedArtifact(_StrictModel):
    relative_path: str
    source_url: str
    size: int = Field(gt=0)
    sha256: str
    operating_system: Literal["macos"]
    architecture: Literal["arm64"]

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        _validated_relative_name(value, max_bytes=512, max_depth=12)
        return value

    @field_validator("sha256")
    @classmethod
    def _artifact_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("toolchain identities must be lowercase SHA-256")
        return value

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        if not value.startswith("https://") or any(character.isspace() for character in value):
            raise ValueError("toolchain artifact source must be an exact HTTPS URL")
        return value


class ToolBinaryArtifact(_PinnedArtifact):
    version: str

    @field_validator("version")
    @classmethod
    def _tool_version(cls, value: str) -> str:
        if not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError("tool version must be exact")
        return value


class PythonRuntimeArtifact(_PinnedArtifact):
    implementation: Literal["cpython"]
    version: str
    executable_relative_path: str
    tree_sha256: str

    @field_validator("version")
    @classmethod
    def _python_version(cls, value: str) -> str:
        if not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError("Python version must be exact")
        return value

    @field_validator("executable_relative_path")
    @classmethod
    def _executable_path(cls, value: str) -> str:
        _validated_relative_name(value, max_bytes=256, max_depth=8)
        return value

    @field_validator("tree_sha256")
    @classmethod
    def _tree_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("Python tree identity must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def _tree_matches_artifact(self) -> "PythonRuntimeArtifact":
        if self.tree_sha256 != self.sha256:
            raise ValueError("bundled Python artifact and tree identities disagree")
        return self


class WheelhouseArtifact(_PinnedArtifact):
    artifact_lock_file: str
    artifact_lock_sha256: str
    wheel_only: Literal[True]
    allow_sdist: Literal[False]
    allow_editable: Literal[False]
    allow_build_backend: Literal[False]
    allow_dependency_resolution: Literal[False]

    @field_validator("artifact_lock_file")
    @classmethod
    def _artifact_lock_file(cls, value: str) -> str:
        _validated_relative_name(value, max_bytes=512, max_depth=12)
        return value

    @field_validator("artifact_lock_sha256")
    @classmethod
    def _artifact_lock_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("wheel artifact lock identity must be lowercase SHA-256")
        return value


class RuntimeLaunch(_StrictModel):
    entrypoint: Literal["main.py"]
    listen_host: Literal["127.0.0.1"]
    port_min: int = Field(ge=1024, le=65535)
    port_max: int = Field(ge=1024, le=65535)
    fixed_arguments: list[str]
    health_path: Literal["/system_stats"]
    startup_timeout_seconds: int = Field(ge=5, le=600)
    shutdown_timeout_seconds: int = Field(ge=1, le=60)


class RuntimePlatform(_StrictModel):
    operating_system: Literal["macos", "windows", "linux"]
    architecture: Literal["arm64", "x86_64"]
    adapter: str
    support: Literal["experimental", "contract_only"]
    install_enabled: bool


class CapabilityBoundary(_StrictModel):
    runtime_only: Literal[True]
    downloads_models: Literal[False]
    includes_workflows: Literal[False]
    allows_custom_nodes: Literal[False]
    generation_ready: Literal[False]


class ComfyUIRuntimeManifest(_StrictModel):
    schema_: Literal["hanclassstudio.comfyui_runtime_manifest.v1"] = Field(alias="schema")
    package_id: Literal["hcs.comfyui-runtime"]
    runtime_id: Literal["comfyui"]
    version: str
    release_tag: str
    source_commit: str
    publisher: str
    source: RuntimeSource
    license: RuntimeLicense
    archive_policy: ArchivePolicy
    critical_files: dict[str, str]
    custom_node_baseline: dict[str, str]
    python: PythonEnvironment
    launch: RuntimeLaunch
    platforms: list[RuntimePlatform]
    capability_boundary: CapabilityBoundary

    @field_validator("source_commit")
    @classmethod
    def _commit(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("source_commit must be a full commit SHA")
        return value

    @field_validator("critical_files", "custom_node_baseline")
    @classmethod
    def _file_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not _SHA256.fullmatch(digest) for digest in value.values()):
            raise ValueError("file identities must be non-empty lowercase SHA-256 mappings")
        for name in value:
            _validated_relative_name(name, max_bytes=512, max_depth=12)
        return value

    @model_validator(mode="after")
    def _fixed_contract(self) -> "ComfyUIRuntimeManifest":
        if self.release_tag != f"v{self.version}":
            raise ValueError("release tag and runtime version differ")
        if self.source.archive_root != f"ComfyUI-{self.source_commit}":
            raise ValueError("archive root is not bound to source commit")
        if self.source_commit not in self.source.archive_url:
            raise ValueError("archive URL is not commit pinned")
        if self.source.archive_size > self.archive_policy.max_compressed_bytes:
            raise ValueError("expected archive exceeds archive policy")
        if self.launch.port_min > self.launch.port_max:
            raise ValueError("runtime port range is invalid")
        if self.launch.fixed_arguments != [
            "--listen", "127.0.0.1", "--disable-auto-launch", "--disable-all-custom-nodes",
            "--disable-api-nodes", "--disable-metadata",
        ]:
            raise ValueError("runtime launch arguments weakened the security boundary")
        enabled = [item for item in self.platforms if item.install_enabled]
        enabled_platforms = [(item.operating_system, item.architecture) for item in enabled]
        if enabled_platforms not in ([], [("macos", "arm64")]):
            raise ValueError("only the reviewed macOS Apple Silicon adapter may install")
        if enabled and self.python.toolchain_status != "ready":
            raise ValueError("platform installation cannot be enabled without a fixed toolchain")
        if self.license.bundled_file not in self.critical_files:
            raise ValueError("bundled license is not covered by critical file identity")
        if self.critical_files[self.license.bundled_file] != self.license.bundled_file_sha256:
            raise ValueError("bundled license hashes disagree")
        if self.critical_files.get("requirements.txt") != self.python.requirements_sha256:
            raise ValueError("requirements hashes disagree")
        return self


class ArchiveMember(_StrictModel):
    archive_name: str
    relative_name: str
    kind: Literal["directory", "file"]
    size: int = Field(ge=0)


class ArchiveInspection(_StrictModel):
    members: list[ArchiveMember]
    file_count: int
    directory_count: int
    total_file_bytes: int


def manifest_path() -> Path:
    return storage.ROOT_DIR / "providers" / "comfyui" / "runtime-manifest.v1.json"


def load_runtime_manifest(path: Path | None = None) -> ComfyUIRuntimeManifest:
    target = path or manifest_path()
    try:
        if target.stat().st_size > 256 * 1024:
            raise ComfyUIArchiveError("invalid_manifest", "ComfyUI runtime manifest exceeds its size limit")
        payload = json.loads(target.read_text(encoding="utf-8"))
        manifest = ComfyUIRuntimeManifest.model_validate(payload)
    except ComfyUIArchiveError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ComfyUIArchiveError("invalid_manifest", "ComfyUI runtime manifest is invalid") from exc
    lock_path = storage.ROOT_DIR / manifest.python.lock_file
    if not lock_path.is_file() or sha256_file(lock_path) != manifest.python.lock_sha256:
        raise ComfyUIArchiveError("dependency_lock_mismatch", "ComfyUI dependency lock cannot be verified")
    if manifest.python.toolchain_status == "ready":
        wheelhouse = manifest.python.wheelhouse
        if wheelhouse is None:
            raise ComfyUIArchiveError("invalid_manifest", "ComfyUI fixed wheelhouse is missing")
        artifact_lock_path = storage.ROOT_DIR / wheelhouse.artifact_lock_file
        if (
            not artifact_lock_path.is_file()
            or sha256_file(artifact_lock_path) != wheelhouse.artifact_lock_sha256
        ):
            raise ComfyUIArchiveError(
                "dependency_lock_mismatch", "ComfyUI wheel artifact lock cannot be verified"
            )
    return manifest


def sha256_file(path: Path, *, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    consumed = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            consumed += len(chunk)
            if max_bytes is not None and consumed > max_bytes:
                raise ComfyUIArchiveError("unsafe_archive", "Archive exceeds its compressed size limit")
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive_file(path: Path, manifest: ComfyUIRuntimeManifest) -> None:
    try:
        archive_stat = path.stat()
    except OSError as exc:
        raise ComfyUIArchiveError("download_failed", "Downloaded ComfyUI archive is unavailable") from exc
    if not stat.S_ISREG(archive_stat.st_mode):
        raise ComfyUIArchiveError("unsafe_archive", "Downloaded ComfyUI archive is not a regular file")
    if archive_stat.st_size != manifest.source.archive_size:
        raise ComfyUIArchiveError("archive_size_mismatch", "Downloaded ComfyUI archive size differs from the manifest")
    digest = sha256_file(path, max_bytes=manifest.archive_policy.max_compressed_bytes)
    if digest != manifest.source.archive_sha256:
        raise ComfyUIArchiveError("checksum_mismatch", "Downloaded ComfyUI archive SHA-256 differs from the manifest")


def _validated_relative_name(name: str, *, max_bytes: int, max_depth: int) -> PurePosixPath:
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive contains an unsafe path")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path contains control characters")
    if unicodedata.normalize("NFC", name) != name:
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path is not Unicode NFC normalized")
    if len(name.encode("utf-8")) > max_bytes:
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path exceeds its length limit")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path contains an unsafe segment")
    if re.fullmatch(r"[A-Za-z]:.*", raw_parts[0]):
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path contains a Windows drive prefix")
    path = PurePosixPath(*raw_parts)
    if len(path.parts) > max_depth:
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive path exceeds its depth limit")
    return path


def inspect_tar_gz(path: Path, manifest: ComfyUIRuntimeManifest) -> ArchiveInspection:
    verify_archive_file(path, manifest)
    policy = manifest.archive_policy
    members: list[ArchiveMember] = []
    exact_names: set[str] = set()
    portable_names: set[str] = set()
    total_bytes = 0
    file_count = 0
    directory_count = 0
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            raw_members = archive.getmembers()
            if len(raw_members) > policy.max_entries:
                raise ComfyUIArchiveError("archive_entry_limit", "ComfyUI archive contains too many entries")
            for member in raw_members:
                raw_name = member.name[:-1] if member.name.endswith("/") else member.name
                full_name = _validated_relative_name(
                    raw_name,
                    max_bytes=policy.max_path_bytes,
                    max_depth=policy.max_depth + 1,
                )
                if full_name.parts[0] != manifest.source.archive_root:
                    raise ComfyUIArchiveError("archive_root_mismatch", "ComfyUI archive has an unexpected root directory")
                relative_parts = full_name.parts[1:]
                relative_name = "/".join(relative_parts)
                if relative_name:
                    _validated_relative_name(
                        relative_name,
                        max_bytes=policy.max_path_bytes,
                        max_depth=policy.max_depth,
                    )
                exact = full_name.as_posix()
                portable = unicodedata.normalize("NFKC", exact).casefold()
                if exact in exact_names or portable in portable_names:
                    raise ComfyUIArchiveError("archive_path_collision", "ComfyUI archive contains colliding paths")
                exact_names.add(exact)
                portable_names.add(portable)
                if member.isdir():
                    kind: Literal["directory", "file"] = "directory"
                    directory_count += 1
                elif member.isfile():
                    kind = "file"
                    if member.size < 0 or member.size > policy.max_file_bytes:
                        raise ComfyUIArchiveError("archive_file_limit", "ComfyUI archive contains an oversized file")
                    total_bytes += member.size
                    file_count += 1
                    if total_bytes > policy.max_total_file_bytes:
                        raise ComfyUIArchiveError("archive_expanded_size_limit", "ComfyUI archive exceeds its expanded size limit")
                    lower_name = relative_name.casefold()
                    if lower_name.endswith(_NESTED_ARCHIVE_SUFFIXES):
                        raise ComfyUIArchiveError("nested_archive_rejected", "ComfyUI archive contains a nested archive")
                else:
                    raise ComfyUIArchiveError("archive_special_file", "ComfyUI archive contains a link or special file")
                members.append(ArchiveMember(
                    archive_name=member.name,
                    relative_name=relative_name,
                    kind=kind,
                    size=member.size if kind == "file" else 0,
                ))
    except ComfyUIArchiveError:
        raise
    except (OSError, tarfile.TarError, UnicodeError) as exc:
        raise ComfyUIArchiveError("invalid_archive", "ComfyUI archive cannot be parsed safely") from exc
    if not members or not any(item.relative_name == "" and item.kind == "directory" for item in members):
        raise ComfyUIArchiveError("archive_root_mismatch", "ComfyUI archive root directory is missing")
    if total_bytes > manifest.source.archive_size * policy.max_compression_ratio:
        raise ComfyUIArchiveError("archive_compression_ratio", "ComfyUI archive exceeds its compression-ratio limit")
    return ArchiveInspection(
        members=members,
        file_count=file_count,
        directory_count=directory_count,
        total_file_bytes=total_bytes,
    )


def secure_dirfd_extraction_supported() -> bool:
    return _HAS_SECURE_DIRFD


def _directory_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_verified_directory(path: Path) -> tuple[int, tuple[int, int]]:
    if not secure_dirfd_extraction_supported():
        raise ComfyUIArchiveError(
            "safe_extraction_unavailable",
            "This platform cannot provide symlink-safe directory-relative extraction",
        )
    try:
        before = path.lstat()
        if not stat.S_ISDIR(before.st_mode):
            raise ComfyUIArchiveError("staging_conflict", "ComfyUI staging directory must be a real directory")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        after = os.fstat(fd)
        if _directory_identity(before) != _directory_identity(after):
            os.close(fd)
            raise ComfyUIArchiveError("unsafe_archive_path", "ComfyUI staging directory identity changed")
        os.fchmod(fd, 0o700)
        return fd, _directory_identity(after)
    except ComfyUIArchiveError:
        raise
    except OSError as exc:
        raise ComfyUIArchiveError("unsafe_archive_path", "ComfyUI staging directory cannot be opened safely") from exc


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            raise ComfyUIArchiveError("unsafe_archive_path", "Archive parent is not a real directory")
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        after = os.fstat(fd)
        if _directory_identity(before) != _directory_identity(after):
            os.close(fd)
            raise ComfyUIArchiveError("unsafe_archive_path", "Archive parent directory identity changed")
        os.fchmod(fd, 0o700)
        return fd
    except ComfyUIArchiveError:
        raise
    except OSError as exc:
        raise ComfyUIArchiveError("unsafe_archive_path", "Archive parent directory cannot be opened safely") from exc


@contextmanager
def _open_directory_chain(root_fd: int, parts: tuple[str, ...]) -> Iterator[int]:
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_child_directory(current, part)
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


def _assert_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    try:
        current = path.lstat()
    except OSError as exc:
        raise ComfyUIArchiveError("unsafe_archive_path", "ComfyUI staging directory disappeared") from exc
    if not stat.S_ISDIR(current.st_mode) or _directory_identity(current) != expected:
        raise ComfyUIArchiveError("unsafe_archive_path", "ComfyUI staging directory identity changed")


def extract_tar_gz(path: Path, destination: Path, manifest: ComfyUIRuntimeManifest) -> ArchiveInspection:
    """Extract only pre-inspected regular files/directories into a private empty directory."""
    inspection = inspect_tar_gz(path, manifest)
    if destination.exists():
        try:
            destination_info = destination.lstat()
        except OSError as exc:
            raise ComfyUIArchiveError("staging_conflict", "ComfyUI staging directory cannot be inspected") from exc
        if not stat.S_ISDIR(destination_info.st_mode) or any(destination.iterdir()):
            raise ComfyUIArchiveError("staging_conflict", "ComfyUI staging directory must be empty")
    else:
        destination.mkdir(parents=True, mode=0o700)
    root_fd, root_identity = _open_verified_directory(destination)
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            raw_by_name = {member.name: member for member in archive.getmembers()}
            for expected in inspection.members:
                if not expected.relative_name:
                    continue
                relative = PurePosixPath(expected.relative_name)
                if expected.kind == "directory":
                    with _open_directory_chain(root_fd, relative.parts):
                        pass
                    continue
                source = archive.extractfile(raw_by_name[expected.archive_name])
                if source is None:
                    raise ComfyUIArchiveError("invalid_archive", "ComfyUI archive file content is missing")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= os.O_NOFOLLOW
                written = 0
                with _open_directory_chain(root_fd, relative.parts[:-1]) as parent_fd:
                    fd = os.open(relative.name, flags, 0o600, dir_fd=parent_fd)
                    try:
                        with os.fdopen(fd, "wb", closefd=False) as output:
                            while chunk := source.read(1024 * 1024):
                                written += len(chunk)
                                if written > expected.size:
                                    raise ComfyUIArchiveError("archive_size_changed", "Archive file exceeded its inspected size")
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                    finally:
                        os.close(fd)
                if written != expected.size:
                    raise ComfyUIArchiveError("archive_size_changed", "Archive file size changed during extraction")
        _assert_directory_identity(destination, root_identity)
        verify_extracted_tree(destination, inspection, manifest)
        verify_archive_file(path, manifest)
        return inspection
    except ComfyUIArchiveError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ComfyUIArchiveError("archive_extraction_failed", "ComfyUI archive extraction failed") from exc
    finally:
        os.close(root_fd)


def verify_extracted_tree(
    root: Path,
    inspection: ArchiveInspection,
    manifest: ComfyUIRuntimeManifest,
) -> None:
    expected_files = {item.relative_name: item.size for item in inspection.members if item.kind == "file"}
    expected_dirs = {item.relative_name for item in inspection.members if item.kind == "directory" and item.relative_name}
    actual_files: dict[str, int] = {}
    actual_dirs: set[str] = set()
    portable: set[str] = set()
    for current_root, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        for name in [*directory_names, *file_names]:
            target = current / name
            relative = target.relative_to(root).as_posix()
            info = target.lstat()
            identity = unicodedata.normalize("NFKC", relative).casefold()
            if identity in portable:
                raise ComfyUIArchiveError("archive_path_collision", "Extracted ComfyUI tree contains colliding paths")
            portable.add(identity)
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ComfyUIArchiveError("archive_special_file", "Extracted ComfyUI tree contains a link or special file")
            if stat.S_ISDIR(info.st_mode):
                actual_dirs.add(relative)
            else:
                actual_files[relative] = info.st_size
    if actual_files != expected_files or actual_dirs != expected_dirs:
        raise ComfyUIArchiveError("archive_tree_mismatch", "Extracted ComfyUI tree differs from the inspected archive")
    for relative, expected_hash in manifest.critical_files.items():
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file() or sha256_file(target) != expected_hash:
            raise ComfyUIArchiveError("critical_file_mismatch", "ComfyUI critical source file cannot be verified")
    for relative, expected_hash in manifest.custom_node_baseline.items():
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file() or sha256_file(target) != expected_hash:
            raise ComfyUIArchiveError("custom_node_baseline_mismatch", "ComfyUI custom-node baseline cannot be verified")


def custom_node_tree_is_pristine(root: Path, manifest: ComfyUIRuntimeManifest) -> bool:
    base = root / "custom_nodes"
    actual: dict[str, str] = {}
    try:
        for current_root, directory_names, file_names in os.walk(base, topdown=True, followlinks=False):
            current = Path(current_root)
            for directory_name in directory_names:
                if (current / directory_name).is_symlink():
                    return False
            for file_name in file_names:
                target = current / file_name
                if target.is_symlink() or not target.is_file():
                    return False
                relative = target.relative_to(root).as_posix()
                actual[relative] = sha256_file(target)
    except OSError:
        return False
    return actual == manifest.custom_node_baseline
