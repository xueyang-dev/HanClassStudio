from __future__ import annotations

import hashlib
import io
import os
import signal
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

import hcs_api.comfyui_runtime as runtime
import hcs_api.storage as storage
from hcs_api.comfyui_archive import (
    ComfyUIRuntimeManifest,
    load_runtime_manifest,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _isolate(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", root)
    monkeypatch.setattr(storage, "PROJECTS_DIR", root / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", root / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", root / "config/provider_settings.json")
    runtime._PROCESS_HANDLES.clear()
    runtime._WORKER_HANDLES.clear()
    runtime._LOG_THREADS.clear()
    runtime._DESTRUCTIVE_CONFIRMATIONS.clear()


def _write_archive(path: Path, manifest: ComfyUIRuntimeManifest) -> dict[str, bytes]:
    root = manifest.source.archive_root
    files = {
        "LICENSE": b"GPL test fixture",
        "requirements.txt": b"fixture==1\n",
        "pyproject.toml": b"[project]\nversion='test'\n",
        "main.py": b"print('fixture')\n",
        "comfy/cli_args.py": b"ARGS=[]\n",
        "comfyui_version.py": b"__version__='test'\n",
        "custom_nodes/example_node.py.example": b"example\n",
        "custom_nodes/websocket_image_save.py": b"websocket\n",
    }
    with tarfile.open(path, "w:gz") as archive:
        for directory in (root, f"{root}/comfy", f"{root}/custom_nodes"):
            item = tarfile.TarInfo(directory)
            item.type = tarfile.DIRTYPE
            archive.addfile(item)
        for name, data in files.items():
            item = tarfile.TarInfo(f"{root}/{name}")
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return files


def _fixture_manifest(tmp_path: Path) -> tuple[ComfyUIRuntimeManifest, Path]:
    manifest = load_runtime_manifest().model_copy(deep=True)
    archive = tmp_path / "fixture.tar.gz"
    files = _write_archive(archive, manifest)
    manifest.source.archive_size = archive.stat().st_size
    manifest.source.archive_sha256 = _sha(archive.read_bytes())
    manifest.critical_files = {
        name: _sha(files[name])
        for name in ("LICENSE", "requirements.txt", "pyproject.toml", "main.py", "comfy/cli_args.py", "comfyui_version.py")
    }
    manifest.custom_node_baseline = {
        name: _sha(data) for name, data in files.items() if name.startswith("custom_nodes/")
    }
    manifest.license.bundled_file_sha256 = manifest.critical_files["LICENSE"]
    manifest.python.requirements_sha256 = manifest.critical_files["requirements.txt"]
    fingerprint_root = tmp_path / "source-fingerprint"
    for name, data in files.items():
        target = fingerprint_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest.source.source_tree_sha256 = runtime.source_tree_fingerprint(fingerprint_root)
    shutil.rmtree(fingerprint_root)
    return manifest, archive


def _install_fakes(tmp_path: Path, monkeypatch) -> tuple[ComfyUIRuntimeManifest, Path]:
    manifest, archive = _fixture_manifest(tmp_path)
    monkeypatch.setattr(runtime, "load_runtime_manifest", lambda: manifest)
    monkeypatch.setattr(runtime, "platform_adapter", lambda _manifest: ("test_adapter", "experimental", True))
    fake_toolchain = runtime.VerifiedPythonToolchain(
            uv=tmp_path / "toolchain/uv",
            python=tmp_path / "toolchain/python",
            wheelhouse=tmp_path / "toolchain/wheels",
            identity_sha256=runtime._toolchain_contract_identity(manifest),
    )
    monkeypatch.setattr(runtime, "TOOLCHAIN_PREPARER", lambda _root, _manifest, _cancel: fake_toolchain)
    monkeypatch.setattr(runtime, "verify_python_toolchain", lambda _manifest, _root: fake_toolchain)

    def download(destination, _manifest, progress, cancel):
        cancel()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        progress(archive.stat().st_size, archive.stat().st_size)

    def environment_builder(environment, _manifest, cancel):
        cancel()
        python = runtime._environment_python(environment)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"controlled-python-fixture")
        return "f" * 64

    def validator(version_root, _manifest):
        return runtime.RuntimeInstallationRecord.model_validate_json(
            (version_root / "installation.json").read_text(encoding="utf-8")
        )

    monkeypatch.setattr(runtime, "ARCHIVE_DOWNLOADER", download)
    monkeypatch.setattr(runtime, "ENVIRONMENT_BUILDER", environment_builder)
    monkeypatch.setattr(runtime, "RUNTIME_VALIDATOR", validator)
    return manifest, archive


def _confirmed_operation(operation: str) -> runtime.RuntimeOperationSummary:
    prepared = runtime.prepare_runtime_operation(operation)
    return runtime.consume_runtime_operation_confirmation(
        operation,
        prepared.confirmation_token,
        prepared.summary.installation_identity,
    )


def test_install_uses_durable_journal_atomic_publish_and_runtime_only_boundary(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, archive = _install_fakes(tmp_path, monkeypatch)
    phases: list[str] = []

    runtime.run_runtime_install(
        "task-install",
        progress=lambda phase, _percent, _message, _current, _total: phases.append(phase),
    )

    final = runtime._version_root(manifest)
    assert (final / "source/main.py").is_file()
    assert (final / "environment/bin/python3.11").read_bytes() == b"controlled-python-fixture"
    assert not (runtime._managed_root() / "staging").exists() or not any((runtime._managed_root() / "staging").iterdir())
    state = runtime._read_state()
    assert state.installed is True
    assert state.status == "stopped"
    assert runtime._models_root().exists() is False
    journal = next(iter(runtime._journals().values()))
    assert journal["phase"] == "completed"
    assert journal["expected_archive_sha256"] == _sha(archive.read_bytes())
    assert "installing_dependencies" in phases
    snapshot = runtime.runtime_snapshot()
    assert snapshot.installed is True
    assert snapshot.runtime_ready is False
    assert snapshot.generation_ready is False
    assert snapshot.no_model_message == "运行环境可用，但尚未安装图片模型。"
    assert "start_runtime" in snapshot.available_actions


def test_install_cancel_cleans_staging_and_never_marks_installed(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, archive = _fixture_manifest(tmp_path)
    monkeypatch.setattr(runtime, "load_runtime_manifest", lambda: manifest)
    monkeypatch.setattr(runtime, "platform_adapter", lambda _manifest: ("test_adapter", "experimental", True))
    cancelled = False

    def cancel() -> None:
        if cancelled:
            raise runtime.ComfyUIRuntimeError("cancelled", "cancelled")

    def download(destination, _manifest, progress, cancel_check):
        nonlocal cancelled
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read_bytes()[:32])
        progress(32, archive.stat().st_size)
        cancelled = True
        cancel_check()

    monkeypatch.setattr(runtime, "ARCHIVE_DOWNLOADER", download)
    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.run_runtime_install("task-cancel", cancel=cancel)

    assert error.value.code == "cancelled"
    assert runtime._read_state().installed is False
    assert not runtime._version_root(manifest).exists()
    assert not (runtime._managed_root() / "staging").exists() or not any((runtime._managed_root() / "staging").iterdir())
    assert next(iter(runtime._journals().values()))["phase"] == "cancelled"


def test_recovery_finishes_published_runtime_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-base")
    state_path = runtime._config_path(runtime._STATE_FILE)
    state_path.unlink()
    raw = runtime._journals()
    transaction_id, journal = next(iter(raw.items()))
    journal["phase"] = "runtime_published"
    raw[transaction_id] = journal
    runtime._atomic_json(runtime._config_path(runtime._JOURNAL_FILE), raw)

    first = runtime.recover_installations()
    second = runtime.recover_installations()

    assert first == [transaction_id]
    assert second == []
    assert runtime._read_state().installed is True
    assert runtime._journals()[transaction_id]["phase"] == "completed"


def test_runtime_tree_rejects_unlisted_source_even_if_install_record_is_rewritten(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    final = runtime._version_root(manifest)
    (final / "source/unlisted.py").write_text("unexpected = True\n", encoding="utf-8")

    with pytest.raises(runtime.ComfyUIRuntimeError) as changed:
        runtime.validate_runtime_tree(final, manifest)
    assert changed.value.code == "runtime_modified"

    record = runtime.RuntimeInstallationRecord.model_validate_json(
        (final / "installation.json").read_text(encoding="utf-8")
    )
    record.source_tree_sha256 = runtime.source_tree_fingerprint(final / "source")
    runtime._write_installation_record(final / "installation.json", record)
    with pytest.raises(runtime.ComfyUIRuntimeError) as rewritten:
        runtime.validate_runtime_tree(final, manifest)
    assert rewritten.value.code == "runtime_validation_failed"


def test_recovery_restores_backup_from_publish_crash(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-base")
    final = runtime._version_root(manifest)
    backup = runtime._managed_root() / f"backups/{manifest.version}-interrupted"
    backup.parent.mkdir(parents=True, exist_ok=True)
    os.replace(final, backup)
    ownership = runtime._read_owned_installation_record(backup)[0]
    now = runtime._iso()
    journal = runtime.RuntimeInstallJournal(
        transaction_id="interrupted",
        task_id="task-interrupted",
        operation="repair",
        runtime_version=manifest.version,
        manifest_sha256=runtime._manifest_sha256(),
        platform_adapter="test_adapter",
        phase="publish_prepared",
        staging_relative_path="staging/interrupted",
        final_relative_path=f"versions/{manifest.version}",
        backup_relative_path=f"backups/{manifest.version}-interrupted",
        archive_relative_path="staging/interrupted/source.tar.gz",
        expected_archive_sha256=manifest.source.archive_sha256,
        managed_root_identity=ownership.managed_root_identity,
        created_at=now,
        updated_at=now,
    )
    runtime._save_journal(journal)

    runtime.recover_installations()
    runtime.recover_installations()

    assert final.is_dir()
    assert not backup.exists()
    assert runtime._journals()["interrupted"]["phase"] == "rolled_back"


def test_uninstall_removes_only_managed_runtime_and_preserves_model_boundary(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    model = runtime._models_root() / "future-model.safetensors"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"future-owned-model")
    project_asset = storage.RUNTIME_DIR / "projects/lesson/assets/image.png"
    project_asset.parent.mkdir(parents=True)
    project_asset.write_bytes(b"asset")

    runtime.run_runtime_uninstall(
        "task-uninstall", confirmation=_confirmed_operation("uninstall")
    )

    assert not runtime._version_root(manifest).exists()
    assert model.read_bytes() == b"future-owned-model"
    assert project_asset.read_bytes() == b"asset"
    assert runtime._read_state().installed is False
    assert runtime._managed_root().is_dir()
    assert runtime._logs_root().is_dir()
    assert not runtime._config_path(runtime._JOURNAL_FILE).exists()


def test_destructive_confirmation_is_required_one_time_and_identity_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    version = runtime._version_root(manifest)

    with pytest.raises(runtime.ComfyUIRuntimeError) as missing:
        runtime.run_runtime_uninstall("task-uninstall")
    assert missing.value.code == "confirmation_invalid"
    assert version.exists()

    prepared = runtime.prepare_runtime_operation("uninstall")
    confirmed = runtime.consume_runtime_operation_confirmation(
        "uninstall",
        prepared.confirmation_token,
        prepared.summary.installation_identity,
    )
    assert confirmed == prepared.summary
    with pytest.raises(runtime.ComfyUIRuntimeError) as replayed:
        runtime.consume_runtime_operation_confirmation(
            "uninstall",
            prepared.confirmation_token,
            prepared.summary.installation_identity,
        )
    assert replayed.value.code == "confirmation_invalid"
    assert version.exists()


def test_destructive_confirmation_expires_or_becomes_stale_without_mutating_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    version = runtime._version_root(manifest)

    expired = runtime.prepare_runtime_operation("uninstall")
    expired_key = hashlib.sha256(expired.confirmation_token.encode()).hexdigest()
    runtime._DESTRUCTIVE_CONFIRMATIONS[expired_key].expires_at_epoch = 0
    with pytest.raises(runtime.ComfyUIRuntimeError) as expired_error:
        runtime.consume_runtime_operation_confirmation(
            "uninstall",
            expired.confirmation_token,
            expired.summary.installation_identity,
        )
    assert expired_error.value.code == "confirmation_expired"

    stale = runtime.prepare_runtime_operation("uninstall")
    (version / "source/main.py").write_text("changed fixture", encoding="utf-8")
    with pytest.raises(runtime.ComfyUIRuntimeError) as stale_error:
        runtime.consume_runtime_operation_confirmation(
            "uninstall",
            stale.confirmation_token,
            stale.summary.installation_identity,
        )
    assert stale_error.value.code == "confirmation_stale"
    assert version.exists()

    queued = runtime.prepare_runtime_operation("uninstall")
    queued_summary = runtime.consume_runtime_operation_confirmation(
        "uninstall",
        queued.confirmation_token,
        queued.summary.installation_identity,
    )
    (version / "source/main.py").write_text("changed again", encoding="utf-8")
    with pytest.raises(runtime.ComfyUIRuntimeError) as queued_error:
        runtime.run_runtime_uninstall(
            "task-uninstall-stale", confirmation=queued_summary
        )
    assert queued_error.value.code == "confirmation_stale"
    assert version.exists()


def test_interrupted_uninstall_recovery_finishes_cleanup_idempotently(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    now = runtime._iso()
    journal = runtime.RuntimeInstallJournal(
        transaction_id="uninstall-crash",
        task_id="task-uninstall",
        operation="uninstall",
        runtime_version=manifest.version,
        manifest_sha256=runtime._manifest_sha256(),
        platform_adapter="test_adapter",
        phase="rolling_back",
        staging_relative_path="staging/uninstall-crash",
        final_relative_path=f"versions/{manifest.version}",
        archive_relative_path="staging/uninstall-crash/unused.tar.gz",
        expected_archive_sha256=manifest.source.archive_sha256,
        managed_root_identity=runtime._read_owned_installation_record(
            runtime._version_root(manifest)
        )[0].managed_root_identity,
        created_at=now,
        updated_at=now,
    )
    runtime._save_journal(journal)

    assert runtime.recover_installations() == ["uninstall-crash"]
    assert runtime.recover_installations() == []
    assert not runtime._version_root(manifest).exists()
    assert runtime._read_state().installed is False
    assert not runtime._config_path(runtime._JOURNAL_FILE).exists()


def _enable_strict_fixture_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "environment_fingerprint", lambda _environment, _manifest: "f" * 64)
    monkeypatch.setattr(runtime, "RUNTIME_VALIDATOR", runtime.validate_runtime_tree)


def test_uninstall_refuses_changed_managed_root_identity_and_preserves_unowned_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    _enable_strict_fixture_validation(monkeypatch)
    original_root = tmp_path / "owned-runtime-root"
    runtime._managed_root().rename(original_root)
    unowned_root = tmp_path / "unowned-root"
    unowned_root.mkdir()
    marker = unowned_root / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    runtime._managed_root().symlink_to(unowned_root, target_is_directory=True)

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.run_runtime_uninstall(
            "task-uninstall", confirmation=_confirmed_operation("uninstall")
        )

    assert error.value.code == "runtime_identity_mismatch"
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert runtime._version_root(manifest).is_symlink() is False
    assert (original_root / f"versions/{manifest.version}").is_dir()


def test_uninstall_refuses_replaced_version_and_missing_installation_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    _enable_strict_fixture_validation(monkeypatch)
    final = runtime._version_root(manifest)
    owned_copy = tmp_path / "owned-version"
    final.rename(owned_copy)
    unowned = tmp_path / "unowned-version"
    unowned.mkdir()
    marker = unowned / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    final.symlink_to(unowned, target_is_directory=True)

    with pytest.raises(runtime.ComfyUIRuntimeError) as linked_error:
        runtime.run_runtime_uninstall(
            "task-uninstall-linked", confirmation=_confirmed_operation("uninstall")
        )

    assert linked_error.value.code == "runtime_identity_mismatch"
    assert marker.read_text(encoding="utf-8") == "unchanged"
    final.unlink()
    final.mkdir()
    unrecorded_marker = final / "unrecorded.txt"
    unrecorded_marker.write_text("unchanged", encoding="utf-8")

    with pytest.raises(runtime.ComfyUIRuntimeError) as unrecorded_error:
        runtime.run_runtime_uninstall(
            "task-uninstall-unrecorded", confirmation=_confirmed_operation("uninstall")
        )

    assert unrecorded_error.value.code == "runtime_identity_mismatch"
    assert unrecorded_marker.read_text(encoding="utf-8") == "unchanged"
    assert owned_copy.is_dir()


def test_recovery_rejects_non_authoritative_journal_without_modifying_unowned_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    marker = tmp_path / "unowned-marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    raw = runtime._journals()
    transaction_id, journal = next(iter(raw.items()))
    journal["phase"] = "rolling_back"
    journal["final_relative_path"] = "../unowned-marker.txt"
    raw[transaction_id] = journal
    runtime._atomic_json(runtime._config_path(runtime._JOURNAL_FILE), raw)

    assert runtime.recover_installations() == [transaction_id]
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert runtime._read_state().installed is True
    assert runtime._read_state().error == {"code": "runtime_identity_mismatch"}


@pytest.mark.parametrize("changed_identity", ["manifest", "tree"])
def test_uninstall_requires_current_manifest_and_tree_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_identity: str,
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    _enable_strict_fixture_validation(monkeypatch)
    final = runtime._version_root(manifest)
    protected = storage.RUNTIME_DIR / "user-owned/marker.txt"
    protected.parent.mkdir(parents=True)
    protected.write_text("unchanged", encoding="utf-8")
    if changed_identity == "manifest":
        record = runtime._read_owned_installation_record(final)[0]
        record.manifest_sha256 = "0" * 64
        runtime._write_installation_record(final / "installation.json", record)
    else:
        (final / "source/main.py").write_text("changed\n", encoding="utf-8")

    with pytest.raises(runtime.ComfyUIRuntimeError):
            runtime.run_runtime_uninstall(
                f"task-uninstall-{changed_identity}",
                confirmation=_confirmed_operation("uninstall"),
            )

    assert final.is_dir()
    assert protected.read_text(encoding="utf-8") == "unchanged"


def test_controlled_dependency_command_is_actually_cancellable(tmp_path: Path) -> None:
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks > 1:
            raise runtime.ComfyUIRuntimeError("cancelled", "cancelled")

    started = time.monotonic()
    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime._run_controlled(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout=60,
            error_code="dependency_install_failed",
            cancel=cancel,
        )

    assert error.value.code == "cancelled"
    assert time.monotonic() - started < 5


def test_parent_exception_reaps_controlled_dependency_process(tmp_path: Path, monkeypatch) -> None:
    signals: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

        def communicate(self, **_kwargs):
            raise KeyboardInterrupt

        def wait(self, **_kwargs):
            self.returncode = -15
            return self.returncode

    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(runtime.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    with pytest.raises(KeyboardInterrupt):
        runtime._run_controlled(
            ["controlled", "command"],
            cwd=tmp_path,
            timeout=60,
            error_code="dependency_install_failed",
            cancel=lambda: None,
        )

    assert signals == [(424242, runtime.signal.SIGTERM)]


def test_environment_fingerprint_rejects_wrong_python_even_with_matching_packages(tmp_path: Path, monkeypatch) -> None:
    manifest = load_runtime_manifest()
    expected = runtime._expected_dependencies(storage.ROOT_DIR / manifest.python.lock_file)
    monkeypatch.setattr(runtime, "_installed_environment", lambda _environment: ("3.11.12", expected))

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.environment_fingerprint(tmp_path, manifest)

    assert error.value.code == "dependency_install_failed"


def test_python_toolchain_fails_closed_when_reviewed_artifacts_are_unavailable() -> None:
    manifest = load_runtime_manifest().model_copy(deep=True)
    manifest.python.toolchain_status = "unavailable"
    manifest.python.toolchain_unavailable_reason = "fixture"
    manifest.python.uv_artifact = None
    manifest.python.python_runtime = None
    manifest.python.wheelhouse = None

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.verify_python_toolchain(manifest, Path("unused"))

    assert error.value.code == "unsupported_platform"


def test_environment_install_is_offline_wheel_only_and_never_resolves_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = load_runtime_manifest()
    toolchain_root = tmp_path / "toolchain"
    toolchain = runtime.VerifiedPythonToolchain(
        uv=toolchain_root / "uv",
        python=toolchain_root / "python/bin/python3.11",
        wheelhouse=toolchain_root / "wheels",
        identity_sha256="a" * 64,
    )
    toolchain.python.parent.mkdir(parents=True)
    toolchain.python.write_bytes(b"python")
    commands: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(runtime, "verify_python_toolchain", lambda _manifest, _root: toolchain)
    monkeypatch.setattr(runtime, "environment_fingerprint", lambda _environment, _manifest: "f" * 64)

    def run_controlled(argv, **kwargs):
        commands.append((argv, kwargs["environment"]))
        return None

    monkeypatch.setattr(runtime, "_run_controlled", run_controlled)
    runtime.create_python_environment(tmp_path / "environment", manifest, lambda: None)

    assert len(commands) == 2
    assert commands[0][0][0] == str(toolchain.uv)
    assert commands[0][0][1:3] == ["pip", "uninstall"]
    assert commands[0][0][-2:] == ["pip", "setuptools"]
    dependency_command, environment = commands[1]
    assert "--offline" in dependency_command
    assert "--no-index" in dependency_command
    assert "--only-binary=:all:" in dependency_command
    assert "--no-build-isolation" in dependency_command
    assert "--no-deps" in dependency_command
    assert "install" in dependency_command
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert environment["UV_OFFLINE"] == "1"


class _ArtifactResponse:
    status = 200

    def __init__(self, body: bytes, *, content_length: bool = True) -> None:
        self._body = body
        self._read = False
        self.headers = {"Content-Length": str(len(body))} if content_length else {}

    def read(self, _size: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body

    def close(self) -> None:
        return


class _ArtifactConnection:
    sock = None

    def __init__(self, response: _ArtifactResponse) -> None:
        self._response = response

    def request(self, *_args, **_kwargs) -> None:
        return

    def getresponse(self) -> _ArtifactResponse:
        return self._response

    def close(self) -> None:
        return


def test_pinned_artifact_download_requires_declared_size_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runtime,
        "_pinned_https_connection",
        lambda _hostname: _ArtifactConnection(
            _ArtifactResponse(b"fixed", content_length=False)
        ),
    )
    destination = tmp_path / "artifact"

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime._download_exact_artifact(
            destination,
            source_url="https://files.pythonhosted.org/packages/fixed.whl",
            expected_size=5,
            expected_sha256=_sha(b"fixed"),
            allowed_redirect_hosts=frozenset(),
            progress=lambda _current, _total: None,
            cancel=lambda: None,
            size_error_code="dependency_lock_mismatch",
            checksum_error_code="dependency_lock_mismatch",
        )

    assert error.value.code == "download_failed"
    assert not destination.exists()


def test_pinned_artifact_download_refuses_replaced_managed_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    with runtime._open_managed_root(create=True) as (_fd, root_identity):
        pass
    staging = runtime._managed_root() / "staging"
    runtime._ensure_managed_directory(staging, root_identity=root_identity)
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "marker"
    marker.write_bytes(b"unchanged")
    staging.rmdir()
    staging.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(
        runtime,
        "_pinned_https_connection",
        lambda _hostname: _ArtifactConnection(_ArtifactResponse(b"fixed")),
    )

    with pytest.raises(runtime.ComfyUIRuntimeError):
        runtime._download_exact_artifact(
            staging / "artifact",
            source_url="https://files.pythonhosted.org/packages/fixed.whl",
            expected_size=5,
            expected_sha256=_sha(b"fixed"),
            allowed_redirect_hosts=frozenset(),
            progress=lambda _current, _total: None,
            cancel=lambda: None,
            size_error_code="dependency_lock_mismatch",
            checksum_error_code="dependency_lock_mismatch",
            managed_root_identity=root_identity,
        )

    assert marker.read_bytes() == b"unchanged"
    assert not (external / "artifact").exists()


def test_runtime_validation_rejects_changed_toolchain_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    manifest, _archive = _install_fakes(tmp_path, monkeypatch)
    runtime.run_runtime_install("task-install")
    version = runtime._version_root(manifest)
    record = runtime.RuntimeInstallationRecord.model_validate_json(
        (version / "installation.json").read_text(encoding="utf-8")
    )
    record.toolchain_identity_sha256 = "0" * 64
    runtime._write_installation_record(version / "installation.json", record)
    monkeypatch.setattr(runtime, "environment_fingerprint", lambda _environment, _manifest: "f" * 64)

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.validate_runtime_tree(version, manifest)

    assert error.value.code == "runtime_validation_failed"


@pytest.mark.parametrize(
    ("internal", "public"),
    [
        ("archive_entry_limit", "archive_too_many_files"),
        ("archive_compression_ratio", "archive_too_large"),
        ("unsafe_archive_path", "archive_path_escape"),
        ("archive_special_file", "archive_link_rejected"),
        ("archive_extraction_failed", "extraction_failed"),
        ("critical_file_mismatch", "runtime_validation_failed"),
        ("unknown_tar_failure", "unsafe_archive"),
    ],
)
def test_archive_failures_map_to_stable_public_runtime_errors(internal: str, public: str) -> None:
    assert runtime._public_archive_error_code(internal) == public
    assert public in runtime.PUBLIC_ERROR_CODES


_FAKE_SERVER = r'''
import argparse, json, signal, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--listen')
parser.add_argument('--port', type=int)
args, _ = parser.parse_known_args()
if args.listen != '127.0.0.1':
    raise SystemExit(92)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/system_stats':
            body = {'system': {'comfyui_version': '0.28.0', 'argv': sys.argv}}
        elif self.path == '/object_info':
            body = {'KSampler': {}, 'CheckpointLoaderSimple': {}, 'SaveImage': {}}
        else:
            self.send_response(404); self.end_headers(); return
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
    def log_message(self, *_args):
        return

server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
server.serve_forever()
'''


def _prepare_fake_runtime(tmp_path: Path, monkeypatch) -> ComfyUIRuntimeManifest:
    _isolate(tmp_path, monkeypatch)
    manifest = load_runtime_manifest().model_copy(deep=True)
    manifest.custom_node_baseline = {}
    manifest.launch.startup_timeout_seconds = 8
    manifest.launch.shutdown_timeout_seconds = 2
    monkeypatch.setattr(runtime, "load_runtime_manifest", lambda: manifest)
    version = runtime._version_root(manifest)
    source = version / "source"
    source.mkdir(parents=True)
    (source / "custom_nodes").mkdir()
    (source / "main.py").write_text(_FAKE_SERVER, encoding="utf-8")
    manifest.source.source_tree_sha256 = runtime.source_tree_fingerprint(source)
    python = runtime._environment_python(version / "environment")
    python.parent.mkdir(parents=True)
    python.symlink_to(Path(sys.executable))
    record = runtime.RuntimeInstallationRecord(
        version=manifest.version,
        source_commit=manifest.source_commit,
        manifest_sha256=runtime._manifest_sha256(),
        dependency_lock_sha256=manifest.python.lock_sha256,
        environment_fingerprint="e" * 64,
        source_tree_sha256=manifest.source.source_tree_sha256,
        python_executable_sha256=runtime.sha256_file(python),
        environment_manager_version="test",
        toolchain_identity_sha256="1" * 64,
        uv_artifact_sha256="2" * 64,
        python_runtime_sha256="3" * 64,
        wheelhouse_sha256="4" * 64,
        wheel_artifact_lock_sha256="5" * 64,
        platform_adapter="test_adapter",
        managed_root_identity=runtime.RuntimeDirectoryIdentity(
            device=runtime._managed_root().stat().st_dev,
            inode=runtime._managed_root().stat().st_ino,
        ),
        parent_directory_identity=runtime.RuntimeDirectoryIdentity(
            device=version.parent.stat().st_dev,
            inode=version.parent.stat().st_ino,
        ),
        version_directory_identity=runtime.RuntimeDirectoryIdentity(
            device=version.stat().st_dev,
            inode=version.stat().st_ino,
        ),
        installed_at=runtime._iso(),
    )
    runtime._write_installation_record(version / "installation.json", record)
    monkeypatch.setattr(runtime, "RUNTIME_VALIDATOR", lambda _root, _manifest: record)
    monkeypatch.setattr(runtime, "_source_contract_pristine", lambda _root, _manifest: True)
    runtime._write_state(runtime.RuntimeStateRecord(
        installed=True,
        version=manifest.version,
        status="stopped",
        platform_adapter="test_adapter",
        manifest_sha256=runtime._manifest_sha256(),
        environment_fingerprint=record.environment_fingerprint,
        installed_at=record.installed_at,
    ))
    return manifest


@pytest.mark.skipif(os.name != "posix", reason="process-group fixture currently targets POSIX CI")
def test_supervisor_starts_health_checks_loopback_identity_and_stops(tmp_path: Path, monkeypatch) -> None:
    manifest = _prepare_fake_runtime(tmp_path, monkeypatch)
    expected_argv = runtime._expected_runtime_argv(manifest, manifest.launch.port_min, "a" * 32)
    assert expected_argv[1] == "-s"
    assert "-I" not in expected_argv

    health = runtime.start_runtime()
    snapshot = runtime.runtime_snapshot(recover=False)

    assert health.healthy is True
    assert health.identity_verified is True
    assert health.core_api_available is True
    assert health.port is not None
    assert manifest.launch.port_min <= health.port <= manifest.launch.port_max
    assert snapshot.status == "runtime_ready"
    assert snapshot.runtime_ready is True
    assert snapshot.generation_ready is False
    assert snapshot.available_actions[0] == "stop_runtime"
    process = runtime._read_process()
    assert process is not None
    assert process.ownership.process_group_id == process.ownership.pid
    assert process.ownership.session_id == process.ownership.pid
    assert process.ownership.cwd_relative_path == f"versions/{manifest.version}/source"
    assert process.ownership.nonce in " ".join(runtime._expected_runtime_argv(manifest, process.ownership.port, process.ownership.nonce))
    stopped = runtime.stop_runtime()
    assert stopped.status == "stopped"
    assert runtime._read_process() is None
    assert runtime._read_state().status == "stopped"


@pytest.mark.skipif(os.name != "posix", reason="process-group fixture currently targets POSIX CI")
def test_supervisor_detects_crash_and_does_not_return_runtime_ready(tmp_path: Path, monkeypatch) -> None:
    _prepare_fake_runtime(tmp_path, monkeypatch)
    runtime.start_runtime()
    process = runtime._read_process()
    assert process is not None
    os.killpg(process.ownership.pid, 9)
    deadline = time.monotonic() + 3
    while runtime._process_alive(process.ownership.pid) and time.monotonic() < deadline:
        time.sleep(0.02)

    health = runtime.check_runtime_health()

    assert health.status == "crashed"
    assert health.healthy is False
    assert runtime.runtime_snapshot(recover=False).runtime_ready is False


@pytest.mark.skipif(os.name != "posix", reason="listener ownership fixture targets POSIX CI")
@pytest.mark.parametrize("mismatch", ["process", "address"])
def test_listener_identity_mismatch_never_reports_runtime_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    _prepare_fake_runtime(tmp_path, monkeypatch)
    runtime.start_runtime()
    process = runtime._read_process()
    assert process is not None
    assert process.ownership.listener_pid is not None
    if mismatch == "process":
        monkeypatch.setattr(runtime, "_listener_owners", lambda _process: [(os.getpid(), "127.0.0.1")])
    else:
        listener_pid = process.ownership.listener_pid
        monkeypatch.setattr(runtime, "_listener_owners", lambda _process: [(listener_pid, "::")])
    try:
        health = runtime.check_runtime_health()

        assert health.healthy is False
        assert health.status == "repair_required"
        assert health.error is not None
        assert health.error["code"] == "runtime_identity_mismatch"
    finally:
        runtime.stop_runtime(force=True)


@pytest.mark.skipif(os.name != "posix", reason="process-group fixture currently targets POSIX CI")
def test_dead_supervisor_owned_group_is_reclaimed_without_touching_adjacent_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_fake_runtime(tmp_path, monkeypatch)
    runtime.start_runtime()
    process = runtime._read_process()
    assert process is not None
    adjacent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        start_new_session=True,
    )
    try:
        os.kill(process.ownership.pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while runtime._process_alive(process.ownership.pid) and time.monotonic() < deadline:
            time.sleep(0.02)

        health = runtime.check_runtime_health()

        assert health.status == "crashed"
        assert health.identity_verified is True
        assert runtime._read_process() is None
        assert not runtime._process_group_alive(process.ownership.process_group_id)
        assert adjacent.poll() is None
    finally:
        adjacent.terminate()
        adjacent.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="worker process-group fixture targets POSIX CI")
def test_owned_install_worker_is_reclaimed_without_touching_adjacent_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    runtime._managed_root().mkdir(parents=True)
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    worker = subprocess.Popen(argv, cwd=runtime._managed_root(), start_new_session=True)
    runtime._WORKER_HANDLES[worker.pid] = worker
    adjacent = subprocess.Popen(argv, cwd=tmp_path, start_new_session=True)
    try:
        token = runtime._process_start_token(worker.pid)
        group = runtime._process_group_identity(worker.pid)
        assert token is not None
        assert group == (worker.pid, worker.pid)
        root_info = runtime._managed_root().stat()
        ownership = runtime.RuntimeWorkerOwnership(
            pid=worker.pid,
            process_start_token=token,
            process_group_id=group[0],
            session_id=group[1],
            executable_sha256=runtime.sha256_file(Path(sys.executable)),
            argv_sha256=runtime._argv_digest(argv),
            argv=argv,
            cwd_relative_path=".",
            managed_root_identity=runtime.RuntimeDirectoryIdentity(
                device=root_info.st_dev,
                inode=root_info.st_ino,
            ),
            started_at=runtime._iso(),
        )
        runtime._write_worker_process(ownership)

        assert runtime._runtime_worker_mismatch_reason(ownership) is None
        assert runtime._reclaim_runtime_worker() is True
        worker.wait(timeout=5)
        assert runtime._read_worker_process() is None
        assert adjacent.poll() is None
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        adjacent.terminate()
        adjacent.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="worker process-group fixture targets POSIX CI")
def test_mismatched_worker_record_never_signals_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    runtime._managed_root().mkdir(parents=True)
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    worker = subprocess.Popen(argv, cwd=runtime._managed_root(), start_new_session=True)
    try:
        group = runtime._process_group_identity(worker.pid)
        assert group == (worker.pid, worker.pid)
        root_info = runtime._managed_root().stat()
        runtime._write_worker_process(runtime.RuntimeWorkerOwnership(
            pid=worker.pid,
            process_start_token="mismatched-start-token",
            process_group_id=group[0],
            session_id=group[1],
            executable_sha256=runtime.sha256_file(Path(sys.executable)),
            argv_sha256=runtime._argv_digest(argv),
            argv=argv,
            cwd_relative_path=".",
            managed_root_identity=runtime.RuntimeDirectoryIdentity(
                device=root_info.st_dev,
                inode=root_info.st_ino,
            ),
            started_at=runtime._iso(),
        ))

        with pytest.raises(runtime.ComfyUIRuntimeError) as error:
            runtime._reclaim_runtime_worker()

        assert error.value.code == "runtime_identity_mismatch"
        assert worker.poll() is None
    finally:
        worker.terminate()
        worker.wait(timeout=5)


def test_port_selector_skips_conflicts_and_fails_when_range_is_full(tmp_path: Path, monkeypatch) -> None:
    manifest = _prepare_fake_runtime(tmp_path, monkeypatch)
    manifest.launch.port_min = 18440
    manifest.launch.port_max = 18441
    first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    first.bind(("127.0.0.1", 18440))
    try:
        assert runtime._find_port(manifest) == 18441
        second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        second.bind(("127.0.0.1", 18441))
        try:
            with pytest.raises(runtime.ComfyUIRuntimeError) as error:
                runtime._find_port(manifest)
            assert error.value.code == "port_conflict"
        finally:
            second.close()
    finally:
        first.close()


def test_pid_identity_mismatch_never_sends_signal(tmp_path: Path, monkeypatch) -> None:
    manifest = _prepare_fake_runtime(tmp_path, monkeypatch)
    ownership = runtime.RuntimeProcessOwnership(
        pid=os.getpid(),
        process_start_token="reused-pid-token",
        process_group_id=os.getpid(),
        session_id=os.getpid(),
        executable_sha256="0" * 64,
        runtime_version=manifest.version,
        runtime_root_relative_path=f"versions/{manifest.version}",
        cwd_relative_path=f"versions/{manifest.version}/source",
        installation_identity_sha256="0" * 64,
        port=manifest.launch.port_min,
        nonce="a" * 32,
        expected_argv_sha256="0" * 64,
        runtime_argv_sha256="0" * 64,
        supervisor_script_sha256="0" * 64,
        source_tree_sha256=manifest.source.source_tree_sha256,
        started_at=runtime._iso(),
    )
    process = runtime.ComfyUIRuntimeProcess(state="running", ownership=ownership, updated_at=runtime._iso())
    signals: list[int] = []
    monkeypatch.setattr(runtime.os, "killpg", lambda pid, _signal: signals.append(pid))

    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime._stop_owned_process(process, manifest, force=True)

    assert error.value.code == "runtime_identity_mismatch"
    assert signals == []


def test_invalid_process_record_fails_closed_without_runtime_mutations(tmp_path: Path, monkeypatch) -> None:
    manifest = _prepare_fake_runtime(tmp_path, monkeypatch)
    process_path = runtime._config_path(runtime._PROCESS_FILE)
    process_path.parent.mkdir(parents=True, exist_ok=True)
    process_path.write_text('{"schema":"invalid"}', encoding="utf-8")

    snapshot = runtime.runtime_snapshot(recover=False)

    assert snapshot.status == "repair_required"
    assert snapshot.available_actions == ["view_runtime_logs", "open_runtime_directory"]
    with pytest.raises(runtime.ComfyUIRuntimeError) as start_error:
        runtime.start_runtime()
    assert start_error.value.code == "runtime_identity_mismatch"
    with pytest.raises(runtime.ComfyUIRuntimeError) as stop_error:
        runtime.stop_runtime()
    assert stop_error.value.code == "runtime_identity_mismatch"
    assert runtime._version_root(manifest).exists()


def test_custom_node_modification_blocks_start_and_requests_repair(tmp_path: Path, monkeypatch) -> None:
    _prepare_fake_runtime(tmp_path, monkeypatch)

    def modified(_root, _manifest):
        raise runtime.ComfyUIRuntimeError("runtime_modified", "external custom node")

    monkeypatch.setattr(runtime, "RUNTIME_VALIDATOR", modified)
    with pytest.raises(runtime.ComfyUIRuntimeError) as error:
        runtime.start_runtime()

    assert error.value.code == "runtime_modified"
    assert runtime._read_state().status == "unsupported_modified"
    assert runtime._read_process() is None


def test_runtime_logs_are_bounded_and_paths_are_redacted(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "_LOG_MAX_BYTES", 128)
    marker = str(storage.RUNTIME_DIR / "private/location")
    for index in range(20):
        runtime._append_log("runtime", f"line-{index} {marker} token=secret-value")

    combined = "\n".join(runtime.log_summary("runtime"))
    assert marker not in combined
    assert "secret-value" not in combined
    assert "<runtime>" in combined
    assert (runtime._logs_root() / "runtime.log.1").exists()
