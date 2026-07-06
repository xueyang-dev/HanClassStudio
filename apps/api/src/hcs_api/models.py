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
    lesson_title: str
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
