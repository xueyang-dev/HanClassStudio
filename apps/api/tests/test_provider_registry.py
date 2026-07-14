from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import hcs_api.main as main
import hcs_api.provider_registry as registry
import hcs_api.storage as storage
from hcs_api.main import app


def _isolate(tmp_path, monkeypatch) -> TestClient:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(storage, "PROJECTS_DIR", runtime / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", runtime / "projects")
    return TestClient(app)


def test_registry_fixture_has_trusted_fixed_and_verifiable_metadata() -> None:
    entries = registry.validate_registry()
    assert {entry.provider_id for entry in entries} == {"hcs_mock_ocr", "hcs_mock_llm"}
    for entry in entries:
        assert entry.trust_level == "first_party"
        assert entry.source_ref not in {"main", "latest"}
        assert len(entry.checksum_sha256) == 64
        assert entry.manifest_digest == registry._digest(entry.manifest.model_dump(mode="json", by_alias=True))
        assert entry.executor == "mock"
        assert entry.mock_only is True

    with pytest.raises((ValidationError, ValueError)):
        registry.ProviderRegistryEntry(
            provider_id="unsafe",
            capability="ocr",
            display_name="Unsafe",
            source_url="https://example.com",
            repository="example/unsafe",
            publisher="unknown",
            license="MIT",
            trust_level="first_party",
            version="1.0.0",
            source_ref="main",
            checksum_sha256="0" * 64,
            manifest_version="1",
            manifest_digest="0" * 64,
            manifest={"provider_id": "unsafe", "version": "1.0.0", "source_ref": "main", "steps": ["checkout_exact_ref"]},
        )


def test_registry_install_is_two_phase_and_persists_backend_state(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    catalog = client.get("/api/providers/registry")
    assert catalog.status_code == 200
    status = next(item for item in catalog.json()["providers"] if item["entry"]["provider_id"] == "hcs_mock_ocr")
    assert status["installation"]["install_state"] == "ready"
    assert status["install_actions"] == ["prepare_install"]

    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare")
    assert prepared.status_code == 200
    plan = prepared.json()["plan"]
    assert plan["provider_id"] == "hcs_mock_ocr"
    assert all("shell" not in step for step in plan["steps"])

    not_confirmed = client.get("/api/providers/registry/hcs_mock_ocr")
    assert not_confirmed.json()["installation"]["install_state"] == "ready"

    confirmed = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": plan["plan_id"], "confirmation_token": prepared.json()["confirmation_token"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["installation"]["install_state"] == "available"
    assert confirmed.json()["installation"]["installed_version"] == "0.1.0"
    assert "confirmation_token" not in confirmed.text

    logs = client.get("/api/providers/registry/hcs_mock_ocr/install/logs")
    assert logs.status_code == 200
    assert logs.json()
    assert all("api_key" not in json.dumps(item) for item in logs.json())


def test_confirmation_token_is_bound_to_plan_and_provider(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    response = client.post(
        "/api/providers/registry/hcs_mock_llm/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "provider_plan_invalid"

    bad_token = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": "wrong"},
    )
    assert bad_token.status_code == 409
    assert bad_token.json()["detail"]["code"] == "provider_confirmation_invalid"


def test_secret_required_provider_never_echoes_or_persists_secret(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_llm/install/prepare").json()
    confirmed = client.post(
        "/api/providers/registry/hcs_mock_llm/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["installation"]["install_state"] == "configuring"
    assert confirmed.json()["installation"]["configuration_status"] == "missing"

    secret = "registry-test-secret"
    configured = client.post("/api/providers/registry/hcs_mock_llm/configure", json={"values": {"api_key": secret}})
    assert configured.status_code == 200
    assert configured.json()["installation"]["install_state"] == "available"
    assert configured.json()["installation"]["api_key_present"] is True
    assert secret not in configured.text
    assert secret not in client.get("/api/providers/registry").text
    assert secret not in (storage.CONFIG_DIR / "provider_installations.json").read_text(encoding="utf-8")


def test_environment_blocker_removes_install_actions(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(registry.platform, "system", lambda: "Plan9")
    response = client.get("/api/providers/registry")
    assert response.status_code == 200
    status = response.json()["providers"][0]
    assert status["environment"]["blockers"]
    assert status["install_actions"] == []
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare")
    assert prepared.status_code == 400
    assert prepared.json()["detail"]["code"] == "provider_environment_blocked"


def test_state_machine_rejects_illegal_transition() -> None:
    record = registry.ProviderInstallationRecord(provider_id="test", capability="ocr")
    with pytest.raises(registry.ProviderRegistryError) as error:
        registry._transition(record, "available")
    assert error.value.code == "provider_invalid_state_transition"


def test_unknown_provider_is_not_silently_fallbacked(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    response = client.post("/api/providers/registry/unknown-provider/install/prepare")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "provider_not_registered"


def test_failed_install_preserves_previous_active_version(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    assert client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    ).status_code == 200

    monkeypatch.setattr(registry, "EXECUTOR", registry.MockProviderExecutor("activate_version"))
    upgrade = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    failed = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": upgrade["plan"]["plan_id"], "confirmation_token": upgrade["confirmation_token"]},
    )
    assert failed.status_code == 400
    current = client.get("/api/providers/registry/hcs_mock_ocr").json()["installation"]
    assert current["install_state"] == "failed"
    assert current["installed_version"] == "0.1.0"
    assert current["active_version"] == "0.1.0"
