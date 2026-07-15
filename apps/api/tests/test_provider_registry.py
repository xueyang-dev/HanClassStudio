from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

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

    payload = registry.registry_entries()[0].model_dump(mode="json", by_alias=True)
    payload["source_url"] = "http://github.com/xueyang-dev/HanClassStudio/tree/v0.1.0/providers"
    with pytest.raises((ValidationError, ValueError)):
        registry.ProviderRegistryEntry.model_validate(payload)
    payload = registry.registry_entries()[0].model_dump(mode="json", by_alias=True)
    payload["manifest_version"] = "2"
    with pytest.raises((ValidationError, ValueError)):
        registry.ProviderRegistryEntry.model_validate(payload)
    payload = registry.registry_entries()[0].model_dump(mode="json", by_alias=True)
    payload["source_url"] = "https://github.com/xueyang-dev/HanClassStudio-evil/tree/v0.1.0/providers"
    with pytest.raises((ValidationError, ValueError)):
        registry.ProviderRegistryEntry.model_validate(payload)
    payload = registry.registry_entries()[0].model_dump(mode="json", by_alias=True)
    payload["manifest"]["unexpected_step_metadata"] = True
    with pytest.raises((ValidationError, ValueError)):
        registry.ProviderRegistryEntry.model_validate(payload)


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


def test_registry_install_state_flows_into_capability_contract(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)

    before = client.get("/api/settings/providers/capabilities")
    assert before.status_code == 200
    ocr_before = next(item for item in before.json() if item["provider_id"] == "hcs_mock_ocr")
    assert ocr_before["available"] is False
    assert ocr_before["configured"] is False
    assert ocr_before["install_state"] == "ready"
    assert ocr_before["install_actions"] == ["prepare_install"]

    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    assert client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    ).status_code == 200

    after = client.get("/api/settings/providers/capabilities")
    assert after.status_code == 200
    ocr_after = next(item for item in after.json() if item["provider_id"] == "hcs_mock_ocr")
    assert ocr_after["available"] is True
    assert ocr_after["configured"] is False
    assert ocr_after["install_state"] == "available"
    assert ocr_after["configuration_status"] == "configured"


def test_registry_configuration_state_flows_into_capability_contract_without_secret(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_llm/install/prepare").json()
    confirmed = client.post(
        "/api/providers/registry/hcs_mock_llm/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert confirmed.status_code == 200

    configuring = next(item for item in client.get("/api/settings/providers/capabilities").json() if item["provider_id"] == "hcs_mock_llm")
    assert configuring["available"] is False
    assert configuring["configuration_status"] == "missing"
    assert configuring["install_actions"] == ["configure", "view_logs"]

    secret = "capability-contract-secret"
    assert client.post("/api/providers/registry/hcs_mock_llm/configure", json={"values": {"api_key": secret}}).status_code == 200
    available = next(item for item in client.get("/api/settings/providers/capabilities").json() if item["provider_id"] == "hcs_mock_llm")
    assert available["available"] is True
    assert available["configured"] is False
    assert available["configuration_status"] == "configured"
    assert secret not in json.dumps(available)


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


@pytest.mark.parametrize("failed_step", ["run_health_check"])
def test_health_check_failure_enters_failed_not_available(tmp_path, monkeypatch, failed_step) -> None:
    client = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(registry, "EXECUTOR", registry.MockProviderExecutor(failed_step))
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    response = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_install_step_failed"
    state = client.get("/api/providers/registry/hcs_mock_ocr").json()["installation"]
    assert state["install_state"] == "failed"
    assert state["failure"]["code"] == "provider_install_step_failed"


def test_checksum_failure_enters_failed_not_available(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()

    class TamperingExecutor(registry.MockProviderExecutor):
        def execute(self, entry, plan) -> None:
            entry.checksum_sha256 = "0" * 64
            super().execute(entry, plan)

    monkeypatch.setattr(registry, "EXECUTOR", TamperingExecutor())
    response = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_checksum_mismatch"
    state = client.get("/api/providers/registry/hcs_mock_ocr").json()["installation"]
    assert state["install_state"] == "failed"
    assert state["failure"]["code"] == "provider_checksum_mismatch"
    assert state["install_state"] != "available"


def test_prepare_supersedes_old_plan_and_confirm_is_single_use(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    first = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    second = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()

    stale = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": first["plan"]["plan_id"], "confirmation_token": first["confirmation_token"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "provider_plan_stale"

    confirmed = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": second["plan"]["plan_id"], "confirmation_token": second["confirmation_token"]},
    )
    assert confirmed.status_code == 200

    repeated = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": second["plan"]["plan_id"], "confirmation_token": second["confirmation_token"]},
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "provider_plan_consumed"


def test_confirmation_rejects_tampered_plan_and_expired_plan(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    plans_path = storage.CONFIG_DIR / "provider_install_plans.json"
    plans = json.loads(plans_path.read_text(encoding="utf-8"))
    plan_id = prepared["plan"]["plan_id"]
    plans[plan_id]["plan"]["source_ref"] = "v9.9.9"
    plans_path.write_text(json.dumps(plans), encoding="utf-8")

    tampered = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": plan_id, "confirmation_token": prepared["confirmation_token"]},
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"]["code"] == "provider_plan_stale"

    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()
    plans = json.loads(plans_path.read_text(encoding="utf-8"))
    plan_id = prepared["plan"]["plan_id"]
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    plans[plan_id]["plan"]["expires_at"] = expired.isoformat()
    plans[plan_id]["expires_at"] = expired.isoformat()
    plans_path.write_text(json.dumps(plans), encoding="utf-8")

    expired_response = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": plan_id, "confirmation_token": prepared["confirmation_token"]},
    )
    assert expired_response.status_code == 409
    assert expired_response.json()["detail"]["code"] == "provider_plan_expired"


def test_concurrent_confirm_executes_once(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    prepared = registry.prepare_install("hcs_mock_ocr")
    request = registry.InstallConfirmRequest(plan_id=prepared.plan.plan_id, confirmation_token=prepared.confirmation_token)

    class CountingExecutor(registry.ProviderExecutor):
        calls = 0

        def execute(self, entry, plan) -> None:
            type(self).calls += 1

    executor = CountingExecutor()
    monkeypatch.setattr(registry, "EXECUTOR", executor)

    def confirm_once():
        try:
            registry.confirm_install("hcs_mock_ocr", request)
            return "success"
        except registry.ProviderRegistryError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: confirm_once(), range(2)))
    assert sorted(outcomes) == ["provider_plan_consumed", "success"]
    assert executor.calls == 1


def test_unexpected_executor_failure_is_persisted_as_failed_without_raw_error(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    prepared = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare").json()

    class RaisingExecutor(registry.ProviderExecutor):
        def execute(self, entry, plan) -> None:
            raise RuntimeError("Authorization: Bearer super-secret-value")

    monkeypatch.setattr(registry, "EXECUTOR", RaisingExecutor())
    response = client.post(
        "/api/providers/registry/hcs_mock_ocr/install/confirm",
        json={"plan_id": prepared["plan"]["plan_id"], "confirmation_token": prepared["confirmation_token"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_install_failed"
    assert "super-secret-value" not in response.text
    state = client.get("/api/providers/registry/hcs_mock_ocr").json()["installation"]
    assert state["install_state"] == "failed"
    assert state["failure"]["code"] == "provider_install_failed"
    assert "super-secret-value" not in (storage.CONFIG_DIR / "provider_install_logs.jsonl").read_text(encoding="utf-8")


def test_interrupted_install_is_recovered_as_retryable_failure(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    interrupted_at = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    registry._save_record(registry.ProviderInstallationRecord(
        provider_id="hcs_mock_ocr",
        capability="ocr",
        install_state="installing",
        install_started_at=interrupted_at,
        updated_at=interrupted_at,
    ))

    status = client.get("/api/providers/registry/hcs_mock_ocr").json()
    assert status["installation"]["install_state"] == "failed"
    assert status["installation"]["failure"]["code"] == "provider_install_interrupted"
    assert status["install_actions"] == ["retry_install", "view_logs"]


def test_concurrent_prepare_preserves_plans_for_each_provider(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)

    with ThreadPoolExecutor(max_workers=2) as pool:
        prepared = list(pool.map(registry.prepare_install, ["hcs_mock_ocr", "hcs_mock_llm"]))
    plans = json.loads((storage.CONFIG_DIR / "provider_install_plans.json").read_text(encoding="utf-8"))
    assert {item.plan.provider_id for item in prepared} <= {"hcs_mock_ocr", "hcs_mock_llm"}
    assert all(item.plan.plan_id in plans for item in prepared)


def test_rollback_audit_records_original_and_target_versions(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    registry._save_record(registry.ProviderInstallationRecord(
        provider_id="hcs_mock_ocr",
        capability="ocr",
        install_state="failed",
        installed_version="0.2.0",
        active_version="0.2.0",
        previous_version="0.1.0",
        configuration_status="configured",
        rollback_available=True,
        updated_at=datetime.now(timezone.utc).isoformat(),
    ))

    response = client.post("/api/providers/registry/hcs_mock_ocr/rollback")
    assert response.status_code == 200
    audit = client.get("/api/providers/registry/audit?provider_id=hcs_mock_ocr").json()[-1]
    assert audit["operation"] == "rollback"
    assert audit["previous_version"] == "0.2.0"
    assert audit["target_version"] == "0.1.0"
    assert audit["reason"] == "restore_previous_active_version"


def test_public_capability_values_redact_secret_like_keys(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    secret = "capability-token-secret"
    saved = client.put("/api/settings/providers", json={
        "capabilities": {"llm": {"providerId": "deterministic", "values": {"token": secret, "model": "deterministic-v1"}}},
    })
    assert saved.status_code == 200
    public = client.get("/api/settings/providers")
    assert public.status_code == 200
    assert secret not in public.text
    assert "token" not in public.json()["capabilities"]["llm"]["values"]
    assert public.json()["capabilities"]["llm"]["api_key_present"] is True


def test_redaction_handles_json_headers_and_url_secrets() -> None:
    text = '{"api_key":"json-secret","authorization":"Bearer header-secret","token":"field-secret"} https://example.test/?access_token=query-secret'
    redacted = registry._redact_sensitive_text(text)
    assert all(secret not in redacted for secret in ("json-secret", "header-secret", "field-secret", "query-secret"))
    assert redacted.count("[REDACTED]") >= 4


def test_corrupt_persistence_is_reported_without_overwriting_file(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    path = storage.CONFIG_DIR / "provider_installations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    response = client.get("/api/providers/registry")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_persistence_corrupt"
    assert path.read_text(encoding="utf-8") == "{not-json"


def test_corrupt_record_fails_closed_without_retry_overwrite(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    path = storage.CONFIG_DIR / "provider_installations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"hcs_mock_ocr": {"provider_id": "other-provider"}})
    path.write_text(original, encoding="utf-8")

    status = client.get("/api/providers/registry/hcs_mock_ocr")
    assert status.status_code == 200
    assert status.json()["installation"]["install_state"] == "failed"
    assert status.json()["installation"]["failure"]["code"] == "provider_state_corrupt"
    assert status.json()["install_actions"] == ["view_logs"]

    retry = client.post("/api/providers/registry/hcs_mock_ocr/install/prepare")
    assert retry.status_code == 400
    assert retry.json()["detail"]["code"] == "provider_state_corrupt"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["hcs_mock_ocr"] == {"provider_id": "other-provider"}


def test_inconsistent_available_record_is_failed_closed(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)
    registry._save_record(registry.ProviderInstallationRecord(
        provider_id="hcs_mock_ocr",
        capability="ocr",
        install_state="available",
        configuration_status="missing",
        active_version="0.1.0",
        updated_at=datetime.now(timezone.utc).isoformat(),
    ))

    status = client.get("/api/providers/registry/hcs_mock_ocr")
    assert status.status_code == 200
    installation = status.json()["installation"]
    assert installation["install_state"] == "failed"
    assert installation["failure"]["code"] == "provider_state_inconsistent"
    assert status.json()["install_actions"] == ["view_logs"]


def test_registry_failure_is_not_silently_removed_from_capability_contract(tmp_path, monkeypatch) -> None:
    client = _isolate(tmp_path, monkeypatch)

    def unavailable():
        raise registry.ProviderRegistryError("provider_registry_unavailable", "registry unavailable")

    monkeypatch.setattr(registry, "registry_status", unavailable)
    response = client.get("/api/settings/providers/capabilities")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_registry_unavailable"
