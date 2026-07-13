import type {
  AgentPackage,
  AgentValidation,
  AssetFile,
  AssetManifest,
  BackendHealth,
  ArtifactTree,
  ComponentRegistry,
  EditablePptxExportResponse,
  LessonBlueprint,
  LessonProfile,
  OcrStatusResponse,
  ProjectState,
  ProviderCapability,
  ProviderConfig,
  ProviderDefinition,
  ProjectSummary,
  StateFirstTeacherSummary
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
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (body.detail && typeof body.detail === "object") {
      const detail = body.detail as { message?: unknown; blocking_reasons?: unknown };
      const reasons = Array.isArray(detail.blocking_reasons)
        ? detail.blocking_reasons.filter((item): item is string => typeof item === "string")
        : [];
      message = [typeof detail.message === "string" ? detail.message : "", ...reasons]
        .filter(Boolean)
        .join("\n") || message;
    }
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

export async function fetchHealth(): Promise<BackendHealth> {
  return request<BackendHealth>("/api/health");
}

export async function listProjects(limit = 20): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>(`/api/projects?limit=${limit}`);
}

export async function fetchProject(projectId: string): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export async function fetchDesignSummary(projectId: string): Promise<StateFirstTeacherSummary> {
  return request<StateFirstTeacherSummary>(`/api/projects/${encodeURIComponent(projectId)}/design/summary`);
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

export async function generateMedia(projectId: string, forceRegenerate = false): Promise<ProjectState> {
  return request<ProjectState>(`/api/projects/${projectId}/media${forceRegenerate ? "?force_regenerate=true" : ""}`, { method: "POST" });
}

export async function fetchMediaManifest(projectId: string): Promise<AssetManifest> {
  return request<AssetManifest>(`/api/projects/${encodeURIComponent(projectId)}/media`);
}

export async function reviewMedia(projectId: string, assetId: string, action: { state: string; candidate_id?: string; notes?: string }): Promise<AssetFile> {
  return request<AssetFile>(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(assetId)}/review`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
}

export async function replaceMedia(projectId: string, assetId: string, file: File, notes = ""): Promise<AssetFile> {
  const body = new FormData();
  body.append("file", file);
  body.append("notes", notes);
  return request<AssetFile>(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(assetId)}/replacement`, {
    method: "POST",
    body,
  });
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

/** Fetch the persisted provider settings from the backend. */
export async function fetchProviderSettings(): Promise<BackendProviderSettings> {
  return request<BackendProviderSettings>("/api/settings/providers");
}

export async function fetchProviderCapabilities(): Promise<ProviderDefinition[]> {
  const descriptors = await request<Array<{
    capability: ProviderCapability;
    provider_id: string;
    display_name: string;
    category: "cloud" | "local";
    description: string;
    implemented: boolean;
    configurable: boolean;
    configured: boolean;
    available: boolean;
    experimental: boolean;
    unavailable_reason?: string | null;
    configuration_schema: Array<{
      key: string;
      label: string;
      type: "text" | "password" | "select" | "url";
      placeholder?: string;
      required: boolean;
      options?: Array<{ value: string; label: string }>;
    }>;
    supported_operations: string[];
  }>>
  ("/api/settings/providers/capabilities");
  return descriptors.map((descriptor) => ({
    id: descriptor.provider_id,
    name: descriptor.display_name,
    category: descriptor.category,
    capability: descriptor.capability,
    description: descriptor.description,
    fields: descriptor.configuration_schema,
    implemented: descriptor.implemented,
    configurable: descriptor.configurable,
    configured: descriptor.configured,
    available: descriptor.available,
    experimental: descriptor.experimental,
    unavailable_reason: descriptor.unavailable_reason,
    supported_operations: descriptor.supported_operations,
  }));
}

/** Persist the provider settings to the backend. */
export async function putProviderSettings(body: BackendProviderSettings): Promise<BackendProviderSettings> {
  return request<BackendProviderSettings>("/api/settings/providers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function nonEmptyString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function preserveSecret(value: unknown, fallback: string): string {
  // An empty API key means "not edited" in the WebUI. It must not erase a
  // credential already stored by the backend console or another session.
  return typeof value === "string" && value.trim() ? value : fallback;
}

/** Translate the frontend `ProviderConfig` into the backend `ProviderSettings` shape,
 * deriving the flat image/audio/ocr/video fields the pipeline reads. */
export function configToBackend(config: ProviderConfig, base?: BackendProviderSettings | null): BackendProviderSettings {
  const cap: Record<string, BackendCapabilityConfig> = {};
  (Object.keys(config) as ProviderCapability[]).forEach((capability) => {
    const c = config[capability];
    if (c && c.providerId) cap[capability] = { providerId: c.providerId, values: c.values };
  });

  const llm = config.llm;
  const llmV = llm?.values ?? {};
  const img = config.image;
  const imgV = img?.values ?? {};
  const tts = config.tts;
  const ttsV = tts?.values ?? {};
  const ocr = config.ocr;
  const ocrV = ocr?.values ?? {};
  const vid = config.video;
  const vidV = vid?.values ?? {};

  const current = base ?? {
    llm: { provider: "openai_compatible", base_url: "https://api.openai.com/v1", api_key: "", model: "gpt-4.1-mini" },
    image: { provider: "placeholder", endpoint_url: "", api_key: "", model: "placeholder-svg" },
    audio: { provider: "placeholder", endpoint_url: "", api_key: "", model: "placeholder-tone", voice: "default" },
    ocr: { provider: "", deploy_mode: "local", api_key: "", endpoint_url: "", model: "", langs: "", use_gpu: false },
    video: { provider: "", deploy_mode: "local", api_key: "", endpoint_url: "", model: "" },
    capabilities: {},
  };
  const next: BackendProviderSettings = {
    ...current,
    llm: llm ? {
      ...current.llm,
      provider: llm.providerId,
      base_url: llmV.base_url || llmV.baseUrl || current.llm.base_url,
      api_key: preserveSecret(llmV.api_key ?? llmV.apiKey, current.llm.api_key),
      model: nonEmptyString(llmV.model, current.llm.model),
    } : current.llm,
    image: {
      ...current.image,
      provider: img?.providerId ?? current.image.provider,
      endpoint_url: nonEmptyString(imgV.endpoint ?? imgV.baseUrl ?? imgV.base_url, current.image.endpoint_url),
      api_key: preserveSecret(imgV.apiKey ?? imgV.api_key, current.image.api_key),
      model: nonEmptyString(imgV.model ?? imgV.deployment, current.image.model),
    },
    audio: {
      ...current.audio,
      provider: tts?.providerId ?? current.audio.provider,
      endpoint_url: nonEmptyString(ttsV.endpoint ?? ttsV.baseUrl ?? ttsV.base_url, current.audio.endpoint_url),
      api_key: preserveSecret(ttsV.apiKey ?? ttsV.api_key, current.audio.api_key),
      model: nonEmptyString(ttsV.model, current.audio.model),
      voice: nonEmptyString(ttsV.voice ?? ttsV.voiceId, current.audio.voice),
    },
    ocr: {
      ...current.ocr,
      provider: ocr?.providerId ?? current.ocr.provider,
      deploy_mode: current.ocr.deploy_mode,
      api_key: preserveSecret(ocrV.apiKey ?? ocrV.api_key, current.ocr.api_key),
      endpoint_url: nonEmptyString(ocrV.endpoint ?? ocrV.endpoint_url, current.ocr.endpoint_url),
      model: nonEmptyString(ocrV.model, current.ocr.model),
      langs: ocrV.langs ?? current.ocr.langs,
      use_gpu: ocrV.useGpu === "true" || ocrV.use_gpu === "true" || current.ocr.use_gpu,
    },
    video: {
      ...current.video,
      provider: vid?.providerId ?? current.video.provider,
      deploy_mode: current.video.deploy_mode,
      api_key: preserveSecret(vidV.apiKey ?? vidV.api_key, current.video.api_key),
      endpoint_url: nonEmptyString(vidV.endpoint ?? vidV.endpoint_url, current.video.endpoint_url),
      model: nonEmptyString(vidV.model, current.video.model),
    },
    capabilities: mergeCapabilitySettings(current.capabilities, cap),
  };
  return next;
}

function mergeCapabilitySettings(
  current: Record<string, BackendCapabilityConfig>,
  next: Record<string, BackendCapabilityConfig>,
): Record<string, BackendCapabilityConfig> {
  const merged: Record<string, BackendCapabilityConfig> = { ...current };
  for (const [capability, value] of Object.entries(next)) {
    const previous = current[capability];
    const values = { ...(previous?.values ?? {}), ...value.values };
    for (const key of ["api_key", "apiKey"]) {
      if (!String(value.values[key] ?? "").trim() && String(previous?.values[key] ?? "").trim()) {
        values[key] = previous?.values[key] ?? "";
      }
    }
    merged[capability] = { providerId: value.providerId, values };
  }
  return merged;
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
      if (c && c.providerId) out[k as ProviderCapability] = { providerId: c.providerId, values: normalizeProviderValues(c.values) };
    });
    return out;
  }

  const out: ProviderConfig = {};
  if (backend.llm?.provider) {
    out.llm = {
      providerId: backend.llm.provider,
      values: { base_url: backend.llm.base_url, api_key: backend.llm.api_key, model: backend.llm.model },
    };
  }
  if (backend.image?.provider && backend.image.provider !== "placeholder") {
    out.image = {
      providerId: backend.image.provider,
      values: normalizeProviderValues({ api_key: backend.image.api_key, base_url: backend.image.endpoint_url, model: backend.image.model }),
    };
  }
  if (backend.audio?.provider && backend.audio.provider !== "placeholder") {
    out.tts = {
      providerId: backend.audio.provider,
      values: normalizeProviderValues({ api_key: backend.audio.api_key, base_url: backend.audio.endpoint_url, model: backend.audio.model, voice: backend.audio.voice }),
    };
  }
  if (backend.ocr?.provider) {
    out.ocr = {
      providerId: backend.ocr.provider,
      values: normalizeProviderValues({
        endpoint: backend.ocr.endpoint_url,
        apiKey: backend.ocr.api_key,
        langs: backend.ocr.langs,
        useGpu: backend.ocr.use_gpu ? "true" : "false",
      }),
    };
  }
  if (backend.video?.provider) {
    out.video = {
      providerId: backend.video.provider,
      values: normalizeProviderValues({ apiKey: backend.video.api_key, endpoint: backend.video.endpoint_url }),
    };
  }
  return out;
}

function normalizeProviderValues(values: Record<string, string>): Record<string, string> {
  return {
    ...values,
    api_key: values.api_key ?? values.apiKey ?? "",
    base_url: values.base_url ?? values.baseUrl ?? values.endpoint ?? "",
    endpoint: values.endpoint ?? values.endpoint_url ?? values.baseUrl ?? "",
    endpoint_url: values.endpoint_url ?? values.endpoint ?? values.baseUrl ?? "",
    use_gpu: values.use_gpu ?? values.useGpu ?? "false",
    voice: values.voice ?? values.voiceId ?? "",
  };
}
