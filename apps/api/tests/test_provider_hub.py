from __future__ import annotations

import json
import logging
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
from hcs_api.ffmpeg_video import FfmpegCapability
from hcs_api.main import app
from hcs_api.models import ImageProviderSettings, ProviderSettings, SafeValidationErrorEnvelope


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


def test_video_package_uses_full_capability_probe_not_executable_presence(monkeypatch) -> None:
    monkeypatch.setattr(hub, "probe_ffmpeg", lambda: FfmpegCapability(
        available=False,
        executable="/usr/local/bin/ffmpeg",
        probe_executable="/usr/local/bin/ffprobe",
        blockers=["subtitles_filter_missing", "decoder_missing:webp", "cjk_font_not_found"],
    ))

    item = hub._video_package_item(hub.detect_hardware())

    assert item.installed is True
    assert item.ready is False
    assert item.status == "degraded"
    assert item.technical_error == {
        "code": "capability_probe_failed",
        "blockers": ["subtitles_filter_missing", "decoder_missing:webp", "cjk_font_not_found"],
    }


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
    task = _wait_install(client, started.json()["task"]["task_id"])
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
    assert "cancel_install" not in local["available_actions"]


def test_checksum_mismatch_fails_and_leaves_no_installed_result(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_FIXTURE_SHA256", "0" * 64)
    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    task = _wait_install(client, started.json()["task"]["task_id"])
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
    task = _wait_install(client, started.json()["task"]["task_id"])
    assert task["state"] == "failed"
    assert task["error"]["code"] == "internal_error"
    installed = storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json"
    assert not installed.exists()
    local = next(item for item in client.get("/api/providers/hub").json()["providers"] if item["id"] == "hcs.local-image-basic")
    assert local["ready"] is False


def test_install_can_be_cancelled_and_cleans_temporary_files(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_INSTALL_STEP_DELAY_SECONDS", 0.08)
    response = client.post("/api/providers/hub/packages/hcs.local-image-basic/install").json()
    started = response["task"]
    cancelled = client.post(f"/api/providers/hub/install-tasks/{started['task_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["cancel_requested"] is True
    assert "cancel_install" in cancelled.json()["provider"]["available_actions"]
    task = _wait_install(client, started["task_id"])
    assert task["state"] == "cancelled"
    assert task["error"]["code"] == "cancelled"
    assert not (storage.RUNTIME_DIR / "providers" / "hcs.local-image-basic" / "1.0.0" / "package.json").exists()


def test_install_start_returns_authoritative_actions_and_rejects_duplicates(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_INSTALL_STEP_DELAY_SECONDS", 0.08)

    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    assert started.status_code == 200
    body = started.json()
    assert body["task"]["state"] == "queued"
    assert body["provider"]["status"] == "installing"
    assert "cancel_install" in body["provider"]["available_actions"]
    assert "install" not in body["provider"]["available_actions"]
    assert "repair" not in body["provider"]["available_actions"]

    duplicate = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "task_conflict"

    task_id = body["task"]["task_id"]
    assert client.post(f"/api/providers/hub/install-tasks/{task_id}/cancel").status_code == 200
    assert _wait_install(client, task_id)["state"] == "cancelled"
    local = next(
        item for item in client.get("/api/providers/hub").json()["providers"]
        if item["id"] == "hcs.local-image-basic"
    )
    assert "install" in local["available_actions"]
    assert "cancel_install" not in local["available_actions"]


def test_repair_start_replaces_repair_action_and_rejects_duplicates(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "_INSTALL_STEP_DELAY_SECONDS", 0.08)
    hub._update_hub_state("local_image", {"installed": True, "ready": False})
    before = next(
        item for item in client.get("/api/providers/hub").json()["providers"]
        if item["id"] == "hcs.local-image-basic"
    )
    assert "repair" in before["available_actions"]

    started = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    assert started.status_code == 200
    body = started.json()
    assert "cancel_install" in body["provider"]["available_actions"]
    assert "repair" not in body["provider"]["available_actions"]
    duplicate = client.post("/api/providers/hub/packages/hcs.local-image-basic/install")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "task_conflict"

    task_id = body["task"]["task_id"]
    assert client.post(f"/api/providers/hub/install-tasks/{task_id}/cancel").status_code == 200
    assert _wait_install(client, task_id)["state"] == "cancelled"
    after = next(
        item for item in client.get("/api/providers/hub").json()["providers"]
        if item["id"] == "hcs.local-image-basic"
    )
    assert "repair" in after["available_actions"]
    assert "cancel_install" not in after["available_actions"]


@pytest.mark.parametrize(
    ("marker", "payload"),
    [
        (
            "CONTROL_SECRET_MARKER",
            {"api_key": "CONTROL_SECRET_MARKER\r\n", "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
        ),
        (
            "NUL_SECRET_MARKER",
            {"api_key": "NUL_SECRET_MARKER\x00", "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
        ),
        (
            "OVERSIZED_SECRET_MARKER",
            {"api_key": "OVERSIZED_SECRET_MARKER" + "x" * 4096, "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
        ),
        (
            "ENDPOINT_SECRET_MARKER",
            {"api_key": "valid-key", "endpoint": "https://api.openai.com/v1?token=ENDPOINT_SECRET_MARKER", "model": "gpt-image-2"},
        ),
        (
            "API_KEY_QUERY_MARKER",
            {"api_key": "valid-key", "endpoint": "https://api.openai.com/v1?api_key=API_KEY_QUERY_MARKER", "model": "gpt-image-2"},
        ),
        (
            "ENDPOINT_USERINFO_MARKER",
            {"api_key": "valid-key", "endpoint": "https://user:ENDPOINT_USERINFO_MARKER@api.openai.com/v1", "model": "gpt-image-2"},
        ),
    ],
)
def test_request_validation_never_echoes_sensitive_input_or_logs(
    tmp_path, monkeypatch, caplog, marker: str, payload: dict[str, str]
) -> None:
    client = _isolate(tmp_path, monkeypatch)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = client.put(
            "/api/providers/hub/online/openai_images/configuration",
            json=payload,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert response.json()["error"]["fields"]
    assert marker not in response.text
    assert '"input"' not in response.text
    assert marker not in caplog.text


def test_openapi_declares_and_runtime_returns_safe_validation_envelope(tmp_path, monkeypatch, caplog) -> None:
    client = _isolate(tmp_path, monkeypatch)
    spec = client.get("/openapi.json").json()
    expected_ref = "#/components/schemas/SafeValidationErrorEnvelope"
    declared_422 = []
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            response = operation.get("responses", {}).get("422")
            if response:
                declared_422.append((method.upper(), path))
                assert response["content"]["application/json"]["schema"]["$ref"] == expected_ref
    assert ("PUT", "/api/providers/hub/online/{provider_id}/configuration") in declared_422

    marker = "OPENAPI_VALIDATION_SECRET_MARKER"
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = client.put(
            "/api/providers/hub/online/openai_images/configuration",
            json={"api_key": marker + "\n", "endpoint": "https://api.openai.com/v1", "model": "gpt-image-2"},
        )
    assert response.status_code == 422
    SafeValidationErrorEnvelope.model_validate(response.json())
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert marker not in response.text
    assert marker not in caplog.text


def test_nested_validation_errors_drop_input_message_and_context() -> None:
    marker = "NESTED_SECRET_MARKER"
    fields = main._safe_request_validation_fields([
        {
            "loc": ("body", "credentials", "api_key"),
            "type": "string_too_long",
            "msg": marker,
            "input": marker,
            "ctx": {"secret": marker},
        }
    ])
    serialized = json.dumps(fields)
    assert fields == [{
        "path": "credentials.api_key",
        "code": "string_too_long",
        "message": "The value is too long.",
    }]
    assert marker not in serialized

    authorization_marker = "AUTHORIZATION_HEADER_MARKER"
    header_fields = main._safe_request_validation_fields([{
        "loc": ("header", "authorization"),
        "type": "value_error",
        "msg": authorization_marker,
        "input": f"Bearer {authorization_marker}",
    }])
    assert authorization_marker not in json.dumps(header_fields)


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


@pytest.mark.parametrize(
    ("image", "expected_endpoint", "expected_model", "key_present"),
    [
        (ImageProviderSettings(), "https://api.openai.com/v1", "gpt-image-2", False),
        (ImageProviderSettings(provider="placeholder", model="placeholder-svg", api_key="old-placeholder-key"), "https://api.openai.com/v1", "gpt-image-2", False),
        (ImageProviderSettings(provider="other_online", endpoint_url="https://api.openai.com/v1/custom", model="other-model", api_key="other-key"), "https://api.openai.com/v1", "gpt-image-2", False),
        (ImageProviderSettings(provider="openai_images", endpoint_url="https://api.openai.com/v1/custom", model="gpt-image-2", api_key="saved-key"), "https://api.openai.com/v1/custom", "gpt-image-2", True),
        (ImageProviderSettings(provider="openai_images", endpoint_url="https://api.openai.com/v1/custom", model="teacher-image-v2", api_key="saved-key"), "https://api.openai.com/v1/custom", "teacher-image-v2", True),
    ],
)
def test_online_config_only_inherits_matching_provider(
    tmp_path, monkeypatch, image: ImageProviderSettings, expected_endpoint: str, expected_model: str, key_present: bool
) -> None:
    client = _isolate(tmp_path, monkeypatch)
    storage.write_provider_settings(ProviderSettings(image=image))
    config = client.get("/api/providers/hub/online/openai_images/configuration")
    assert config.status_code == 200
    assert config.json()["endpoint"] == expected_endpoint
    assert config.json()["model"] == expected_model
    assert config.json()["api_key_present"] is key_present


def test_online_config_with_missing_provider_type_uses_real_defaults(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    storage.ensure_runtime()
    storage.PROVIDER_SETTINGS_PATH.write_text(json.dumps({"image": {"model": "placeholder-svg"}}), encoding="utf-8")
    config = client.get("/api/providers/hub/online/openai_images/configuration")
    assert config.json()["model"] == "gpt-image-2"
    assert config.json()["endpoint"] == "https://api.openai.com/v1"
    assert config.json()["api_key_present"] is False


def test_online_config_normalizes_empty_model_and_rejects_placeholder(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    empty = client.put(
        "/api/providers/hub/online/openai_images/configuration",
        json={"api_key": "valid-key", "endpoint": "https://api.openai.com/v1", "model": "  "},
    )
    assert empty.status_code == 200
    assert empty.json()["model"] == "gpt-image-2"

    rejected = client.put(
        "/api/providers/hub/online/openai_images/configuration",
        json={"api_key": "valid-key", "endpoint": "https://api.openai.com/v1", "model": "placeholder-svg"},
    )
    assert rejected.status_code == 422
    assert storage.read_provider_settings().image.model == "gpt-image-2"


def test_connection_never_uses_placeholder_model(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    storage.write_provider_settings(ProviderSettings(image=ImageProviderSettings(
        provider="openai_images",
        endpoint_url="https://api.openai.com/v1",
        api_key="valid-key",
        model="placeholder-svg",
    )))
    checked: list[str] = []
    monkeypatch.setattr(hub, "CONNECTION_CHECKER", lambda _endpoint, _api_key, model: checked.append(model))
    response = client.post("/api/providers/hub/online/openai_images/test")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "health_check_failed"
    assert checked == []


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
