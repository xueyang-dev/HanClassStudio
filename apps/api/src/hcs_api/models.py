from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class AssetFile(BaseModel):
    id: str
    kind: Literal["image", "audio", "video", "font", "data"]
    path: str
    prompt: str = ""
    text: str = ""


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


# ── State-Evidence Kernel models ──

StateType = Literal["unseen", "noticed", "recognized", "understood", "controlled_production", "communicative_use", "transfer"]
EvidenceType = Literal["deterministic_choice", "matching", "listen_choose", "constrained_production", "role_play", "semantic_judgment", "teacher_observation"]
AssessmentMode = Literal["deterministic", "rubric_ai", "teacher", "hybrid"]
TransitionPolicy = Literal["all_required", "any_required", "custom_threshold", "exposure_only"]


class LearningGoal(BaseModel):
    goal_id: str = ""
    goal_type: Literal["recognition", "understanding", "production", "transfer"] = "recognition"
    target_items: list[str] = Field(default_factory=list)
    success_claim: str = ""
    required_state_to_reach: str = ""


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
    evidence_id: str = ""
    state_from: str = ""
    state_to: str = ""
    learning_claim: str = ""
    target_items: list[str] = Field(default_factory=list)
    evidence_type: EvidenceType = "deterministic_choice"
    assessment_mode: AssessmentMode = "deterministic"
    collector_refs: list[str] = Field(default_factory=list)
    expected_behavior: dict[str, Any] = Field(default_factory=dict)
    pass_criteria: dict[str, Any] = Field(default_factory=dict)
    confidence_policy: dict[str, Any] = Field(default_factory=lambda: {"deterministic": True, "ai_required": False, "teacher_override": True})
    failure_action: dict[str, Any] = Field(default_factory=dict)


class LearningActivity(BaseModel):
    activity_id: str = ""
    activity_type: str = ""
    collects_evidence: list[str] = Field(default_factory=list)
    allowed_presentation_modes: list[str] = Field(default_factory=list)
    learner_level_fit: list[str] = Field(default_factory=list)
    scaffolding_level: str = "high"


class LearningStatePlan(BaseModel):
    schema_: str = Field(default="hanclassstudio.learning_state_plan.v1", alias="schema")
    lesson_title: str = ""
    route_hint: str = ""
    states: list[LearningState] = Field(default_factory=list)
    goals: list[LearningGoal] = Field(default_factory=list)
    transitions: list[LearningTransition] = Field(default_factory=list)


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
