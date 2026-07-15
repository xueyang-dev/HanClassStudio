from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import hcs_api.main as main
import hcs_api.storage as storage
from hcs_api.main import app
from hcs_api.models import LessonBlueprint, LessonProfile, LessonSlide, MediaRequirements, SourceMaterial


TOKEN = "codex-bridge-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(storage, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(storage, "PROJECTS_DIR", runtime / "projects")
    monkeypatch.setattr(storage, "CONFIG_DIR", runtime / "config")
    monkeypatch.setattr(storage, "PROVIDER_SETTINGS_PATH", runtime / "config" / "provider_settings.json")
    monkeypatch.setattr(main, "PROJECTS_DIR", runtime / "projects")
    return TestClient(app)


def _configure(client: TestClient, *capabilities: str) -> None:
    payload = {
        "capabilities": {
            capability: {
                "providerId": "codex_chatgpt" if capability == "llm" else "codex_image",
                "values": {"api_key": TOKEN, "model": "codex-test"},
            }
            for capability in capabilities
        }
    }
    response = client.put("/api/settings/providers", json=payload)
    assert response.status_code == 200
    assert TOKEN not in response.text


def _heartbeat(client: TestClient, *capabilities: str) -> None:
    response = client.post(
        "/api/providers/codex-bridge/heartbeat",
        headers=AUTH,
        json={"capabilities": list(capabilities)},
    )
    assert response.status_code == 200


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 36), (220, 80, 50)).save(output, format="PNG")
    return output.getvalue()


def test_catalog_requires_configuration_and_live_heartbeat(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    unconfigured = client.get("/api/settings/providers/capabilities").json()
    for provider_id in ("codex_chatgpt", "codex_image"):
        descriptor = next(item for item in unconfigured if item["provider_id"] == provider_id)
        assert descriptor["configured"] is False and descriptor["available"] is False
        assert descriptor["unavailable_reason"]

    _configure(client, "llm", "image")

    before = client.get("/api/settings/providers/capabilities").json()
    llm = next(item for item in before if item["provider_id"] == "codex_chatgpt")
    image = next(item for item in before if item["provider_id"] == "codex_image")
    assert llm["configured"] is True and llm["available"] is False
    assert image["configured"] is True and image["available"] is False
    assert "heartbeat" in llm["unavailable_reason"].lower()

    _heartbeat(client, "llm", "image")
    after = client.get("/api/settings/providers/capabilities").json()
    assert next(item for item in after if item["provider_id"] == "codex_chatgpt")["available"] is True
    assert next(item for item in after if item["provider_id"] == "codex_image")["available"] is True
    assert TOKEN not in json.dumps(after)
    assert TOKEN not in (storage.CONFIG_DIR / "codex_bridge_sessions.json").read_text(encoding="utf-8")


def test_blueprint_job_is_schema_validated_and_consumed_on_retry(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _configure(client, "llm")
    _heartbeat(client, "llm")
    project_id = "codexblueprint"
    storage.ensure_project(project_id)
    storage.write_model(project_id, "source_material.json", SourceMaterial(
        original_filename="lesson.pdf", source_type="pdf", title="你好",
    ))
    storage.write_model(project_id, "lesson_profile.json", LessonProfile(
        lesson_title="你好", learner_level="Beginner", target_audience="Adults",
    ))
    storage.set_profile_state(project_id, "confirmed")

    requested = client.post(f"/api/projects/{project_id}/blueprint")
    assert requested.status_code == 409
    assert requested.json()["detail"]["code"] == "codex_agent_action_required"
    jobs = client.get("/api/providers/codex-bridge/jobs?state=pending", headers=AUTH)
    assert jobs.status_code == 200 and len(jobs.json()) == 1
    job = jobs.json()[0]
    assert job["capability"] == "llm" and job["operation"] == "blueprint"
    assert TOKEN not in json.dumps(job)

    invalid = client.post(
        f"/api/providers/codex-bridge/jobs/{job['job_id']}/complete-blueprint",
        headers=AUTH,
        json={"lesson_title": "invalid", "slides": "not-a-list"},
    )
    assert invalid.status_code == 400

    blueprint = LessonBlueprint(
        lesson_title="第一课：你好！",
        slides=[LessonSlide(id=1, slide_type="CoverSlide", layout_variant="hero", title="你好")],
    )
    completed = client.post(
        f"/api/providers/codex-bridge/jobs/{job['job_id']}/complete-blueprint",
        headers=AUTH,
        json=blueprint.model_dump(mode="json"),
    )
    assert completed.status_code == 200
    generated = client.post(f"/api/projects/{project_id}/blueprint")
    assert generated.status_code == 200
    assert generated.json()["lesson_blueprint"]["lesson_title"] == "第一课：你好！"


def test_image_job_persists_reviewable_generated_candidate(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _configure(client, "image")
    _heartbeat(client, "image")
    project_id = "codeximage"
    storage.ensure_project(project_id)
    storage.write_model(project_id, "lesson_blueprint.json", LessonBlueprint(
        lesson_title="第一课：你好！",
        slides=[LessonSlide(
            id=1,
            slide_type="CoverSlide",
            layout_variant="hero",
            title="你好",
            media_requirements=MediaRequirements(
                image_key="greeting-scene",
                image_prompt="Two adult learners greeting in a bright classroom",
                media_kind="raster",
            ),
        )],
    ))

    requested = client.post(f"/api/projects/{project_id}/media")
    assert requested.status_code == 409
    job = client.get("/api/providers/codex-bridge/jobs?state=pending", headers=AUTH).json()[0]
    assert job["capability"] == "image"

    completed = client.post(
        f"/api/providers/codex-bridge/jobs/{job['job_id']}/complete-image",
        headers=AUTH,
        files={"file": ("greeting.png", _png(), "image/png")},
    )
    assert completed.status_code == 200
    duplicate = client.post(
        f"/api/providers/codex-bridge/jobs/{job['job_id']}/complete-image",
        headers=AUTH,
        files={"file": ("replacement.png", _png(), "image/png")},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"]["code"] == "codex_bridge_job_completed"
    generated = client.post(f"/api/projects/{project_id}/media")
    assert generated.status_code == 200
    asset = generated.json()["asset_manifest"]["images"][0]
    assert asset["generation"]["provider"] == "codex_image"
    assert asset["review_state"] == "pending_review"
    assert asset["selected_candidate_id"].startswith("generated-")
    assert (storage.ensure_project(project_id) / asset["path"]).is_file()


def test_bridge_rejects_unknown_token(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _configure(client, "llm")
    response = client.post(
        "/api/providers/codex-bridge/heartbeat",
        headers={"Authorization": "Bearer wrong"},
        json={"capabilities": ["llm"]},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "codex_bridge_unauthorized"
