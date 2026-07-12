import type {
  AgentPackage,
  AgentValidation,
  ArtifactTree,
  ComponentRegistry,
  EditablePptxExportResponse,
  LessonBlueprint,
  LessonProfile,
  OcrStatusResponse,
  ProjectState,
  ProviderCapability,
  ProviderConfig
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function download(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.blob();
}

async function responseError(response: Response): Promise<string> {
  let message = response.statusText;
  try {
    const body = await response.json();
    message = body.detail ?? message;
  } catch {
    message = response.statusText;
  }
  return message;
}

export async function uploadProject(file: File): Promise<ProjectState> {
  const data = new FormData();
  data.append("file", file);
  return request<ProjectState>("/api/projects/upload", {
    method: "POST",
    body: data
  });
}

export async function saveProfile(projectId: string, profile: LessonProfile): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile)
  });
}

export async function generateBlueprint(projectId: string): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/blueprint`, { method: "POST" });
}

export async function saveBlueprint(projectId: string, blueprint: LessonBlueprint): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/blueprint`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(blueprint)
  });
}

export async function generateMedia(projectId: string): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/media`, { method: "POST" });
}

export async function renderProject(projectId: string): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/render`, { method: "POST" });
}

export async function runPipeline(projectId: string): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/pipeline`, { method: "POST" });
}

export async function listProjectArtifacts(projectId: string): Promise<ArtifactTree> {
  return request<ArtifactTree>(`/api/projects/${projectId}/artifacts`);
}

export async function getComponentRegistry(): Promise<ComponentRegistry> {
  return request<ComponentRegistry>("/api/component-registry");
}

export async function generateAgentPackage(projectId: string): Promise<AgentPackage> {
  return request<AgentPackage>(`/api/projects/${projectId}/agent/package`, { method: "POST" });
}

export async function validateAgentOutput(projectId: string): Promise<AgentValidation> {
  return request<AgentValidation>(`/api/projects/${projectId}/agent/validate`, { method: "POST" });
}

export async function forceExportProject(projectId: string): Promise<Blob> {
  return download(`/api/projects/${projectId}/export?force=true`, { method: "POST" });
}

export async function exportEditablePptx(projectId: string, force = false): Promise<EditablePptxExportResponse> {
  return request<EditablePptxExportResponse>(`/api/projects/${projectId}/export/pptx-editable?force=${force ? "true" : "false"}`, {
    method: "POST"
  });
}

export function exportUrl(projectId: string): string {
  return `${API_BASE}/api/projects/${projectId}/export`;
}

export function previewUrl(path?: string | null): string | null {
  return path ? `${API_BASE}${path}` : null;
}

/** Report which OCR engines are actually available in this deployment. */
export async function getOcrStatus(): Promise<OcrStatusResponse> {
  return request<OcrStatusResponse>("/api/ocr/status");
}

/** Re-run OCR on the already-uploaded file. `engine` is optional
 * ("paddle_ocr" | "tesseract"); omit/"auto" to use the default layered policy. */
export async function rerunOcr(projectId: string, engine?: string): Promise<ProjectState> {
  const qs = engine && engine !== "auto" ? `?engine=${encodeURIComponent(engine)}` : "";
  return request<ProjectState>(`/api/projects/${projectId}/ocr${qs}`, { method: "POST" });
}

/* ── Provider settings: persisted on the backend, the single source of truth ── */

interface BackendCapabilityConfig {
  providerId: string;
  values: Record<string, string>;
}

/** Server-side shape of `ProviderSettings` (see apps/api .../models.py). */
export interface BackendProviderSettings {
  llm: { provider: string; base_url: string; api_key: string; model: string };
  image: { provider: string; endpoint_url: string; api_key: string; model: string };
  audio: { provider: string; endpoint_url: string; api_key: string; model: string; voice: string };
  ocr: { provider: string; deploy_mode: string; api_key: string; endpoint_url: string; model: string; langs: string; use_gpu: boolean };
  video: { provider: string; deploy_mode: string; api_key: string; endpoint_url: string; model: string };
  capabilities: Record<string, BackendCapabilityConfig>;
}

const CLOUD_PROVIDER_IDS = new Set([
  "openai", "anthropic", "azure_openai", "google", "ollama", "lm_studio",
  "openai_tts", "elevenlabs", "runway", "azure_doc",
]);

/** Fetch the persisted provider settings from the backend. */
export async function fetchProviderSettings(): Promise<BackendProviderSettings> {
  return request<BackendProviderSettings>("/api/settings/providers");
}

/** Persist the provider settings to the backend. */
export async function putProviderSettings(body: BackendProviderSettings): Promise<BackendProviderSettings> {
  return request<BackendProviderSettings>("/api/settings/providers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Translate the frontend `ProviderConfig` into the backend `ProviderSettings` shape,
 * deriving the flat image/audio/ocr/video fields the pipeline reads. */
export function configToBackend(config: ProviderConfig): BackendProviderSettings {
  const cap: Record<string, BackendCapabilityConfig> = {};
  (Object.keys(config) as ProviderCapability[]).forEach((capability) => {
    const c = config[capability];
    if (c && c.providerId) cap[capability] = { providerId: c.providerId, values: c.values };
  });

  const img = config.image;
  const imgV = img?.values ?? {};
  const tts = config.tts;
  const ttsV = tts?.values ?? {};
  const ocr = config.ocr;
  const ocrV = ocr?.values ?? {};
  const vid = config.video;
  const vidV = vid?.values ?? {};

  return {
    llm: { provider: "openai_compatible", base_url: "https://api.openai.com/v1", api_key: "", model: "gpt-4.1-mini" },
    image: {
      provider: img?.providerId ?? "placeholder",
      endpoint_url: imgV.endpoint || imgV.baseUrl || "",
      api_key: imgV.apiKey || "",
      model: imgV.model || imgV.deployment || "",
    },
    audio: {
      provider: tts?.providerId ?? "placeholder",
      endpoint_url: ttsV.endpoint || ttsV.baseUrl || "",
      api_key: ttsV.apiKey || "",
      model: ttsV.model || "",
      voice: ttsV.voice || ttsV.voiceId || "",
    },
    ocr: {
      provider: ocr?.providerId ?? "",
      deploy_mode: ocr ? (CLOUD_PROVIDER_IDS.has(ocr.providerId) ? "cloud" : "local") : "local",
      api_key: ocrV.apiKey || "",
      endpoint_url: ocrV.endpoint || "",
      model: "",
      langs: ocrV.langs || "",
      use_gpu: ocrV.useGpu === "true",
    },
    video: {
      provider: vid?.providerId ?? "",
      deploy_mode: vid ? (CLOUD_PROVIDER_IDS.has(vid.providerId) ? "cloud" : "local") : "local",
      api_key: vidV.apiKey || "",
      endpoint_url: vidV.endpoint || "",
      model: "",
    },
    capabilities: cap,
  };
}

/** Translate backend `ProviderSettings` back into the frontend `ProviderConfig`.
 * Prefers the raw `capabilities` payload (exact round-trip); falls back to
 * reconstructing from the flat fields when `capabilities` is empty. */
export function backendToConfig(backend: BackendProviderSettings): ProviderConfig {
  const cap = backend.capabilities;
  if (cap && Object.keys(cap).length > 0) {
    const out: ProviderConfig = {};
    Object.keys(cap).forEach((k) => {
      const c = cap[k];
      if (c && c.providerId) out[k as ProviderCapability] = { providerId: c.providerId, values: c.values };
    });
    return out;
  }

  const out: ProviderConfig = {};
  if (backend.image?.provider && backend.image.provider !== "placeholder") {
    out.image = {
      providerId: backend.image.provider,
      values: { apiKey: backend.image.api_key, baseUrl: backend.image.endpoint_url, model: backend.image.model },
    };
  }
  if (backend.audio?.provider && backend.audio.provider !== "placeholder") {
    out.tts = {
      providerId: backend.audio.provider,
      values: { apiKey: backend.audio.api_key, baseUrl: backend.audio.endpoint_url, model: backend.audio.model, voice: backend.audio.voice },
    };
  }
  if (backend.ocr?.provider) {
    out.ocr = {
      providerId: backend.ocr.provider,
      values: {
        endpoint: backend.ocr.endpoint_url,
        apiKey: backend.ocr.api_key,
        langs: backend.ocr.langs,
        useGpu: backend.ocr.use_gpu ? "true" : "false",
      },
    };
  }
  if (backend.video?.provider) {
    out.video = {
      providerId: backend.video.provider,
      values: { apiKey: backend.video.api_key, endpoint: backend.video.endpoint_url },
    };
  }
  return out;
}
