from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .blueprint_utils import duplicate_component_id_messages
from .components import load_component_registry
from .models import AgentPackage, AgentValidation, LessonBlueprint
from .storage import ensure_project, read_json, write_text


AGENT_TASK_PATH = "agent/AGENT_TASK.md"
AGENT_RULES_PATH = "agent/AGENT_RULES.md"


def generate_agent_package(project_id: str) -> AgentPackage:
    root = ensure_project(project_id)
    spec_lock = read_json(project_id, "specs/spec_lock.json")
    route = spec_lock.get("route", "pending") if isinstance(spec_lock, dict) else "pending"
    mode = spec_lock.get("generation_mode", "pending") if isinstance(spec_lock, dict) else "pending"
    task_text = _build_task_text(project_id, route, mode)
    rules_text = _build_rules_text()
    write_text(project_id, AGENT_TASK_PATH, task_text)
    write_text(project_id, AGENT_RULES_PATH, rules_text)
    return AgentPackage(
        project_id=project_id,
        task_path=str(root / AGENT_TASK_PATH),
        rules_path=str(root / AGENT_RULES_PATH),
        task_text=task_text,
        rules_text=rules_text,
    )


def validate_agent_output(project_id: str) -> AgentValidation:
    root = ensure_project(project_id)
    blocking: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    required = [
        "specs/lesson_spec.md",
        "specs/spec_lock.json",
        "blueprints/lesson_blueprint.json",
        "blueprints/interaction_plan.json",
        "blueprints/media_plan.json",
    ]
    for relative in required:
        path = root / relative
        if path.exists():
            passed.append(f"{relative} exists")
        else:
            blocking.append(f"Missing {relative}")

    spec_lock = _read_json_artifact(root, "specs/spec_lock.json", blocking)
    if isinstance(spec_lock, dict):
        passed.append("spec_lock.json parses as JSON")
        for key in ["schema", "project_id", "route", "generation_mode", "components", "quality"]:
            if key not in spec_lock:
                blocking.append(f"spec_lock.json missing {key}")
    blueprint = _read_blueprint(root, blocking)
    if blueprint:
        passed.append("lesson_blueprint.json matches schema")
        _validate_components(blueprint, spec_lock if isinstance(spec_lock, dict) else {}, blocking, warnings, passed)

    for relative in ["blueprints/interaction_plan.json", "blueprints/media_plan.json"]:
        if _read_json_artifact(root, relative, blocking) is not None:
            passed.append(f"{relative} parses as JSON")

    if not (root / "courseware" / "lesson.html").exists():
        warnings.append("courseware/lesson.html is not present yet; run render after agent edits")
    if not (root / "quality" / "quality_report.json").exists():
        warnings.append("quality_report.json is not present yet; run quality gate after render")

    state = "blocked" if blocking else "warning" if warnings else "pass"
    return AgentValidation(project_id=project_id, state=state, blocking=blocking, warnings=warnings, passed=passed)


def _build_task_text(project_id: str, route: str, mode: str) -> str:
    return f"""# HanClassStudio Agent Task

Project workspace:

`runtime/projects/{project_id}`

Current route: `{route}`
Generation mode: `{mode}`

Read first:

1. `AGENTS.md`
2. `skills/hanclassstudio/SKILL.md`
3. `skills/hanclassstudio/references/artifact-ownership.md`
4. `skills/hanclassstudio/references/component-registry.md`
5. `skills/hanclassstudio/references/scaffolding-language.md`

Allowed edit targets:

- `specs/lesson_spec.md`
- `specs/spec_lock.json`
- `blueprints/lesson_blueprint.json`
- `blueprints/interaction_plan.json`
- `blueprints/media_plan.json`
- `assets/data/asset_manifest.json` only when media references change

After editing, ask HanClassStudio to validate agent output, then render, run the quality gate, and export only if quality allows it.
"""


def _build_rules_text() -> str:
    return """# HanClassStudio Agent Rules

- Follow `AGENTS.md` and `skills/hanclassstudio/SKILL.md`.
- Keep the pipeline strictly serial.
- Do not edit `uploads/`, `courseware/lesson.html`, or `exports/`.
- Use only components from `courseware/components/registry.json`.
- Chinese is always the target language.
- The scaffolding language supports comprehension only; it must not replace Chinese input or output.
- Do not bypass the quality gate.
"""


def _read_json_artifact(root: Path, relative: str, blocking: list[str]) -> Any | None:
    path = root / relative
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blocking.append(f"{relative} is invalid JSON: {exc.msg}")
        return None


def _read_blueprint(root: Path, blocking: list[str]) -> LessonBlueprint | None:
    path = root / "blueprints" / "lesson_blueprint.json"
    if not path.exists():
        return None
    try:
        return LessonBlueprint.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        blocking.append(f"lesson_blueprint.json schema invalid: {exc.errors()[0]['msg']}")
        return None


def _validate_components(
    blueprint: LessonBlueprint,
    spec_lock: dict[str, Any],
    blocking: list[str],
    warnings: list[str],
    passed: list[str],
) -> None:
    registry = load_component_registry()
    components_lock = spec_lock.get("components") if isinstance(spec_lock.get("components"), dict) else {}
    allowed = components_lock.get("allowed") if isinstance(components_lock, dict) else None
    allowed_components = set(allowed if isinstance(allowed, list) else registry.keys())
    component_issue_count = len(blocking)
    blocking.extend(duplicate_component_id_messages(blueprint))
    for slide in blueprint.slides:
        for component in slide.components:
            if component.component_type not in registry:
                blocking.append(f"Unsupported component {component.component_type}")
                continue
            if component.component_type not in allowed_components:
                blocking.append(f"Component {component.component_type} is not allowed by spec_lock")
            config = registry[component.component_type]
            if config.get("experimental"):
                warnings.append(f"Component {component.component_type} is experimental")
            for key in config.get("requires", []):
                if key not in component.data or component.data[key] in ("", None, []):
                    blocking.append(f"{component.id} missing required data field {key}")
    if len(blocking) == component_issue_count:
        passed.append("All blueprint components are registry-compatible")
