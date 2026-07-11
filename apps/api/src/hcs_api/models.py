from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


GenerationMode = Literal["faithful", "guided_redesign", "reimagined"]
SourceType = Literal["pptx", "pdf", "unknown"]
QualityState = Literal["pass", "warning", "blocked"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TextBlock(BaseModel):
    id: str
    text: str
    kind: str = "body"
    left: float | None = None
    top: float | None = None
    width: float | None = None
    height: float | None = None


class ImageBlock(BaseModel):
    id: str
    path: str
    filename: str
    width: float | None = None
    height: float | None = None
    description: str = ""


class SourcePage(BaseModel):
    page_number: int
    title: str = ""
    text_blocks: list[TextBlock] = Field(default_factory=list)
    images: list[ImageBlock] = Field(default_factory=list)
    notes: str = ""
    ocr_text: str = ""


class SourceMaterial(BaseModel):
    source_type: SourceType
    original_filename: str
    created_at: str = Field(default_factory=utc_now_iso)
    pages: list[SourcePage] = Field(default_factory=list)


class LessonProfile(BaseModel):
    lesson_title: str = "未命名中文课"
    subject: str = "International Chinese"
    learner_level: str = "Beginner"
    target_students: str = "International Chinese learners"
    scaffolding_language: str = "English"
    lesson_type: str = "New lesson"
    generation_mode: GenerationMode = "guided_redesign"
    estimated_duration: str = "45 minutes"


class ContentBlock(BaseModel):
    id: str
    block_type: str = "text"
    text: str = ""
    scaffolding_text: str = ""


class SlideComponent(BaseModel):
    id: str
    component_type: str
    title: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class MediaRequirements(BaseModel):
    image_prompt: str | None = None
    image_key: str | None = None
    # Discriminator between a raster image (placeholder or provider PNG) and a
    # hand-written, offline-safe vector illustration driven by the locked contract.
    media_kind: Literal["raster", "svg_illustration"] = "raster"
    svg_style: str | None = None
    # Illustration planning controls (consumed by the SVG illustration pipeline).
    illustration_level: Literal["icon", "scene"] | None = None
    text_policy: Literal["no_text", "semantic_symbols_only", "short_environment_label"] | None = None
    scene_type: str | None = None
    audio_text: str | None = None
    audio_key: str | None = None
    video_scene_prompt: str | None = None
    video_key: str | None = None


class LessonSlide(BaseModel):
    id: int
    slide_type: str
    layout_variant: str
    title: str
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    components: list[SlideComponent] = Field(default_factory=list)
    media_requirements: MediaRequirements = Field(default_factory=MediaRequirements)


class LessonBlueprint(BaseModel):
    route_hint: str = ""
    lesson_title: str = ""
    objectives: list[str] = Field(default_factory=list)
    key_vocabulary: list[dict[str, str]] = Field(default_factory=list)
    grammar_points: list[str] = Field(default_factory=list)
    slides: list[LessonSlide] = Field(default_factory=list)


class IllustrationRequest(BaseModel):
    """Provider-neutral request for experimental raster illustration generation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    concept: str = ""
    scene_description: str = ""
    illustration_role: str = "classroom_visual"
    style_profile: str = "soft_flat_educational_v1"
    aspect_ratio: str = "16:9"
    width: int | None = None
    height: int | None = None
    negative_constraints: list[str] = Field(default_factory=list)
    seed: int | None = None
    candidate_count: int = 1
    language_context: dict[str, str] = Field(default_factory=dict)
    source_trace: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GeneratedImage(BaseModel):
    """Local-only provenance for one successfully persisted raster illustration."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    local_path: str
    mime_type: str
    width: int | None = None
    height: int | None = None
    prompt: str
    revised_prompt: str | None = None
    seed: int | None = None
    content_hash: str
    generated_at: str = Field(default_factory=utc_now_iso)
    provider_request_id: str | None = None
    source_trace: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


RasterFailureStage = Literal[
    "request_build",
    "provider_generation",
    "provider_response_parse",
    "remote_asset_download",
    "mime_validation",
    "local_persist",
    "manifest_record",
    "fallback",
]
RasterFailureCategory = Literal[
    "configuration",
    "authentication",
    "rate_limit",
    "provider_generation",
    "generation_timeout",
    "response_shape",
    "download_forbidden",
    "download_timeout",
    "invalid_mime",
    "local_write",
    "network",
    "unknown",
]


class GeneratedImageFailure(BaseModel):
    """Structured provider-neutral provenance for a raster fallback."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    stage: RasterFailureStage
    category: RasterFailureCategory
    message: str
    status_code: int | None = None
    retry_count: int = 0
    provider_request_id: str | None = None
    occurred_at: str = Field(default_factory=utc_now_iso)
    source_trace: list[str] = Field(default_factory=list)


class AssetFile(BaseModel):
    id: str
    kind: Literal["image", "audio", "video", "font", "data"]
    path: str
    prompt: str = ""
    text: str = ""
    media_request_id: str | None = None
    # Explicit generation provenance; historical manifests deserialize empty.
    origin_media_requirement_ids: list[str] = Field(default_factory=list)
    mime_type: str | None = None
    content_hash: str | None = None
    generation: GeneratedImage | None = None
    generation_failure: GeneratedImageFailure | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None


class AssetManifest(BaseModel):
    images: list[AssetFile] = Field(default_factory=list)
    audio: list[AssetFile] = Field(default_factory=list)
    video: list[AssetFile] = Field(default_factory=list)
    fonts: list[AssetFile] = Field(default_factory=list)


class QualityReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.quality_report.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    missing_titles: list[str] = Field(default_factory=list)
    missing_audio: list[str] = Field(default_factory=list)
    missing_images: list[str] = Field(default_factory=list)
    invalid_interactions: list[str] = Field(default_factory=list)
    empty_prompts: list[str] = Field(default_factory=list)
    resource_errors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.blocking) + len(self.warnings)


class ProjectState(BaseModel):
    project_id: str
    status: str
    route: str | None = None
    quality_state: QualityState | None = None
    source_material: SourceMaterial | None = None
    lesson_profile: LessonProfile | None = None
    lesson_blueprint: LessonBlueprint | None = None
    asset_manifest: AssetManifest | None = None
    quality_report: QualityReport | None = None
    preview_url: str | None = None
    export_url: str | None = None


class ArtifactEntry(BaseModel):
    path: str
    exists: bool
    size: int | None = None
    updated_at: str | None = None
    artifact_type: str


class ArtifactGroup(BaseModel):
    name: str
    items: list[ArtifactEntry] = Field(default_factory=list)


class ArtifactTree(BaseModel):
    project_id: str
    groups: list[ArtifactGroup] = Field(default_factory=list)
    spec_lock: dict[str, Any] | None = None


class AgentPackage(BaseModel):
    project_id: str
    task_path: str
    rules_path: str
    task_text: str
    rules_text: str


class AgentValidation(BaseModel):
    project_id: str
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)


class EditablePptxExportResponse(BaseModel):
    filename: str
    download_url: str
    export_type: Literal["pptx_editable"] = "pptx_editable"
    editable: bool = True
    interaction_policy: Literal["classroom_static_activity"] = "classroom_static_activity"
    quality_state: QualityState | None = None


class LLMProviderSettings(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4.1-mini"


class ImageProviderSettings(BaseModel):
    provider: str = "placeholder"
    endpoint_url: str = ""
    api_key: str = ""
    model: str = "placeholder-svg"


class AudioProviderSettings(BaseModel):
    provider: str = "placeholder"
    endpoint_url: str = ""
    api_key: str = ""
    model: str = "placeholder-tone"
    voice: str = "default"


class ProviderSettings(BaseModel):
    llm: LLMProviderSettings = Field(default_factory=LLMProviderSettings)
    image: ImageProviderSettings = Field(default_factory=ImageProviderSettings)
    audio: AudioProviderSettings = Field(default_factory=AudioProviderSettings)

QualityState = Literal["pass", "warning", "blocked"]
LearnerLevel = Literal["zero_beginner", "beginner", "elementary", "intermediate"]
RouteHint = Literal["greeting_lesson", "vocabulary_lesson", "dialogue_lesson", "character_lesson", "grammar_pattern_lesson", "mixed_lesson"]
StandardScheme = Literal["HSK", "CEFR", "JLPT", "TOPIK", "ACTFL", "custom"]


class TeachingCandidates(BaseModel):
    schema_: str = Field(default="hanclassstudio.teaching_candidates.v1", alias="schema")
    route_hint: RouteHint = "mixed_lesson"
    core_vocabulary: list[dict[str, str]] = Field(default_factory=list)
    secondary_vocabulary: list[dict[str, str]] = Field(default_factory=list)
    noise_candidates: list[str] = Field(default_factory=list)
    grammar_candidates: list[dict[str, str]] = Field(default_factory=list)
    dialogue_candidates: list[dict[str, str]] = Field(default_factory=list)
    character_candidates: list[str] = Field(default_factory=list)
    classroom_task_candidates: list[str] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list)


class ClassroomQualityReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.classroom_quality_report.v1", alias="schema")
    state: QualityState = "pass"
    content_leaks: list[str] = Field(default_factory=list)
    scaffold_failures: list[str] = Field(default_factory=list)
    pinyin_issues: list[str] = Field(default_factory=list)
    vocabulary_noise: list[str] = Field(default_factory=list)
    grammar_mismatch: list[str] = Field(default_factory=list)
    debug_artifacts: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class LearnerModel(BaseModel):
    schema_: str = Field(default="hanclassstudio.learner_model.v1", alias="schema")
    target_language: str = "Chinese"
    scaffold_language: str = "English"
    level: LearnerLevel = "zero_beginner"
    age_group: str = "11-13"
    known_words: list[str] = Field(default_factory=list)
    known_patterns: list[str] = Field(default_factory=list)
    known_scripts: list[str] = Field(default_factory=list)
    new_word_limit_per_slide: int = 2
    new_word_limit_per_lesson: int = 10
    max_sentence_length: int = 12
    require_scaffold_meaning: bool = True
    require_usage_scene: bool = True
    allow_meta_language: bool = False
    classroom_instruction_policy: str = "scaffold_first"


class LanguageItem(BaseModel):
    id: str
    item_type: Literal["word", "phrase", "pattern", "character", "function"] = "word"
    target_form: str = ""
    pronunciation: str = ""
    scaffold_meaning: str = ""
    usage_context: str = ""
    example: str = ""
    example_gloss: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    difficulty: int = 1
    source_evidence: str = ""


class InputSequenceItem(BaseModel):
    order: int
    language_item_id: str
    slide_id: int | None = None
    presentation_type: str = "vocabulary"
    notes: str = ""


class InputSequencePlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.input_sequence_plan.v1", alias="schema")
    learner_level: LearnerLevel = "zero_beginner"
    items: list[InputSequenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComprehensibilityReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.comprehensibility_report.v1", alias="schema")
    state: QualityState = "pass"
    new_word_violations: list[str] = Field(default_factory=list)
    missing_meaning: list[str] = Field(default_factory=list)
    unknown_example_words: list[str] = Field(default_factory=list)
    meta_labels_exposed: list[str] = Field(default_factory=list)
    missing_usage_context: list[str] = Field(default_factory=list)
    target_scaffold_mixing: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class SourceLessonProfile(BaseModel):
    schema_: str = Field(default="hanclassstudio.source_lesson_profile.v1", alias="schema")
    source_title: str = ""
    detected_target_language: str = "Chinese"
    lesson_topic: str = ""
    visible_text_units: list[str] = Field(default_factory=list)
    dialogue_units: list[str] = Field(default_factory=list)
    vocabulary_units: list[str] = Field(default_factory=list)
    grammar_units: list[str] = Field(default_factory=list)
    exercise_units: list[str] = Field(default_factory=list)
    teacher_instruction_units: list[str] = Field(default_factory=list)
    noise_units: list[str] = Field(default_factory=list)


class DifficultyProfile(BaseModel):
    schema_: str = Field(default="hanclassstudio.difficulty_profile.v1", alias="schema")
    estimated_level: LearnerLevel = "zero_beginner"
    standard_scheme: StandardScheme = "HSK"
    standard_level: str = "HSK1"
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    source_scope_notes: str = ""


class LanguageInventory(BaseModel):
    schema_: str = Field(default="hanclassstudio.language_inventory.v1", alias="schema")
    known_items: list[str] = Field(default_factory=list)
    lesson_target_items: list[str] = Field(default_factory=list)
    lesson_support_items: list[str] = Field(default_factory=list)
    off_level_items: list[str] = Field(default_factory=list)
    teacher_only_items: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)


class AllowedSlideText(BaseModel):
    slide_id: int
    allowed_target_text: list[str] = Field(default_factory=list)
    allowed_scaffold_text: list[str] = Field(default_factory=list)
    allowed_pronunciation: list[str] = Field(default_factory=list)
    forbidden_target_text: list[str] = Field(default_factory=list)
    teacher_only_text: list[str] = Field(default_factory=list)
    max_new_items: int = 1
    output_task_allowed: bool = False


class AllowedTextPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.allowed_text_plan.v1", alias="schema")
    slides: list[AllowedSlideText] = Field(default_factory=list)


class OffLevelItem(BaseModel):
    text: str
    location: str
    reason: str
    severity: str = "warning"


class OffLevelReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.off_level_report.v1", alias="schema")
    state: QualityState = "pass"
    unknown_target_items: list[OffLevelItem] = Field(default_factory=list)
    off_level_items: list[OffLevelItem] = Field(default_factory=list)
    unsupported_new_items: list[OffLevelItem] = Field(default_factory=list)
    teacher_text_leaks: list[OffLevelItem] = Field(default_factory=list)
    scaffold_missing: list[OffLevelItem] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


PedagogicalIntentKind = Literal[
    "introduce_vocabulary", "introduce_polite_vs_neutral_form", "guided_dialogue",
    "listening_check", "simple_recall", "role_play", "character_form_demo",
    "grammar_contrast", "scene_match", "audio_repeat",
]

PedagogicalActivityType = Literal[
    "choose", "repeat_audio", "match_image", "scene_choose", "recall",
    "drag_sentence", "sort", "listen_choose", "scene_match_game",
]

ZB_FORBIDDEN_ACTIVITIES = {"drag_sentence", "sort"}
ZB_FORBIDDEN_LABELS = {"礼貌对比", "拖拽组句", "答案提示", "Teacher answer", "组句"}


class TeacherFacingBlock(BaseModel):
    intent: str = ""
    title: str = ""
    instruction: str = ""
    notes: str = ""


class LearnerFacingBlock(BaseModel):
    target_text: str = ""
    scaffold_text: str = ""
    visual_cue: str = ""
    audio_key: str = ""


class PedagogicalIntent(BaseModel):
    slide_id: int = 0
    intent: PedagogicalIntentKind = "introduce_vocabulary"
    teacher_title: str = ""
    learner_title: str = ""
    activity_type: PedagogicalActivityType = "choose"
    teacher_blocks: list[TeacherFacingBlock] = Field(default_factory=list)
    learner_blocks: list[LearnerFacingBlock] = Field(default_factory=list)
    level: LearnerLevel = "zero_beginner"
    requires_image: bool = True
    requires_audio: bool = False


class SlideRealization(BaseModel):
    slide_id: int = 0
    intent: PedagogicalIntentKind = "introduce_vocabulary"
    learner_title: str = ""
    activity_type: str = ""
    learner_visible_blocks: list[LearnerFacingBlock] = Field(default_factory=list)
    teacher_only_blocks: list[TeacherFacingBlock] = Field(default_factory=list)
    meta_labels_detected: list[str] = Field(default_factory=list)
    blocked: bool = False


class ActivityPolicy(BaseModel):
    level: LearnerLevel = "zero_beginner"
    forbidden_activities: list[str] = Field(default_factory=lambda: list(ZB_FORBIDDEN_ACTIVITIES))
    forbidden_labels: list[str] = Field(default_factory=lambda: list(ZB_FORBIDDEN_LABELS))
    max_instruction_length: int = 20
    prefer_visual: bool = True
    prefer_audio: bool = True


class PresentationPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.presentation_plan.v1", alias="schema")
    level: LearnerLevel = "zero_beginner"
    realizations: list[SlideRealization] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RealizationReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.realization_report.v1", alias="schema")
    state: QualityState = "pass"
    meta_labels_exposed: list[str] = Field(default_factory=list)
    forbidden_activities: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)


# ── Traditional PPTX Deck models ──

TraditionalLayout = Literal[
    "cover_title", "objectives_cards", "single_item_focus",
    "two_card_contrast", "listen_choose", "dialogue_bubbles",
    "match_pairs", "summary_cards", "generic_content",
]


class PptxDeckSlide(BaseModel):
    slide_id: int = 0
    slide_purpose: str = ""
    traditional_layout: TraditionalLayout = "generic_content"
    main_focus: str = ""
    target_text: str = ""
    pronunciation: str = ""
    scaffold_text: str = ""
    usage_context: str = ""
    teacher_notes: list[str] = Field(default_factory=list)
    speaker_notes: list[str] = Field(default_factory=list)
    visual_hint: str = ""
    audio_key: str = ""
    image_key: str = ""
    binding_id: str = ""
    activity_id: str = ""
    evidence_id: str = ""
    evidence_claim: str = ""
    expected_behavior: dict = Field(default_factory=dict)
    failure_action: dict = Field(default_factory=dict)


class PptxDeckPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.pptx_deck_plan.v1", alias="schema")
    target_language: str = ""
    scaffold_language: str = ""
    learner_level: str = "zero_beginner"
    slides: list[PptxDeckSlide] = Field(default_factory=list)


class ScaffoldLanguageReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.scaffold_language_report.v1", alias="schema")
    state: QualityState = "pass"
    scaffold_mismatches: list[str] = Field(default_factory=list)
    missing_glossary: list[str] = Field(default_factory=list)
    target_scaffold_mixing: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)


class LearnerFacingTextReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.learner_facing_text_report.v1", alias="schema")
    state: QualityState = "pass"
    forbidden_labels: list[str] = Field(default_factory=list)
    off_level_target: list[str] = Field(default_factory=list)
    teacher_only_leakage: list[str] = Field(default_factory=list)
    role_violations: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)


# ── Courseware Review Agent models ──

ReviewDimension = Literal["suitable", "workable", "sustainable", "usable"]
ReviewSeverity = Literal["info", "warning", "blocked"]


class ReviewFinding(BaseModel):
    id: str = ""
    slide_id: int = 0
    dimension: ReviewDimension = "suitable"
    severity: ReviewSeverity = "warning"
    message: str = ""
    evidence: str = ""
    suggested_action: str = ""


class CoursewareReviewReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.courseware_review.v1", alias="schema")
    state: QualityState = "pass"
    scores: dict[str, int] = Field(default_factory=lambda: {"suitable": 0, "workable": 0, "sustainable": 0, "usable": 0})
    findings: list[ReviewFinding] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    summary: str = ""


class RevisionPatch(BaseModel):
    slide_id: int = 0
    operation: str = "rewrite_text"
    constraints: dict[str, list[str]] = Field(default_factory=lambda: {
        "allowed_target_text": [],
        "forbidden_text": [],
        "forbidden_components": [],
        "preferred_activity_types": [],
        "preferred_layouts": [],
    })
    reason: str = ""


class RevisionPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.revision_plan.v1", alias="schema")
    target_artifact: str = ""
    patches: list[RevisionPatch] = Field(default_factory=list)
    rationale: str = ""
    priority: int = 1


class RenderedArtifactReview(BaseModel):
    schema_: str = Field(default="hanclassstudio.rendered_artifact_review.v1", alias="schema")
    state: QualityState = "pass"
    forbidden_text_leaks: list[dict] = Field(default_factory=list)
    teacher_only_leaks: list[dict] = Field(default_factory=list)
    component_labels: list[dict] = Field(default_factory=list)
    answer_visible_on_slide: list[dict] = Field(default_factory=list)
    missing_notes: list[dict] = Field(default_factory=list)
    layout_fallback: list[dict] = Field(default_factory=list)
    target_scaffold_mixing: list[dict] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)


# ── Presentation binding models ──

PresentationMode = Literal[
    "html_interactive",
    "html_classroom",
    "pptx_classroom",
    "speaker_notes",
    "teacher_observation",
]


class PresentationBinding(BaseModel):
    binding_id: str = ""
    activity_id: str = ""
    evidence_id: str = ""
    slide_id: int = 0
    component_id: str | None = None
    presentation_modes: list[PresentationMode] = Field(default_factory=list)
    binding_confidence: float = 0.0
    binding_reason: str = ""
    teacher_note_policy: str = ""
    created_by: str = "binding_builder"


class PresentationBindingPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.presentation_bindings.v1", alias="schema")
    bindings: list[PresentationBinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    state: QualityState = "pass"


class PresentationReadinessReport(BaseModel):
    """Composed gate between resolved presentation bindings and renderers."""

    schema_: str = Field(default="hanclassstudio.presentation_readiness.v1", alias="schema")
    state: QualityState = "pass"
    binding_strategy: Literal["legacy_resolved", "abstract"] = "legacy_resolved"
    deprecated_blueprint_fields: list[str] = Field(default_factory=list)
    authority_violations: list[str] = Field(default_factory=list)
    invalid_bindings: list[str] = Field(default_factory=list)
    missing_activity_bindings: list[str] = Field(default_factory=list)
    teacher_channel_leaks: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class V2CutoverReadinessReport(BaseModel):
    """Aggregate, diagnostic-only route decision for the internal v2 HTML experiment."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.v2_cutover_readiness.v1", alias="schema")
    state: QualityState = "warning"
    experiment_eligible: bool = False
    selected_route: Literal["v2_internal_html", "legacy"] = "legacy"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    learner_facing_modes: list[str] = Field(default_factory=list)
    approved_modes: list[str] = Field(default_factory=lambda: ["listening_choice", "matching_response"])
    conditional_modes: list[str] = Field(default_factory=lambda: ["guided_response", "role_play_response"])
    unsupported_modes: list[str] = Field(default_factory=list)
    missing_artifacts: list[str] = Field(default_factory=list)
    stale_artifacts: list[str] = Field(default_factory=list)
    required_gate_states: dict[str, str] = Field(default_factory=dict)
    trace_coverage: float = 0.0
    teacher_leakage_findings: list[str] = Field(default_factory=list)
    content_complete: bool = False
    media_complete: bool = False
    adapter_compatible: bool = False
    structural_parity_state: str = ""
    courseware_review_state: str | None = None
    renderer_contract_preserved: bool = False
    production_blueprint_unchanged: bool = True
    whole_lesson_routing: bool = False
    fallback_reason: str = ""
    forced: bool = False
    pre_render_eligible: bool = False
    rendered_output_state: QualityState | None = None
    experiment_run_healthy: bool = False
    input_fingerprint: str = ""
    artifact_mtimes_ns: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class V2RenderedInteractionResult(BaseModel):
    """A runtime observation for one rendered learner interaction."""

    model_config = ConfigDict(extra="forbid")

    presentation_unit_id: str
    presentation_mode: str
    passed: bool
    details: list[str] = Field(default_factory=list)


class V2BrowserRuntimeObservation(BaseModel):
    """Optional, externally collected browser evidence for an internal v2 render."""

    model_config = ConfigDict(extra="forbid")

    source_input_fingerprint: str
    page_load_success: bool
    console_errors: list[str] = Field(default_factory=list)
    uncaught_exceptions: list[str] = Field(default_factory=list)
    interaction_results: list[V2RenderedInteractionResult] = Field(default_factory=list)
    responsive_findings: list[str] = Field(default_factory=list)
    accessibility_findings: list[str] = Field(default_factory=list)
    screenshot_artifacts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class V2RenderedOutputReviewReport(BaseModel):
    """Diagnostic-only review of the generated internal v2 learner HTML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.v2_rendered_output_review.v1", alias="schema")
    state: QualityState = "warning"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    internal_html_path: str = "courseware/lesson_v2_internal.html"
    legacy_html_path: str = "courseware/lesson.html"
    render_manifest_path: str = "courseware/render_manifest_v2_internal.json"
    browser_runtime_available: bool = False
    page_load_success: bool = False
    console_errors: list[str] = Field(default_factory=list)
    uncaught_exceptions: list[str] = Field(default_factory=list)
    missing_assets: list[str] = Field(default_factory=list)
    broken_links: list[str] = Field(default_factory=list)
    learner_visible_modes: list[str] = Field(default_factory=list)
    expected_interactions: list[str] = Field(default_factory=list)
    discovered_interactions: list[str] = Field(default_factory=list)
    interaction_results: list[V2RenderedInteractionResult] = Field(default_factory=list)
    trace_dom_coverage: float = 0.0
    teacher_leakage_findings: list[str] = Field(default_factory=list)
    learner_content_findings: list[str] = Field(default_factory=list)
    accessibility_findings: list[str] = Field(default_factory=list)
    responsive_findings: list[str] = Field(default_factory=list)
    visual_comparison: dict[str, Any] = Field(default_factory=dict)
    screenshot_artifacts: list[str] = Field(default_factory=list)
    deterministic_dom: bool = False
    normalized_dom_fingerprint: str = ""
    source_input_fingerprint: str = ""
    production_output_unchanged: bool = True
    visual_parity_verified: bool = False
    human_review_required: bool = True
    notes: list[str] = Field(default_factory=list)


# ── Shadow canonical presentation models ──

AbstractLearnerChannel = Literal["learner_card", "learner_display", "learner_interaction"]
AbstractTeacherChannel = Literal["speaker_notes", "teacher_observation", "teacher_html", "diagnostic_export"]
AbstractPresentationMode = Literal[
    "choice_response",
    "listening_choice",
    "matching_response",
    "guided_response",
    "role_play_response",
    "teacher_observation",
]


class PresentationTrace(BaseModel):
    """Trace references only; this is deliberately not a pedagogical payload."""

    model_config = ConfigDict(extra="forbid")

    presentation_unit_id: str
    binding_id: str
    activity_id: str
    evidence_ids: list[str]


class AbstractPresentationBinding(BaseModel):
    """Binding-first, renderer-independent projection of one planned activity."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.abstract_presentation_binding.v2", alias="schema")
    id: str
    presentation_unit_id: str
    activity_id: str
    evidence_ids: list[str]
    learner_channel: list[AbstractLearnerChannel]
    teacher_channel: list[AbstractTeacherChannel]
    presentation_mode: AbstractPresentationMode
    interaction_requirements: list[str]
    fallback_mode: str
    render_ready: bool
    teacher_only: bool
    warnings: list[str]
    trace: PresentationTrace


class AbstractPresentationBindingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.abstract_presentation_bindings.v2", alias="schema")
    state: QualityState = "pass"
    bindings: list[AbstractPresentationBinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)


class PresentationUnit(BaseModel):
    """A renderer-neutral unit with only learner-safe presentation content."""

    model_config = ConfigDict(extra="forbid")

    presentation_unit_id: str
    binding_id: str
    activity_id: str
    evidence_ids: list[str]
    content_item_id: str | None = None
    unit_role: str
    learner_channel: list[AbstractLearnerChannel]
    teacher_channel: list[AbstractTeacherChannel]
    presentation_mode: AbstractPresentationMode
    learner_facing_content: list[str]
    interaction_requirements: list[str]
    fallback_mode: str
    media_requirements: list[str]
    teacher_channel_reference: str | None = None
    render_ready: bool
    warnings: list[str]
    trace: PresentationTrace


class CanonicalPresentationBlueprint(BaseModel):
    """Canonical v2 presentation contract; it contains no kernel objects or layout."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_blueprint.v2", alias="schema")
    lesson_title: str
    presentation_units: list[PresentationUnit]
    warnings: list[str]
    source_artifacts: list[str]
    compatibility_notes: list[str]


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    value: str
    is_accepted: bool = False
    provenance: list[str] = Field(default_factory=list)


class MatchingPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    left: str
    right: str
    provenance: list[str] = Field(default_factory=list)


class AcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    normalized_value: str
    response_type: str
    acceptance_mode: str
    case_sensitive: bool = False
    alternatives: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_type: Literal["audio", "image"]
    path_or_key: str
    availability: Literal["available", "planned", "missing"]
    provenance: list[str] = Field(default_factory=list)


class PresentationContentItem(BaseModel):
    """Component-neutral learner content for an already-approved presentation unit."""

    model_config = ConfigDict(extra="forbid")

    id: str
    presentation_unit_id: str
    activity_id: str
    evidence_ids: list[str]
    presentation_mode: AbstractPresentationMode
    prompt: str = ""
    learner_instructions: list[str] = Field(default_factory=list)
    display_items: list[str] = Field(default_factory=list)
    options: list[ChoiceOption] = Field(default_factory=list)
    accepted_responses: list[AcceptedResponse] = Field(default_factory=list)
    matching_pairs: list[MatchingPair] = Field(default_factory=list)
    audio_asset_refs: list[AssetReference] = Field(default_factory=list)
    image_asset_refs: list[AssetReference] = Field(default_factory=list)
    learner_safe_hint: str = ""
    fallback_content: list[str] = Field(default_factory=list)
    language_items: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    complete: bool = False
    teacher_channel_reference: str | None = None
    trace: PresentationTrace


class PresentationContentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_content.v1", alias="schema")
    lesson_title: str
    content_items: list[PresentationContentItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_artifacts: list[str] = Field(default_factory=list)
    generation_strategy: str = "approved_artifact_projection"
    deterministic: bool = True
    trace: list[PresentationTrace] = Field(default_factory=list)


class PresentationContentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_content_report.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    items_count: int = 0
    complete_items_count: int = 0
    incomplete_items_count: int = 0
    choice_items_count: int = 0
    matching_items_count: int = 0
    listening_items_count: int = 0
    missing_audio_assets: list[str] = Field(default_factory=list)
    missing_options: list[str] = Field(default_factory=list)
    missing_accepted_responses: list[str] = Field(default_factory=list)
    missing_matching_pairs: list[str] = Field(default_factory=list)
    teacher_only_items: list[str] = Field(default_factory=list)
    fabricated_content_findings: list[str] = Field(default_factory=list)
    trace_coverage: float = 0.0
    deterministic: bool = True
    source_artifacts_checked: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PresentationAssetReconciliationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_item_id: str
    presentation_unit_id: str
    activity_id: str
    evidence_ids: list[str]
    presentation_mode: AbstractPresentationMode
    requested_asset_refs: list[AssetReference] = Field(default_factory=list)
    matched_asset_refs: list[AssetReference] = Field(default_factory=list)
    matching_strategy: str = "none"
    candidate_count: int = 0
    state: QualityState = "warning"
    warnings: list[str] = Field(default_factory=list)


class PresentationAssetReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_asset_reconciliation.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_content_plan_path: str = "presentation/presentation_content_plan.json"
    reconciled_content_plan_path: str = "presentation/presentation_content_plan.reconciled.json"
    asset_manifest_path: str = "assets/data/asset_manifest.json"
    assessed_audio_items: int = 0
    reconciled_audio_items: int = 0
    unresolved_audio_items: list[str] = Field(default_factory=list)
    ambiguous_audio_items: list[str] = Field(default_factory=list)
    invalid_asset_findings: list[str] = Field(default_factory=list)
    missing_asset_findings: list[str] = Field(default_factory=list)
    trace_coverage: float = 0.0
    deterministic: bool = True
    mutated_non_asset_fields: list[str] = Field(default_factory=list)
    recomputed_reports: list[str] = Field(default_factory=list)
    findings: list[PresentationAssetReconciliationFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


PresentationMediaRequestStatus = Literal["planned", "linked_to_existing_asset", "submitted", "generated", "unavailable", "failed", "ambiguous"]


class PresentationMediaRequest(BaseModel):
    """Renderer-neutral request identity for an approved presentation media need."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content_item_id: str
    presentation_unit_id: str
    activity_id: str
    evidence_ids: list[str]
    media_type: Literal["audio", "image"]
    media_role: str
    source_text: str
    source_language_item_ids: list[str] = Field(default_factory=list)
    required: bool = True
    generation_constraints: list[str] = Field(default_factory=list)
    preferred_voice_or_variant: str | None = None
    expected_asset_type: Literal["audio", "image"]
    status: PresentationMediaRequestStatus = "planned"
    provenance: list[str] = Field(default_factory=list)
    trace: PresentationTrace
    warnings: list[str] = Field(default_factory=list)


class PresentationMediaRequestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_media_requests.v1", alias="schema")
    requests: list[PresentationMediaRequest] = Field(default_factory=list)
    source_content_plan_path: str = "presentation/presentation_content_plan.json"
    generation_strategy: str = "shadow_request_identity_only"
    deterministic: bool = True
    warnings: list[str] = Field(default_factory=list)
    trace: list[PresentationTrace] = Field(default_factory=list)


class PresentationMediaRequestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_media_request_report.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requests_count: int = 0
    required_requests_count: int = 0
    optional_requests_count: int = 0
    complete_requests_count: int = 0
    incomplete_requests_count: int = 0
    duplicate_requests: list[str] = Field(default_factory=list)
    teacher_only_requests: list[str] = Field(default_factory=list)
    missing_source_findings: list[str] = Field(default_factory=list)
    deterministic: bool = True
    trace_coverage: float = 0.0
    asset_manifest_trace_supported: bool = False
    generation_integration_mode: str = "shadow_linkage"
    source_artifacts_checked: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PresentationMediaAssetLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_request_id: str
    asset_id: str = ""
    matching_strategy: str = "none"
    candidate_count: int = 0
    state: PresentationMediaRequestStatus = "unavailable"
    warnings: list[str] = Field(default_factory=list)


class PresentationMediaAssetLinkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_media_asset_links.v1", alias="schema")
    links: list[PresentationMediaAssetLink] = Field(default_factory=list)
    source_request_plan_path: str = "presentation/presentation_media_request_plan.json"
    source_asset_manifest_path: str = "assets/data/asset_manifest.json"
    deterministic: bool = True
    warnings: list[str] = Field(default_factory=list)


PresentationMediaProjectionMatchClass = Literal[
    "exact", "linkable", "approximate", "ambiguous", "unlinkable", "shadow_only", "legacy_only",
]


class PresentationMediaProjectionFinding(BaseModel):
    """Diagnostic comparison between one shadow request and legacy media requirements."""

    model_config = ConfigDict(extra="forbid")

    shadow_request_id: str
    content_item_id: str
    presentation_unit_id: str
    activity_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    media_type: Literal["audio", "image"]
    media_role: str
    shadow_source_text: str = ""
    shadow_language_item_ids: list[str] = Field(default_factory=list)
    candidate_legacy_requirement_ids: list[str] = Field(default_factory=list)
    selected_legacy_requirement_id: str | None = None
    match_class: PresentationMediaProjectionMatchClass
    matching_strategy: str = "none"
    confidence: float = 0.0
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: PresentationTrace


class PresentationMediaProjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_media_projection.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    shadow_requests_count: int = 0
    legacy_requirements_count: int = 0
    exact_matches_count: int = 0
    linkable_matches_count: int = 0
    approximate_matches_count: int = 0
    ambiguous_matches_count: int = 0
    unlinkable_shadow_requests_count: int = 0
    legacy_only_requirements_count: int = 0
    media_type_mismatches: list[str] = Field(default_factory=list)
    role_mismatches: list[str] = Field(default_factory=list)
    duplicate_semantic_requirements: list[str] = Field(default_factory=list)
    trace_coverage: float = 0.0
    deterministic: bool = True
    projection_safe_for_experiment: bool = False
    asset_origin_trace_mode: Literal["identity_contract", "explicit_origin_metadata", "unresolved_origin"] = "unresolved_origin"
    assets_with_origin_trace: list[str] = Field(default_factory=list)
    assets_without_origin_trace: list[str] = Field(default_factory=list)
    origin_trace_coverage: float = 0.0
    duplicate_origin_findings: list[str] = Field(default_factory=list)
    ambiguous_origin_findings: list[str] = Field(default_factory=list)
    projection_chain_complete: bool = False
    source_artifacts_checked: list[str] = Field(default_factory=list)
    findings: list[PresentationMediaProjectionFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PresentationMediaProjectionLink(BaseModel):
    """An exact or linkable, non-authoritative shadow relationship only."""

    model_config = ConfigDict(extra="forbid")

    shadow_request_id: str
    legacy_requirement_id: str
    match_class: Literal["exact", "linkable"]
    matching_strategy: str
    source_fingerprint: str
    media_type: Literal["audio", "image"]
    media_role: str
    trace: PresentationTrace


class PresentationMediaProjectionLinkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_media_projection_links.v1", alias="schema")
    links: list[PresentationMediaProjectionLink] = Field(default_factory=list)
    source_request_plan_path: str = "presentation/presentation_media_request_plan.json"
    source_legacy_media_plan_path: str = "blueprints/media_plan.json"
    deterministic: bool = True
    warnings: list[str] = Field(default_factory=list)


class PresentationShadowReport(BaseModel):
    """Status for the non-production v2 compiler path, not a pedagogical gate."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_shadow_report.v2", alias="schema")
    state: QualityState = "pass"
    generated_artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    compatibility_contract_valid: bool = False


class PresentationParityReport(BaseModel):
    """Diagnostic-only structural comparison of v2 and production presentation inputs."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_parity.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    production_blueprint_path: str = "blueprints/lesson_blueprint.json"
    shadow_legacy_blueprint_path: str = "presentation/legacy_blueprint_from_v2.shadow.json"
    canonical_blueprint_path: str = "presentation/presentation_blueprint.json"
    slide_count_production: int = 0
    slide_count_shadow: int = 0
    component_count_production: int = 0
    component_count_shadow: int = 0
    interactive_count_production: int = 0
    interactive_count_shadow: int = 0
    trace_coverage: float = 0.0
    teacher_leakage_findings: list[str] = Field(default_factory=list)
    unsupported_modes: list[str] = Field(default_factory=list)
    missing_units: list[str] = Field(default_factory=list)
    deterministic_output: bool = False
    visual_parity_checked: bool = False
    notes: list[str] = Field(default_factory=list)


PresentationMappingQuality = Literal["exact", "approximate", "fallback", "unsupported", "teacher_only"]


class PresentationModeCapability(BaseModel):
    """Diagnostic capability of a canonical mode in the current legacy renderer contract."""

    model_config = ConfigDict(extra="forbid")

    presentation_mode: AbstractPresentationMode
    presentation_unit_ids: list[str]
    recommended_legacy_slide_type: str
    recommended_legacy_component_type: str | None = None
    mapping_quality: PresentationMappingQuality
    required_payload_fields: list[str]
    optional_payload_fields: list[str]
    trace_fields: list[str]
    teacher_safe: bool
    learner_safe: bool
    renderer_supported: bool
    warnings: list[str] = Field(default_factory=list)


class PresentationAdapterMappingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.legacy_component_mapping.v1", alias="schema")
    capabilities: list[PresentationModeCapability] = Field(default_factory=list)


class PresentationAdapterAssessmentReport(BaseModel):
    """Diagnostic-only assessment of canonical modes against existing legacy capabilities."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_: str = Field(default="hanclassstudio.presentation_adapter_assessment.v1", alias="schema")
    state: QualityState = "pass"
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    canonical_blueprint_path: str = "presentation/presentation_blueprint.json"
    shadow_legacy_blueprint_path: str = "presentation/legacy_blueprint_from_v2.shadow.json"
    assessed_units_count: int = 0
    exact_mappings_count: int = 0
    approximate_mappings_count: int = 0
    fallback_mappings_count: int = 0
    unsupported_mappings_count: int = 0
    teacher_only_units_count: int = 0
    learner_visible_units_count: int = 0
    trace_coverage: float = 0.0
    component_payload_findings: list[str] = Field(default_factory=list)
    unsupported_modes: list[str] = Field(default_factory=list)
    fallback_modes: list[str] = Field(default_factory=list)
    teacher_channel_findings: list[str] = Field(default_factory=list)
    renderer_compatibility_findings: list[str] = Field(default_factory=list)
    visual_parity_checked: bool = False
    notes: list[str] = Field(default_factory=list)


# ── State-Evidence Kernel models ──

StateType = Literal["unseen", "noticed", "recognized", "understood", "controlled_production", "communicative_use", "transfer"]
EvidenceType = Literal["deterministic_choice", "matching", "listen_choose", "constrained_production", "role_play", "semantic_judgment", "teacher_observation"]
AssessmentMode = Literal["deterministic", "rubric_ai", "teacher", "hybrid"]
TransitionPolicy = Literal["all_required", "any_required", "custom_threshold", "exposure_only"]


class LearningGoal(BaseModel):
    """A design-time learning outcome; presentation details are intentionally absent."""

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$", validation_alias=AliasChoices("id", "goal_id"))
    description: str = Field(default="", validation_alias=AliasChoices("description", "success_claim"))
    skill_focus: Literal["recognition", "understanding", "production", "communicative", "transfer"] = Field(
        default="recognition", validation_alias=AliasChoices("skill_focus", "goal_type")
    )
    target_language: list[str] = Field(default_factory=list, validation_alias=AliasChoices("target_language", "target_items"))
    expected_behavior: str = ""
    difficulty: str = "beginner"
    success_criteria: list[str] = Field(default_factory=list)
    justification: str = ""
    required_state_to_reach: str = ""

    @property
    def goal_id(self) -> str:
        return self.id

    @property
    def goal_type(self) -> str:
        return self.skill_focus

    @property
    def target_items(self) -> list[str]:
        return self.target_language

    @property
    def success_claim(self) -> str:
        return self.description


class LearningState(BaseModel):
    state_id: str = ""
    state_type: StateType = "unseen"
    target_items: list[str] = Field(default_factory=list)
    learner_claim: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    design_confidence: float = 0.5


class LearningTransition(BaseModel):
    from_state: str = ""
    to_state: str = ""
    transition_intent: str = ""
    required_evidence_ids: list[str] = Field(default_factory=list)
    optional_evidence_ids: list[str] = Field(default_factory=list)
    transition_policy: TransitionPolicy = "all_required"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSpec(BaseModel):
    """Observable, presentation-independent evidence for exactly one learning goal."""

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$", validation_alias=AliasChoices("id", "evidence_id"))
    goal_id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    evidence_type: EvidenceType = "deterministic_choice"
    observable_behavior: str = Field(default="", validation_alias=AliasChoices("observable_behavior", "learning_claim"))
    collection_method: str = "learner_response"
    acceptable_response: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("acceptable_response", "pass_criteria"))
    teacher_observation_notes: str = ""
    confidence_level: str = "high"
    limitations: list[str] = Field(default_factory=list)
    justification: str = ""

    # Legacy state and collection fields remain to keep existing bindings working.
    state_from: str = ""
    state_to: str = ""
    target_items: list[str] = Field(default_factory=list)
    assessment_mode: AssessmentMode = "deterministic"
    collector_refs: list[str] = Field(default_factory=list)
    expected_behavior: dict[str, Any] = Field(default_factory=dict)
    confidence_policy: dict[str, Any] = Field(default_factory=lambda: {"deterministic": True, "ai_required": False, "teacher_override": True})
    failure_action: dict[str, Any] = Field(default_factory=dict)

    @property
    def evidence_id(self) -> str:
        return self.id

    @property
    def learning_claim(self) -> str:
        return self.observable_behavior

    @property
    def pass_criteria(self) -> dict[str, Any]:
        return self.acceptable_response


class LearningActivity(BaseModel):
    """Classroom interaction that collects evidence, without visual presentation decisions."""

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$", validation_alias=AliasChoices("id", "activity_id"))
    evidence_ids: list[str] = Field(min_length=1, validation_alias=AliasChoices("evidence_ids", "collects_evidence"))
    activity_type: str = ""
    learner_action: str = ""
    teacher_action: str = ""
    interaction_mode: str = "individual"
    input_type: str = "prompt"
    output_type: str = "response"
    fallback_activity: str = ""
    classroom_notes: str = ""
    learner_facing: bool = True

    # Presentation modes are existing binding constraints, not layout data.
    allowed_presentation_modes: list[str] = Field(default_factory=list)
    learner_level_fit: list[str] = Field(default_factory=list)
    scaffolding_level: str = "high"

    @property
    def activity_id(self) -> str:
        return self.id

    @property
    def collects_evidence(self) -> list[str]:
        return self.evidence_ids


class LearningStatePlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.learning_state_plan.v1", alias="schema")
    lesson_title: str = ""
    route_hint: str = ""
    learner_level: str = "beginner"
    language_background: str = ""
    topic_domain: str = ""
    prior_knowledge_assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    states: list[LearningState] = Field(default_factory=list)
    learning_goals: list[LearningGoal] = Field(default_factory=list, validation_alias=AliasChoices("learning_goals", "goals"))
    transitions: list[LearningTransition] = Field(default_factory=list)

    @property
    def goals(self) -> list[LearningGoal]:
        return self.learning_goals


class EvidencePlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.evidence_plan.v1", alias="schema")
    evidence_specs: list[EvidenceSpec] = Field(default_factory=list)


class ActivityPlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.activity_plan.v1", alias="schema")
    activities: list[LearningActivity] = Field(default_factory=list)


class EvidenceAlignmentReport(BaseModel):
    schema_: str = Field(default="hanclassstudio.evidence_alignment.v1", alias="schema")
    state: QualityState = "pass"
    goal_orphans: list[str] = Field(default_factory=list)
    evidence_orphans: list[str] = Field(default_factory=list)
    activity_suitability: list[str] = Field(default_factory=list)
    semantic_safety: list[str] = Field(default_factory=list)
    presentation_independence: list[str] = Field(default_factory=list)
    teacher_observation_readiness: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
