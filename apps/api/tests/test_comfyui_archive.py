from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path

import pytest

from hcs_api.comfyui_archive import (
    ComfyUIArchiveError,
    ComfyUIRuntimeManifest,
    extract_pinned_tool_archive,
    extract_tar_gz,
    inspect_tar_gz,
    load_runtime_manifest,
)
from hcs_api import comfyui_archive as archive_module
from hcs_api import comfyui_runtime as runtime_module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_tar(path: Path, entries: list[tuple[str, bytes | None, str]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            if kind == "dir":
                member.type = tarfile.DIRTYPE
                member.mode = 0o755
                archive.addfile(member)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = data.decode() if data else "target"
                archive.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = data.decode() if data else "target"
                archive.addfile(member)
            elif kind == "fifo":
                member.type = tarfile.FIFOTYPE
                archive.addfile(member)
            else:
                payload = data or b""
                member.size = len(payload)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(payload))


def _mini_manifest(archive: Path, entries: list[tuple[str, bytes | None, str]]) -> ComfyUIRuntimeManifest:
    manifest = load_runtime_manifest().model_copy(deep=True)
    files = {name.split("/", 1)[1]: data or b"" for name, data, kind in entries if kind == "file"}
    manifest.source.archive_size = archive.stat().st_size
    manifest.source.archive_sha256 = _sha(archive.read_bytes())
    manifest.critical_files = {
        name: _sha(files[name])
        for name in ("LICENSE", "requirements.txt", "pyproject.toml", "main.py", "comfy/cli_args.py", "comfyui_version.py")
        if name in files
    }
    manifest.custom_node_baseline = {
        name: _sha(data)
        for name, data in files.items()
        if name.startswith("custom_nodes/")
    }
    if "LICENSE" in manifest.critical_files:
        manifest.license.bundled_file_sha256 = manifest.critical_files["LICENSE"]
    if "requirements.txt" in manifest.critical_files:
        manifest.python.requirements_sha256 = manifest.critical_files["requirements.txt"]
    return manifest


def _valid_entries(root: str) -> list[tuple[str, bytes | None, str]]:
    files = {
        "LICENSE": b"GPL-3.0 test fixture",
        "requirements.txt": b"aiohttp==1\n",
        "pyproject.toml": b"[project]\nversion='test'\n",
        "main.py": b"print('fixture')\n",
        "comfy/cli_args.py": b"ARGS = []\n",
        "comfyui_version.py": b"__version__='test'\n",
        "custom_nodes/example_node.py.example": b"example\n",
        "custom_nodes/websocket_image_save.py": b"websocket\n",
    }
    directories = [root, f"{root}/comfy", f"{root}/custom_nodes"]
    return (
        [(item, None, "dir") for item in directories]
        + [(f"{root}/{name}", data, "file") for name, data in files.items()]
    )


def test_bundled_manifest_is_strict_commit_pinned_and_lock_verified() -> None:
    manifest = load_runtime_manifest()

    assert manifest.version == "0.28.0"
    assert manifest.source_commit == "700821e1364eaab0e8f21c538a2131719fec57bf"
    assert manifest.source.archive_url.endswith(manifest.source_commit)
    assert manifest.source.source_tree_sha256 == "9a0930b7b26cf02e9a6392d340309f35ce88f4506d365374c95cd1f98caaa5a6"
    assert manifest.license.spdx == "GPL-3.0-only"
    assert manifest.capability_boundary.runtime_only is True
    assert manifest.capability_boundary.downloads_models is False
    assert manifest.capability_boundary.generation_ready is False
    assert "--disable-all-custom-nodes" in manifest.launch.fixed_arguments
    assert "--disable-api-nodes" in manifest.launch.fixed_arguments
    assert manifest.python.toolchain_status == "ready"
    assert manifest.python.uv_artifact is not None
    assert manifest.python.python_runtime is not None
    assert manifest.python.wheelhouse is not None
    assert manifest.python.wheelhouse.package_count == 83
    assert manifest.python.wheelhouse.download_policy == "strict_allowlist"
    enabled = [item for item in manifest.platforms if item.install_enabled]
    assert [(item.operating_system, item.architecture, item.minimum_os_version) for item in enabled] == [
        ("macos", "arm64", "14.0")
    ]


def test_reviewed_wheel_lock_is_complete_allowlisted_and_license_bound() -> None:
    manifest = load_runtime_manifest()
    wheelhouse = manifest.python.wheelhouse
    assert wheelhouse is not None
    lock_path = archive_module.storage.ROOT_DIR / wheelhouse.artifact_lock_file
    lock = runtime_module._read_wheel_artifact_lock(lock_path)
    expected = runtime_module._expected_dependencies(
        archive_module.storage.ROOT_DIR / manifest.python.lock_file
    )
    actual = {
        re.sub(r"[-_.]+", "-", wheel.name).lower(): wheel.version
        for wheel in lock.wheels
    }

    assert actual == expected
    assert lock.package_count == len(lock.wheels) == 83
    assert lock.total_size == wheelhouse.size
    assert all(wheel.source_url.startswith(lock.source_allowlist[0]) for wheel in lock.wheels)
    assert all(wheel.license_expression and wheel.license_review == "approved_for_gpl3_runtime" for wheel in lock.wheels)
    assert all(
        (wheel.license_evidence == "pinned_upstream")
        == (wheel.license_source_url is not None and wheel.license_source_sha256 is not None)
        for wheel in lock.wheels
    )


def test_manifest_rejects_floating_source_and_unknown_fields(tmp_path: Path) -> None:
    raw = json.loads((Path(__file__).parents[3] / "providers/comfyui/runtime-manifest.v1.json").read_text())
    raw["source"]["archive_url"] = "https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/main"
    raw["unexpected"] = "remote command"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(ComfyUIArchiveError) as error:
        load_runtime_manifest(path)

    assert error.value.code == "invalid_manifest"


def test_safe_archive_extracts_only_verified_regular_tree(tmp_path: Path) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "source.tar.gz"
    entries = _valid_entries(root)
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)
    destination = tmp_path / "staging"

    inspection = extract_tar_gz(archive, destination, manifest)

    assert inspection.file_count == 8
    assert (destination / "main.py").read_bytes() == b"print('fixture')\n"
    assert not (tmp_path / "outside").exists()


def test_fixed_toolchain_archive_extracts_regular_files_and_skips_only_declared_aliases(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "toolchain.tar.gz"
    entries = [
        ("python", None, "dir"),
        ("python/bin", None, "dir"),
        ("python/bin/python3.11", b"controlled-python", "file"),
        ("python/bin/python", b"python3.11", "symlink"),
    ]
    _write_tar(archive, entries)
    destination = tmp_path / "toolchain"

    inspection = extract_pinned_tool_archive(
        archive,
        destination,
        archive_size=archive.stat().st_size,
        archive_sha256=_sha(archive.read_bytes()),
        archive_root="python",
        ignored_symlinks={"bin/python": "python3.11"},
        executable_paths={"bin/python3.11"},
    )

    assert inspection.file_count == 1
    assert (destination / "bin/python3.11").read_bytes() == b"controlled-python"
    assert not (destination / "bin/python").exists()
    assert not [item for item in tmp_path.rglob("*") if item.is_symlink()]


def test_fixed_toolchain_archive_rejects_unapproved_link_without_external_change(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "toolchain.tar.gz"
    entries = [
        ("python", None, "dir"),
        ("python/bin", None, "dir"),
        ("python/bin/python3.11", b"controlled-python", "file"),
        ("python/bin/python", b"unexpected", "symlink"),
    ]
    _write_tar(archive, entries)
    marker = tmp_path / "external-marker"
    marker.write_bytes(b"unchanged")

    with pytest.raises(ComfyUIArchiveError):
        extract_pinned_tool_archive(
            archive,
            tmp_path / "toolchain",
            archive_size=archive.stat().st_size,
            archive_sha256=_sha(archive.read_bytes()),
            archive_root="python",
            ignored_symlinks={"bin/python": "python3.11"},
            executable_paths={"bin/python3.11"},
        )

    assert marker.read_bytes() == b"unchanged"


def test_parent_directory_replacement_cannot_write_outside_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "source.tar.gz"
    entries = _valid_entries(root)
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)
    destination = tmp_path / "staging"
    displaced = tmp_path / "displaced-staging"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = archive_module.os.open
    swapped = False

    def replace_root_before_file_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "main.py" and dir_fd is not None and not swapped:
            swapped = True
            destination.rename(displaced)
            destination.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(archive_module.os, "open", replace_root_before_file_open)

    with pytest.raises(ComfyUIArchiveError) as error:
        extract_tar_gz(archive, destination, manifest)

    assert error.value.code == "unsafe_archive_path"
    assert swapped is True
    assert not (outside / "main.py").exists()
    assert list(outside.iterdir()) == []


def test_extraction_fails_closed_without_safe_dirfd_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "source.tar.gz"
    entries = _valid_entries(root)
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)
    monkeypatch.setattr(archive_module, "secure_dirfd_extraction_supported", lambda: False)

    with pytest.raises(ComfyUIArchiveError) as error:
        extract_tar_gz(archive, tmp_path / "staging", manifest)

    assert error.value.code == "safe_extraction_unavailable"


@pytest.mark.parametrize(
    ("extra_name", "kind", "expected_code"),
    [
        ("../outside", "file", "unsafe_archive_path"),
        ("/absolute", "file", "unsafe_archive_path"),
        ("C:/windows", "file", "unsafe_archive_path"),
        ("\\\\server\\share", "file", "unsafe_archive_path"),
        ("linked", "symlink", "archive_special_file"),
        ("hard-linked", "hardlink", "archive_special_file"),
        ("pipe", "fifo", "archive_special_file"),
        ("payload.zip", "file", "nested_archive_rejected"),
    ],
)
def test_archive_rejects_traversal_links_special_files_and_nesting(
    tmp_path: Path, extra_name: str, kind: str, expected_code: str
) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "unsafe.tar.gz"
    entries = _valid_entries(root)
    full_name = extra_name if extra_name.startswith(("/", "C:")) else f"{root}/{extra_name}"
    entries.append((full_name, b"target", kind))
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)

    with pytest.raises(ComfyUIArchiveError) as error:
        inspect_tar_gz(archive, manifest)

    assert error.value.code == expected_code


@pytest.mark.parametrize("names", [["Readme", "README"], ["caf\u00e9", "cafe\u0301"]])
def test_archive_rejects_portable_name_collisions_and_non_nfc_names(tmp_path: Path, names: list[str]) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "collision.tar.gz"
    entries = _valid_entries(root) + [(f"{root}/{name}", b"x", "file") for name in names]
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)

    with pytest.raises(ComfyUIArchiveError) as error:
        inspect_tar_gz(archive, manifest)

    assert error.value.code in {"archive_path_collision", "unsafe_archive_path"}


def test_archive_rejects_duplicate_member_and_expansion_limit(tmp_path: Path) -> None:
    root = load_runtime_manifest().source.archive_root
    duplicate_archive = tmp_path / "duplicate.tar.gz"
    duplicate_entries = _valid_entries(root) + [(f"{root}/main.py", b"other", "file")]
    _write_tar(duplicate_archive, duplicate_entries)
    duplicate_manifest = _mini_manifest(duplicate_archive, duplicate_entries)
    with pytest.raises(ComfyUIArchiveError) as duplicate_error:
        inspect_tar_gz(duplicate_archive, duplicate_manifest)
    assert duplicate_error.value.code == "archive_path_collision"

    large_archive = tmp_path / "large.tar.gz"
    large_entries = _valid_entries(root) + [(f"{root}/large.bin", b"x" * 128, "file")]
    _write_tar(large_archive, large_entries)
    large_manifest = _mini_manifest(large_archive, large_entries)
    large_manifest.archive_policy.max_total_file_bytes = 64
    with pytest.raises(ComfyUIArchiveError) as large_error:
        inspect_tar_gz(large_archive, large_manifest)
    assert large_error.value.code == "archive_expanded_size_limit"


def test_archive_checksum_and_expected_size_fail_closed(tmp_path: Path) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "source.tar.gz"
    entries = _valid_entries(root)
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)
    manifest.source.archive_sha256 = "0" * 64

    with pytest.raises(ComfyUIArchiveError) as error:
        inspect_tar_gz(archive, manifest)

    assert error.value.code == "checksum_mismatch"


def test_archive_enforces_entry_file_depth_and_compression_limits(tmp_path: Path) -> None:
    root = load_runtime_manifest().source.archive_root

    cases = [
        ("entries", [(f"{root}/extra-{index}", b"x", "file") for index in range(3)], "max_entries", 4, "archive_entry_limit"),
        ("file", [(f"{root}/oversized.bin", b"x" * 32, "file")], "max_file_bytes", 16, "archive_file_limit"),
        ("depth", [(f"{root}/a/b/c/d.txt", b"x", "file")], "max_depth", 2, "unsafe_archive_path"),
        ("ratio", [(f"{root}/compressible.bin", b"x" * 8192, "file")], "max_compression_ratio", 1, "archive_compression_ratio"),
    ]
    for name, extras, field, limit, expected_code in cases:
        archive = tmp_path / f"{name}.tar.gz"
        entries = _valid_entries(root) + extras
        _write_tar(archive, entries)
        manifest = _mini_manifest(archive, entries)
        setattr(manifest.archive_policy, field, limit)
        with pytest.raises(ComfyUIArchiveError) as error:
            inspect_tar_gz(archive, manifest)
        assert error.value.code == expected_code


def test_extraction_refuses_nonempty_destination(tmp_path: Path) -> None:
    root = load_runtime_manifest().source.archive_root
    archive = tmp_path / "source.tar.gz"
    entries = _valid_entries(root)
    _write_tar(archive, entries)
    manifest = _mini_manifest(archive, entries)
    destination = tmp_path / "staging"
    destination.mkdir()
    (destination / "foreign.txt").write_text("do not overwrite")

    with pytest.raises(ComfyUIArchiveError) as error:
        extract_tar_gz(archive, destination, manifest)

    assert error.value.code == "staging_conflict"
    assert (destination / "foreign.txt").read_text() == "do not overwrite"
