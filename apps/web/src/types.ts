export type GenerationMode = "faithful" | "guided_redesign" | "reimagined";
export type QualityState = "pass" | "warning" | "blocked";

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
  source_type: "pptx" | "pdf" | "unknown";
  original_filename: string;
  created_at: string;
  pages: SourcePage[];
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
  prompt: string;
  text: string;
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

export interface ProjectState {
  project_id: string;
  status: string;
  route?: string | null;
  quality_state?: QualityState | null;
  source_material?: SourceMaterial | null;
  lesson_profile?: LessonProfile | null;
  lesson_blueprint?: LessonBlueprint | null;
  asset_manifest?: AssetManifest | null;
  quality_report?: QualityReport | null;
  preview_url?: string | null;
  export_url?: string | null;
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
