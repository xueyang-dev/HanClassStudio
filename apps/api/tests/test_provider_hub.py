from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import hcs_api.main as main
import hcs_api.provider_hub as hub
import hcs_api.provider_registry as registry
import hcs_api.storage as storage
from hcs_api.main import app


def _isolate(tmp_path: Path, monkeypatch) -> TestClient:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(storage, "PROJECTS_DIR", runtime / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", runtime / "projects")
    hub._install_threads.clear()
    hub._cancelled_tasks.clear()
    hub._refresh_threads.clear()
    return TestClient(app)


def _wait_install(client: TestClient, task_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/providers/hub/install-tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["state"] not in {"queued", "running"}:
            return task
        time.sleep(0.02)
    raise AssertionError("installation task did not finish")


def _wait_refresh(client: TestClient, task_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/providers/hub/refresh/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["state"] not in {"queued", "running"}:
            return task
        time.sleep(0.02)
    raise AssertionError("refresh task did not finish")


def test_hub_catalog_separates_domain_layers_and_actions(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    response = client.get("/api/providers/hub")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "hanclassstudio.provider_hub.v1"
    featured = {item["id"]: item for item in body["providers"] if item["recommended"]}
    assert set(featured) == {
        "hcs.teaching-video-basic",
        "hcs.local-image-basic",
        "hcs.online-image-high-quality",
    }
    local = featured["hcs.local-image-basic"]
    assert local["status"] == "not_installed"
    assert "install" in local["available_actions"]
    assert local["capability_package"]["runtime"]["id"] == "fixture-runtime"
    assert local["capability_package"]["model_packages"][0]["safe_format"] is True
    assert local["capability_package"]["workflow_packs"][0]["id"] == "teaching-illustration-fixture-v1"
    online = featured["hcs.online-image-high-quality"]
    assert online["status"] == "not_configured"
    assert "test_connection" not in online["available_actions"]
    assert online["source_links"]["api_application_url"].startswith("https://")


def test_hub_read_is_zero_network_and_hardware_failure_degrades(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(hub, "refresh_registry", lambda: calls.append("network"))
    assert client.get("/api/providers/hub").status_code == 200
    assert calls == []

    monkeypatch.setattr(hub.platform, "system", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))
    hardware = client.get("/api/providers/hub/hardware")
    assert hardware.status_code == 200
    assert hardware.json()["status"] == "unknown"
    assert hardware.json()["reasons"]


def test_external_links_reject_active_or_credentialed_protocols() -> None:
    for value in (
        "javascript:alert(1)",
        "file:///tmp/provider",
        "http://example.com/provider",
        "https://user:secret@example.com/provider",
        "https://example.com:8443/provider",
    ):
        with pytest.raises((ValidationError, ValueError)):
            hub.SourceLinks(project_url=value)

    with pytest.raises(ValidationError):
        hub.OnlineProviderConfigRequest(api_key="safe\r\nInjected: value")
    with pytest.raises(ValidationError):
        hub.OnlineProviderConfigRequest(model="gpt-image-2?unexpected=true")


def test_invalid_manifest_is_isolated_from_valid_entries(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    valid = client.get("/api/providers/hub").json()["providers"][0]
    invalid = {**valid, "id": "unsafe-entry", "unexpected_remote_field": "ignored-no"}
    accepted, errors = hub.isolate_provider_manifests([valid, invalid])
    assert [item.id for item in accepted] == [valid["id"]]
    assert errors == [{"code": "invalid_manifest", "entry": "unsafe-entry"}]


def test_fixture_install_reports_real_task_and_health_state(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    assert started.status_code == 200
    task = _wait_install(client, started.json()["task_id"])
    assert task["state"] == "completed"
    assert task["phase"] == "completed"
    assert task["progress"] == 100
    assert task["downloaded_bytes"] == task["total_bytes"]
    installed = storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json"
    assert installed.is_file()
    assert json.loads(installed.read_text(encoding="utf-8"))["smoke_test"] == "deterministic-teaching-illustration-ok"

    catalog = client.get("/api/providers/hub").json()
    local = next(item for item in catalog["providers"] if item["id"] == "hcs.local-image-basic")
    assert local["status"] == "ready"
    assert local["installed"] is True
    assert local["ready"] is True
    assert "check_health" in local["available_actions"]


def test_checksum_mismatch_fails_and_leaves_no_installed_result(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_FIXTURE_SHA256", "0" * 64)
    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    task = _wait_install(client, started.json()["task_id"])
    assert task["state"] == "failed"
    assert task["error"]["code"] == "checksum_mismatch"
    assert "repair" in task["recoverable_actions"]
    installed = storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json"
    assert not installed.exists()
    local = next(item for item in client.get("/api/providers/hub").json()["providers"] if item["id"] == "hcs.local-image-basic")
    assert local["ready"] is False
    assert local["status"] != "ready"


def test_unexpected_post_copy_failure_cleans_artifact_and_never_marks_ready(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)

    def fail_state_commit(_key: str, _value: object) -> None:
        raise OSError("simulated state persistence failure")

    monkeypatch.setattr(hub, "_update_hub_state", fail_state_commit)
    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    task = _wait_install(client, started.json()["task_id"])
    assert task["state"] == "failed"
    assert task["error"]["code"] == "internal_error"
    installed = storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json"
    assert not installed.exists()
    local = next(item for item in client.get("/api/providers/hub").json()["providers"] if item["id"] == "hcs.local-image-basic")
    assert local["ready"] is False


def test_install_can_be_cancelled_and_cleans_temporary_files(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_INSTALL_STEP_DELAY_SECONDS", 0.08)
    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install").json()
    cancelled = client.post(f"/api/providers/hub/install-tasks/{started['task_id']}/cancel")
    assert cancelled.status_code == 200
    task = _wait_install(client, started["task_id"])
    assert task["state"] == "cancelled"
    assert task["error"]["code"] == "cancelled"
    assert not (storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json").exists()


def test_explicit_refresh_task_summarizes_success_and_retains_snapshot_on_failure(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    calls: list[int] = []

    def success():
        calls.append(1)
        return registry.RegistryRefreshResponse(catalog=registry.registry_status(), changed_provider_ids=[])

    monkeypatch.setattr(hub, "refresh_registry", success)
    assert calls == []
    started = client.post("/api/providers/hub/refresh")
    assert started.status_code == 200
    task = _wait_refresh(client, started.json()["task_id"])
    assert task["state"] == "completed"
    assert task["summary"]["unchanged"] == 2
    assert calls == [1]

    def failed():
        raise registry.ProviderRegistryError("provider_registry_fetch_failed", "secret upstream detail")

    monkeypatch.setattr(hub, "refresh_registry", failed)
    started = client.post("/api/providers/hub/refresh")
    task = _wait_refresh(client, started.json()["task_id"])
    assert task["state"] == "partial"
    assert task["summary"]["failed_sources"] == 1
    official = next(source for source in task["summary"]["sources"] if source["source_id"] == "official_registry")
    assert official["retained_previous_snapshot"] is True
    assert any(source["source_id"] == "builtin_catalog" and source["status"] == "unchanged" for source in task["summary"]["sources"])
    assert "secret upstream detail" not in json.dumps(task)
    assert client.get("/api/providers/hub").status_code == 200


def test_online_configuration_is_explicit_redacted_testable_and_deletable(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    secret = "hub-online-secret"
    saved = client.put(
        "/api/providers/hub/online/openai_images/configuration",
        json={"api_key": secret, "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
    )
    assert saved.status_code == 200
    assert saved.json()["api_key_present"] is True
    assert saved.json()["secure_storage"] == "local_file_write_only"
    assert secret not in saved.text
    assert secret not in client.get("/api/providers/hub").text
    legacy_public_settings = client.get("/api/settings/providers")
    assert legacy_public_settings.status_code == 200
    assert secret not in legacy_public_settings.text
    assert legacy_public_settings.json()["image"]["api_key_present"] is True
    assert legacy_public_settings.json()["capabilities"]["image"]["api_key_present"] is True
    if os.name == "posix":
        assert stat.S_IMODE(storage.PROVIDER_SETTINGS_PATH.stat().st_mode) == 0o600

    checked: list[tuple[str, str]] = []
    monkeypatch.setattr(hub, "CONNECTION_CHECKER", lambda endpoint, api_key, model: checked.append((endpoint, model)))
    tested = client.post("/api/providers/hub/online/openai_images/test")
    assert tested.status_code == 200
    assert tested.json()["status"] == "ready"
    assert checked == [("https://api.openai.com/v1", "gpt-image-2")]

    disabled = client.post("/api/providers/hub/online/openai_images/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["available_actions"][-1] == "enable"

    removed = client.delete("/api/providers/hub/online/openai_images/configuration")
    assert removed.status_code == 200
    assert removed.json()["api_key_present"] is False
    settings = storage.read_provider_settings()
    assert settings.image.api_key == ""
    assert secret not in client.get("/api/providers/hub/online/openai_images/configuration").text


def test_connection_failure_is_classified_and_never_marks_ready(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    assert client.put(
        "/api/providers/hub/online/openai_images/configuration",
        json={"api_key": "bad-key", "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
    ).status_code == 200

    def reject(_endpoint: str, _api_key: str, _model: str) -> None:
        raise hub.ProviderHubError("authentication_error", "The Provider rejected the API Key")

    monkeypatch.setattr(hub, "CONNECTION_CHECKER", reject)
    response = client.post("/api/providers/hub/online/openai_images/test")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_error"
    item = next(item for item in client.get("/api/providers/hub").json()["providers"] if item["id"] == "hcs.online-image-high-quality")
    assert item["status"] == "degraded"
    assert item["ready"] is False
