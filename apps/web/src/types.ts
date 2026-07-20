export type GenerationMode = "faithful" | "guided_redesign" | "reimagined";
export type QualityState = "pass" | "warning" | "blocked" | "stale";
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
  official_homepage_url?: string | null;
  api_signup_url?: string | null;
  api_docs_url?: string | null;
  repository_url?: string | null;
  model_card_url?: string | null;
  code_license_name?: string | null;
  code_license_url?: string | null;
  model_license_name?: string | null;
  model_license_url?: string | null;
  terms_url?: string | null;
  privacy_url?: string | null;
  supported_operations: string[];
  install_state?: ProviderInstallState | null;
  installed_version?: string | null;
  available_version?: string | null;
  environment_requirements?: Record<string, unknown>;
  environment_blockers?: ProviderEnvironmentBlocker[];
  install_actions?: ProviderInstallAction[];
  configuration_status?: "unknown" | "missing" | "configured" | "invalid";
  rollback_available?: boolean;
  failure?: { code: string; message: string; stage?: string | null; recoverable?: boolean } | null;
}

export type ProviderInstallState = "discovered" | "ready" | "installing" | "installed" | "configuring" | "available" | "failed";
export type ProviderInstallAction = "prepare_install" | "confirm_install" | "retry_install" | "configure" | "rollback" | "view_logs";

export interface ProviderEnvironmentBlocker {
  code: string;
  message: string;
  requirement?: string | null;
}

export interface ProviderEnvironmentReport {
  platform: string;
  architecture: string;
  python_version: string;
  free_disk_mb: number;
  gpu_available: boolean;
  blockers: ProviderEnvironmentBlocker[];
  checked_at: string;
}

export interface ProviderRegistryConfigField {
  key: string;
  label: string;
  type: "text" | "password" | "url";
  required: boolean;
  secret: boolean;
  placeholder?: string | null;
}

export interface ProviderRegistryEntry {
  provider_id: string;
  capability: ProviderCapability;
  display_name: string;
  description: string;
  source_url: string;
  repository: string;
  publisher: string;
  license: string;
  license_status: "approved" | "review_required" | "gated";
  license_url: string;
  model_license?: string | null;
  model_license_url?: string | null;
  trust_level: "first_party" | "verified_maintainer";
  version: string;
  source_ref: string;
  checksum_sha256: string;
  manifest_version: string;
  manifest_digest: string;
  configuration_schema: ProviderRegistryConfigField[];
  requirements: Record<string, unknown>;
  supported_operations: string[];
  executor: "mock";
  mock_only: boolean;
  experimental: boolean;
}

export interface ProviderInstallation {
  provider_id: string;
  capability: ProviderCapability;
  install_state: ProviderInstallState;
  installed_version?: string | null;
  available_version?: string | null;
  active_version?: string | null;
  previous_version?: string | null;
  configuration_status: "unknown" | "missing" | "configured" | "invalid";
  api_key_present: boolean;
  environment_blockers: ProviderEnvironmentBlocker[];
  blockers: ProviderEnvironmentBlocker[];
  failure?: { code: string; message: string; stage?: string | null; recoverable?: boolean } | null;
  rollback_available: boolean;
  current_plan_id?: string | null;
  updated_at: string;
}

export interface ProviderRegistryStatus {
  entry: ProviderRegistryEntry;
  installation: ProviderInstallation;
  environment: ProviderEnvironmentReport;
  policy_blockers: ProviderEnvironmentBlocker[];
  install_actions: ProviderInstallAction[];
}

export interface ProviderRegistryCatalog {
  providers: ProviderRegistryStatus[];
  source: {
    kind: "bundled" | "remote";
    source_url?: string | null;
    fetched_at?: string | null;
    catalog_version: number;
    source_revision: string;
    content_digest: string;
  };
}

export interface ProviderRegistryRefreshResponse {
  catalog: ProviderRegistryCatalog;
  changed_provider_ids: string[];
}

export interface ProviderInstallStep {
  kind: string;
  label: string;
}

export interface ProviderInstallPlan {
  plan_id: string;
  provider_id: string;
  version: string;
  source_ref: string;
  checksum_sha256: string;
  manifest_digest: string;
  steps: ProviderInstallStep[];
  environment: ProviderEnvironmentReport;
  rollback_strategy: string;
  created_at: string;
  expires_at: string;
}

export interface ProviderInstallPrepareResponse {
  plan: ProviderInstallPlan;
  confirmation_token: string;
  expires_at: string;
}

export interface ProviderInstallResult {
  installation: ProviderInstallation;
  install_actions: ProviderInstallAction[];
}

export interface ProviderInstallLog {
  timestamp: string;
  provider_id: string;
  plan_id?: string | null;
  stage: string;
  operation: string;
  message: string;
  success?: boolean | null;
  failure_code?: string | null;
}

export type ProviderHubStatus = "discovered" | "available" | "not_installed" | "installing" | "installed" | "not_configured" | "configured" | "checking" | "ready" | "degraded" | "incompatible" | "update_available" | "failed" | "disabled" | "unavailable";
export type ProviderHubAction = "view_details" | "open_project" | "open_api_application" | "configure" | "delete_configuration" | "test_connection" | "install" | "cancel_install" | "repair" | "check_health" | "disable" | "enable" | "view_logs";
export type ProviderTrustLevel = "official_verified" | "community_verified" | "discovered_unverified" | "user_added" | "deprecated" | "blocked";
export type ProviderCompatibility = "compatible" | "compatible_but_slow" | "unsupported" | "unknown";

export interface ProviderHubSourceLinks {
  official_website_url?: string | null;
  project_url?: string | null;
  api_application_url?: string | null;
  api_docs_url?: string | null;
  pricing_url?: string | null;
  terms_url?: string | null;
  privacy_url?: string | null;
  model_url?: string | null;
  license_url?: string | null;
}

export interface ProviderCapabilityPackage {
  id: string;
  name: string;
  description: string;
  runtime?: { id: string; name: string; version: string; execution: string } | null;
  model_packages: Array<{ id: string; name: string; version: string; format: string; safe_format: boolean }>;
  workflow_packs: Array<{ id: string; name: string; version: string; capabilities: string[] }>;
  healthcheck: string;
}

export interface ProviderHardwareCapability {
  operating_system: string;
  architecture: string;
  memory_mb?: number | null;
  free_disk_mb?: number | null;
  gpu_vendor?: string | null;
  gpu_name?: string | null;
  gpu_memory_mb?: number | null;
  cuda_available?: boolean | null;
  directml_available?: boolean | null;
  mps_available?: boolean | null;
  status: ProviderCompatibility;
  reasons: string[];
  speed_estimate?: string | null;
  checked_at: string;
}

export interface ProviderHubItem {
  id: string;
  provider_id: string;
  name: string;
  description: string;
  provider_type: "online" | "offline" | "hybrid";
  capabilities: string[];
  trust_level: ProviderTrustLevel;
  registry_source: "builtin" | "official_registry" | "local_config";
  status: ProviderHubStatus;
  installed: boolean;
  configured: boolean;
  ready: boolean;
  compatible: ProviderCompatibility;
  available_actions: ProviderHubAction[];
  recommended: boolean;
  requires_download: boolean;
  requires_api_key: boolean;
  paid_service?: boolean | null;
  runs_locally: boolean;
  uploads_data: boolean;
  version?: string | null;
  update_channel: "stable" | "beta" | "experimental";
  source_links: ProviderHubSourceLinks;
  license: { name?: string | null; url?: string | null; redistribution_allowed: boolean; clear: boolean };
  publisher?: string | null;
  third_party_executable_code: boolean;
  redistributed_by_hanclassstudio: boolean;
  capability_package?: ProviderCapabilityPackage | null;
  technical_error?: { code?: string; message?: string; [key: string]: unknown } | null;
  last_health_check_at?: string | null;
}

export interface ProviderHubCatalog {
  schema: "hanclassstudio.provider_hub.v1";
  providers: ProviderHubItem[];
  hardware: ProviderHardwareCapability;
  last_refresh_at?: string | null;
  isolated_errors: Array<{ code: string; entry: string }>;
}

export interface ProviderRefreshTask {
  task_id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled" | "partial";
  started_at: string;
  updated_at: string;
  finished_at?: string | null;
  summary: {
    added: number;
    updated: number;
    unchanged: number;
    failed_sources: number;
    sources: Array<{ source_id: string; status: "updated" | "unchanged" | "failed"; message: string; retained_previous_snapshot: boolean }>;
  };
  error?: { code: string; message: string } | null;
}

export interface ProviderHubInstallTask {
  task_id: string;
  package_id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled" | "partial";
  phase: string;
  progress: number;
  current_file_progress: number;
  downloaded_bytes: number;
  total_bytes: number;
  message: string;
  started_at: string;
  updated_at: string;
  finished_at?: string | null;
  cancellable: boolean;
  cancel_requested: boolean;
  error?: { code: string; message: string } | null;
  recoverable_actions: ProviderHubAction[];
  log_ref: string;
}

export interface ProviderHubInstallStartResponse {
  task: ProviderHubInstallTask;
  provider: ProviderHubItem;
}

export interface PublicOnlineProviderConfig {
  provider_id: string;
  endpoint: string;
  model: string;
  api_key_present: boolean;
  secure_storage: "os_protected" | "local_file_write_only";
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
  stale_stages?: string[];
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
