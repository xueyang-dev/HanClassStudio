export type GenerationMode = "faithful" | "guided_redesign" | "reimagined";
export type QualityState = "pass" | "warning" | "blocked";
export type StageState = "not_started" | "ready" | "running" | "completed" | "warning" | "blocked" | "failed" | "stale";
export type GateState = "not_run" | "running" | "passed" | "warning" | "blocked" | "failed" | "stale";

/** Capability category handled by a provider. */
export type ProviderCapability = "llm" | "ocr" | "image" | "tts" | "video";

/** One configurable field for a provider. */
export interface ProviderFieldDef {
  key: string;
  label: string;
  type: "text" | "password" | "select" | "url";
  placeholder?: string;
  required: boolean;
  options?: Array<{ value: string; label: string }>;
}

/** A provider descriptor returned by the backend capability contract. */
export interface ProviderDefinition {
  id: string;
  name: string;
  category: "cloud" | "local";
  capability: ProviderCapability;
  description: string;
  fields: ProviderFieldDef[];
  implemented: boolean;
  configurable: boolean;
  configured: boolean;
  available: boolean;
  experimental: boolean;
  unavailable_reason?: string | null;
  supported_operations: string[];
}

/** Stored configuration for one capability. */
export interface CapabilityConfig {
  providerId: string;
  values: Record<string, string>;
}

/** Full provider configuration persisted per user/browser. */
export type ProviderConfig = Partial<Record<ProviderCapability, CapabilityConfig>>;

export interface ComponentConfig {
  renderer?: string;
  requires?: string[];
  optional?: string[];
  quality?: string[];
  accessible?: boolean;
  experimental?: boolean;
}

export type ComponentRegistry = Record<string, ComponentConfig>;

export interface TextBlock {
  id: string;
  text: string;
  kind: string;
  left?: number | null;
  top?: number | null;
  width?: number | null;
  height?: number | null;
}

export interface ImageBlock {
  id: string;
  path: string;
  filename: string;
  width?: number | null;
  height?: number | null;
  description: string;
}

export interface SourcePage {
  page_number: number;
  title: string;
  text_blocks: TextBlock[];
  images: ImageBlock[];
  notes: string;
  ocr_text: string;
}

export interface SourceMaterial {
  source_type: "pptx" | "pdf" | "image" | "unknown";
  original_filename: string;
  created_at: string;
  pages: SourcePage[];
  source_analysis?: SourceAnalysis | null;
}

/** A single recognized block inside the OCR Source Evidence Model. */
export interface SourceAnalysisBlock {
  text: string;
  confidence: number;
  block_type: string;
  needs_review: boolean;
}

/** Per-page result of the OCR / Source Document Understanding layer. */
export interface SourceAnalysisPage {
  page_number: number;
  source_method: string;
  dominant_language?: string;
  has_native_text?: boolean;
  blocks: SourceAnalysisBlock[];
}

/** Normalized source contract (hanclassstudio.source_evidence.v1) produced by OCR. */
export interface SourceAnalysis {
  schema: string;
  source_method_summary: Record<string, number>;
  overall_confidence: number;
  needs_review_count: number;
  pages: SourceAnalysisPage[];
  notes: string[];
}

/** One OCR engine reported by GET /api/ocr/status. */
export interface OcrEngineStatus {
  name: string;
  available: boolean;
  detail: string;
}

/** Response of GET /api/ocr/status. */
export interface OcrStatusResponse {
  engines: OcrEngineStatus[];
  policy: Record<string, unknown>;
  recommended_pipeline: string[];
}

export interface BackendHealth {
  status: "ok" | string;
}

export interface LessonProfile {
  lesson_title: string;
  subject: string;
  learner_level: string;
  target_students: string;
  scaffolding_language: string;
  lesson_type: string;
  generation_mode: GenerationMode;
  estimated_duration: string;
}

export interface ContentBlock {
  id: string;
  block_type: string;
  text: string;
  scaffolding_text: string;
}

export interface SlideComponent {
  id: string;
  component_type: string;
  title: string;
  data: Record<string, unknown>;
}

export interface MediaRequirements {
  image_prompt?: string | null;
  image_key?: string | null;
  audio_text?: string | null;
  audio_key?: string | null;
  video_scene_prompt?: string | null;
  video_key?: string | null;
}

export interface LessonSlide {
  id: number;
  slide_type: string;
  layout_variant: string;
  title: string;
  content_blocks: ContentBlock[];
  components: SlideComponent[];
  media_requirements: MediaRequirements;
}

export interface LessonBlueprint {
  lesson_title: string;
  objectives: string[];
  key_vocabulary: Array<Record<string, string>>;
  grammar_points: string[];
  slides: LessonSlide[];
}

export interface AssetFile {
  id: string;
  kind: "image" | "audio" | "video" | "font" | "data";
  path: string;
  placeholder?: boolean;
  prompt: string;
  text: string;
  review_state?: "pending_review" | "accepted" | "rejected" | "regenerate_requested" | "replaced_by_teacher" | "fallback_accepted" | null;
  selected_candidate_id?: string | null;
  candidates?: AssetCandidate[];
  review_history?: AssetReviewEvent[];
}

export interface AssetCandidate {
  id: string;
  path: string;
  mime_type: string;
  content_hash: string;
  source: "generated" | "fallback" | "teacher";
  created_at?: string;
}

export interface AssetReviewEvent {
  state: string;
  candidate_id?: string | null;
  notes: string;
  occurred_at?: string;
}

export interface AssetManifest {
  images: AssetFile[];
  audio: AssetFile[];
  video: AssetFile[];
  fonts: AssetFile[];
}

export interface QualityReport {
  schema: string;
  state: QualityState;
  blocking: string[];
  warnings: string[];
  passed: string[];
  missing_titles: string[];
  missing_audio: string[];
  missing_images: string[];
  invalid_interactions: string[];
  empty_prompts: string[];
  resource_errors: string[];
  suggestions: string[];
}

export interface StageStatus {
  stage_id: string;
  state: StageState;
  started_at?: string | null;
  completed_at?: string | null;
  stale: boolean;
  blockers: string[];
  warnings: string[];
  required_artifacts: string[];
  available_actions: string[];
}

export interface GateStatus {
  state: GateState;
  blocking_reasons: string[];
  warnings: string[];
  stale: boolean;
}

export interface GateSummary {
  evidence_alignment: GateStatus;
  presentation_readiness: GateStatus;
  presentation_binding: GateStatus;
  quality_report: GateStatus;
  overall_state: GateState;
  export_allowed: boolean;
  force_export_allowed: boolean;
  blocking_reasons: string[];
  warnings: string[];
  stale: boolean;
}

export interface StaleState {
  stale: boolean;
  reasons: string[];
  changed_at?: string | null;
}

export interface ProjectState {
  project_id: string;
  status: string;
  route?: string | null;
  project_revision?: number;
  current_stage?: string;
  stages?: StageStatus[];
  profile_state?: "inferred" | "confirmed" | "stale";
  gate_summary?: GateSummary;
  artifacts?: Record<string, boolean>;
  stale_state?: StaleState;
  provider_readiness?: ProviderDefinition[];
  last_updated_at?: string | null;
  quality_state?: QualityState | null;
  source_material?: SourceMaterial | null;
  lesson_profile?: LessonProfile | null;
  lesson_blueprint?: LessonBlueprint | null;
  asset_manifest?: AssetManifest | null;
  quality_report?: QualityReport | null;
  preview_url?: string | null;
  export_url?: string | null;
}

export interface ProjectSummary {
  project_id: string;
  status: string;
  current_stage: string;
  profile_state: "inferred" | "confirmed" | "stale";
  project_revision: number;
  source_filename?: string | null;
  last_updated_at?: string | null;
}

export interface StateFirstTeacherSummary {
  project_id: string;
  project_revision: number;
  learning_state_plan?: Record<string, unknown> | null;
  evidence_plan?: Record<string, unknown> | null;
  activity_plan?: Record<string, unknown> | null;
  evidence_alignment?: Record<string, unknown> | null;
  blockers: string[];
  warnings: string[];
  available_actions: string[];
}

export interface ArtifactEntry {
  path: string;
  exists: boolean;
  size?: number | null;
  updated_at?: string | null;
  artifact_type: string;
}

export interface ArtifactGroup {
  name: string;
  items: ArtifactEntry[];
}

export interface ArtifactTree {
  project_id: string;
  groups: ArtifactGroup[];
  spec_lock?: Record<string, unknown> | null;
}

export interface AgentPackage {
  project_id: string;
  task_path: string;
  rules_path: string;
  task_text: string;
  rules_text: string;
}

export interface AgentValidation {
  project_id: string;
  state: QualityState;
  blocking: string[];
  warnings: string[];
  passed: string[];
}

export interface EditablePptxExportResponse {
  filename: string;
  download_url: string;
  export_type: "pptx_editable";
  editable: true;
  interaction_policy: "classroom_static_activity";
  quality_state?: QualityState | null;
}
