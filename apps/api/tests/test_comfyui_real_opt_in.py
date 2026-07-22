from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import hcs_api.comfyui_runtime as runtime
import hcs_api.storage as storage
from hcs_api.comfyui_archive import load_runtime_manifest


pytestmark = pytest.mark.skipif(
    os.environ.get("HCS_RUN_REAL_COMFYUI_RUNTIME") != "1",
    reason="set HCS_RUN_REAL_COMFYUI_RUNTIME=1 for the large official ComfyUI integration",
)


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def test_real_official_comfyui_install_start_health_stop_uninstall(tmp_path: Path, monkeypatch) -> None:
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        pytest.skip("real Phase 2B adapter is enabled only for macOS Apple Silicon")
    if shutil.which("uv") is None:
        pytest.skip("the reviewed uv environment manager is unavailable")
    if shutil.disk_usage(tmp_path).free < 8 * 1024**3:
        pytest.skip("real ComfyUI integration requires at least 8 GB free disk")

    root = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", root)
    monkeypatch.setattr(storage, "PROJECTS_DIR", root / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", root / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", root / "config/provider_settings.json")
    manifest = load_runtime_manifest()
    report: dict[str, object] = {
        "schema": "hanclassstudio.comfyui_real_validation.v1",
        "validated_at": runtime._iso(),
        "upstream_commit": manifest.source_commit,
        "archive_url": manifest.source.archive_url,
        "archive_sha256": manifest.source.archive_sha256,
        "platform": "macos",
        "architecture": "arm64",
        "gpu_type": "apple_silicon_integrated",
        "python_version": manifest.python.version,
        "dependency_lock_sha256": manifest.python.lock_sha256,
        "custom_nodes_allowed": False,
        "generation_ready": False,
    }
    installed = False
    running = False
    try:
        install_started = time.monotonic()
        runtime.run_runtime_install("real-opt-in")
        installed = True
        report["install_seconds"] = round(time.monotonic() - install_started, 3)
        report["installed_bytes"] = _directory_size(runtime._version_root(manifest))
        installation = runtime.validate_runtime_tree(runtime._version_root(manifest), manifest)
        report["environment_manager"] = f"uv {installation.environment_manager_version}"
        report["python_executable_sha256"] = installation.python_executable_sha256

        start_started = time.monotonic()
        health = runtime.start_runtime()
        running = True
        report["startup_seconds"] = round(time.monotonic() - start_started, 3)
        report["bind_host"] = manifest.launch.listen_host
        report["actual_port"] = health.port
        report["api_health"] = {
            "healthy": health.healthy,
            "identity_verified": health.identity_verified,
            "core_api_available": health.core_api_available,
            "custom_nodes_pristine": health.custom_nodes_pristine,
            "version": health.version,
        }
        assert health.healthy is True
        assert health.identity_verified is True
        assert health.core_api_available is True
        assert health.custom_nodes_pristine is True
        assert health.version == manifest.version
        assert health.port is not None
        process = runtime._read_process()
        assert process is not None
        listener = subprocess.run(
            ["lsof", "-nP", "-a", "-p", str(process.ownership.pid), f"-iTCP:{health.port}", "-sTCP:LISTEN", "-Fn"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert listener.returncode == 0
        listen_names = [line[1:] for line in listener.stdout.splitlines() if line.startswith("n")]
        assert listen_names == [f"127.0.0.1:{health.port}"]
        report["actual_listener"] = listen_names[0]

        stopped = runtime.stop_runtime()
        running = False
        report["stop_result"] = stopped.status
        assert stopped.status == "stopped"

        runtime.run_runtime_uninstall("real-opt-in-uninstall")
        installed = False
        report["uninstall_result"] = "not_installed" if not runtime._read_state().installed else "failed"
        assert runtime._read_state().installed is False
        assert not runtime._version_root(manifest).exists()
    except runtime.ComfyUIRuntimeError as exc:
        report["error"] = {"code": exc.code, "message": exc.message}
        report["runtime_log_tail"] = runtime.log_summary("runtime", max_lines=40)
        report["install_log_tail"] = runtime.log_summary("install", max_lines=20)
        raise
    finally:
        if running:
            try:
                runtime.stop_runtime(force=True)
            except runtime.ComfyUIRuntimeError:
                pass
        if installed:
            try:
                runtime.run_runtime_uninstall("real-opt-in-cleanup")
            except runtime.ComfyUIRuntimeError:
                pass
        report_path = os.environ.get("HCS_COMFYUI_REAL_REPORT")
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
