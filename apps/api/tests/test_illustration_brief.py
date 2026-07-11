from __future__ import annotations

from pydantic import ValidationError
import pytest

from hcs_api.illustration_brief import SOFT_FLAT_EDUCATIONAL_V1, compile_illustration_request
from hcs_api.models import IllustrationBrief, IllustrationRequest


def _brief() -> IllustrationBrief:
    return IllustrationBrief(
        concept="学生向老师问好",
        scene_purpose="primary teaching scenario",
        learner_age_range="8-14",
        learner_language_level="zero beginner",
        visual_subject="one student and one teacher",
        action="the student greets the teacher politely",
        environment="classroom doorway",
        number_of_people=2,
        cultural_context="contemporary Chinese school context",
        emotional_tone="warm and respectful",
        visual_hierarchy="the greeting gesture is immediately recognizable",
        forbidden_content=["school logo", "watermark"],
        text_policy="no_text",
        composition_guidance=["show both faces", "keep hands visible"],
        accessibility_requirements=["strong silhouette separation"],
        language_context={"target_language": "Chinese", "scaffolding_language": "English"},
        source_trace=["pilot:greetings"],
    )


def test_brief_compilation_is_deterministic_and_versioned() -> None:
    first = compile_illustration_request(_brief(), "greeting-1")
    second = compile_illustration_request(_brief(), "greeting-1")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.brief_version == "illustration_brief.v1"
    assert first.style_profile == "soft_flat_educational_v1"
    assert first.style_profile_version == SOFT_FLAT_EDUCATIONAL_V1.version


def test_prompt_contains_each_teaching_dimension_in_fixed_order() -> None:
    prompt = compile_illustration_request(_brief(), "greeting-1").scene_description
    expected = [
        "Teaching concept:", "Scene purpose:", "Learners:", "Visual subject:",
        "Action:", "Environment:", "People:", "Cultural context:",
        "Emotional tone:", "Visual hierarchy:", "Composition:",
        "Accessibility and clarity:", "Text policy:", "Style soft_flat_educational_v1@1:",
    ]
    assert [prompt.index(label) for label in expected] == sorted(prompt.index(label) for label in expected)


def test_default_profile_enforces_projection_clarity_and_no_embedded_text() -> None:
    request = compile_illustration_request(_brief(), "greeting-1")
    assert "suitable for classroom projection and learner worksheets" in request.scene_description
    assert "letters, words, or numbers" in request.negative_constraints
    assert request.negative_constraints.count("watermark") == 1


def test_language_and_source_trace_survive_compilation() -> None:
    request = compile_illustration_request(_brief(), "greeting-1")
    restored = IllustrationRequest.model_validate(request.model_dump(mode="json"))
    assert restored.language_context["target_language"] == "Chinese"
    assert restored.source_trace == ["pilot:greetings"]


def test_brief_rejects_impossible_people_count() -> None:
    with pytest.raises(ValidationError):
        IllustrationBrief.model_validate({**_brief().model_dump(), "number_of_people": 99})


def test_brief_contract_has_no_provider_fields() -> None:
    for field in ("provider", "model", "api_key", "endpoint_url"):
        assert field not in IllustrationBrief.model_fields
