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
  ProviderInstallLog,
  ProviderInstallPrepareResponse,
  ProviderInstallResult,
  ProjectState,
  ProviderCapability,
  ProviderConfig,
  ProviderDefinition,
  ProviderRegistryCatalog,
  ProviderRegistryRefreshResponse,
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
      const detail = body.detail as { message?: unknown; blocking_reasons?: unknown; blockers?: unknown };
      const reasons = Array.isArray(detail.blocking_reasons)
        ? detail.blocking_reasons.filter((item): item is string => typeof item === "string")
        : [];
      if (Array.isArray(detail.blockers)) {
        reasons.push(...detail.blockers.map((item) => {
          if (item && typeof item === "object" && "message" in item && typeof item.message === "string") return item.message;
          return typeof item === "string" ? item : "";
        }).filter(Boolean));
      }
      message = [typeof detail.message === "string" ? detail.message : "", ...reasons]
        .filter(Boolean)
        .join("\n") || message;
    }
  } catch {
    message = response.statusText;
  }
  return message;
}

function withExpectedRevision(path: string, expectedRevision?: number | null): string {
  if (expectedRevision === undefined || expectedRevision === null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}expected_revision=${encodeURIComponent(String(expectedRevision))}`;
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

export async function saveProfile(projectId: string, profile: LessonProfile, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/profile`, expectedRevision), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile)
  });
}

export async function generateBlueprint(projectId: string, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/blueprint`, expectedRevision), { method: "POST" });
}

export async function saveBlueprint(projectId: string, blueprint: LessonBlueprint, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/blueprint`, expectedRevision), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(blueprint)
  });
}

export async function generateMedia(projectId: string, forceRegenerate = false, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/media${forceRegenerate ? "?force_regenerate=true" : ""}`, expectedRevision), { method: "POST" });
}

export async function fetchMediaManifest(projectId: string): Promise<AssetManifest> {
  return request<AssetManifest>(`/api/projects/${encodeURIComponent(projectId)}/media`);
}

export async function reviewMedia(projectId: string, assetId: string, action: { state: string; candidate_id?: string; notes?: string }, expectedRevision?: number | null): Promise<AssetFile> {
  return request<AssetFile>(withExpectedRevision(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(assetId)}/review`, expectedRevision), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
}

export async function replaceMedia(projectId: string, assetId: string, file: File, notes = "", expectedRevision?: number | null): Promise<AssetFile> {
  const body = new FormData();
  body.append("file", file);
  body.append("notes", notes);
  return request<AssetFile>(withExpectedRevision(`/api/projects/${encodeURIComponent(projectId)}/media/${encodeURIComponent(assetId)}/replacement`, expectedRevision), {
    method: "POST",
    body,
  });
}

export async function renderProject(projectId: string, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/render`, expectedRevision), { method: "POST" });
}

export async function runPipeline(projectId: string, expectedRevision?: number | null): Promise<ProjectState> {
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/pipeline`, expectedRevision), { method: "POST" });
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
export async function rerunOcr(projectId: string, engine?: string, expectedRevision?: number | null): Promise<ProjectState> {
  const qs = engine && engine !== "auto" ? `?engine=${encodeURIComponent(engine)}` : "";
  return request<ProjectState>(withExpectedRevision(`/api/projects/${projectId}/ocr${qs}`, expectedRevision), { method: "POST" });
}

/* ── Provider settings: persisted on the backend, the single source of truth ── */

interface BackendCapabilityConfig {
  providerId: string;
  values: Record<string, string>;
  api_key_present?: boolean;
}

/** Public server-side shape of ProviderSettings. Credentials are write-only. */
export interface BackendProviderSection {
  provider: string;
  base_url?: string;
  endpoint_url?: string;
  api_key_present: boolean;
  /** Only present on write payloads; never returned by the backend. */
  api_key?: string;
  model?: string;
  voice?: string;
  deploy_mode?: string;
  langs?: string;
  use_gpu?: boolean;
}

export interface BackendProviderSettings {
  llm: BackendProviderSection;
  image: BackendProviderSection;
  audio: BackendProviderSection;
  ocr: BackendProviderSection;
  video: BackendProviderSection;
  capabilities: Record<string, BackendCapabilityConfig>;
}

export type ProviderSettingsPayload = Omit<BackendProviderSettings, "llm" | "image" | "audio" | "ocr" | "video"> & {
  llm: BackendProviderSection;
  image: BackendProviderSection;
  audio: BackendProviderSection;
  ocr: BackendProviderSection;
  video: BackendProviderSection;
};

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
    configuration_schema: Array<{
      key: string;
      label: string;
      type: "text" | "password" | "select" | "url";
      placeholder?: string;
      required: boolean;
      options?: Array<{ value: string; label: string }>;
    }>;
    supported_operations: string[];
    install_state?: ProviderDefinition["install_state"];
    installed_version?: string | null;
    available_version?: string | null;
    environment_requirements?: Record<string, unknown>;
    environment_blockers?: ProviderDefinition["environment_blockers"];
    install_actions?: ProviderDefinition["install_actions"];
    configuration_status?: ProviderDefinition["configuration_status"];
    rollback_available?: boolean;
    failure?: ProviderDefinition["failure"];
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
    official_homepage_url: descriptor.official_homepage_url,
    api_signup_url: descriptor.api_signup_url,
    api_docs_url: descriptor.api_docs_url,
    repository_url: descriptor.repository_url,
    model_card_url: descriptor.model_card_url,
    code_license_name: descriptor.code_license_name,
    code_license_url: descriptor.code_license_url,
    model_license_name: descriptor.model_license_name,
    model_license_url: descriptor.model_license_url,
    terms_url: descriptor.terms_url,
    privacy_url: descriptor.privacy_url,
    supported_operations: descriptor.supported_operations,
    install_state: descriptor.install_state,
    installed_version: descriptor.installed_version,
    available_version: descriptor.available_version,
    environment_requirements: descriptor.environment_requirements,
    environment_blockers: descriptor.environment_blockers,
    install_actions: descriptor.install_actions,
    configuration_status: descriptor.configuration_status,
    rollback_available: descriptor.rollback_available,
    failure: descriptor.failure,
  }));
}

/** Fetch the trusted registry and backend-owned installation lifecycle facts. */
export async function fetchProviderRegistry(): Promise<ProviderRegistryCatalog> {
  return request<ProviderRegistryCatalog>("/api/providers/registry");
}

/** Fetch and validate the official registry index. This is the only network-discovery action. */
export async function refreshProviderRegistry(): Promise<ProviderRegistryRefreshResponse> {
  return request<ProviderRegistryRefreshResponse>("/api/providers/registry/refresh", { method: "POST" });
}

export async function prepareProviderInstall(providerId: string): Promise<ProviderInstallPrepareResponse> {
  return request<ProviderInstallPrepareResponse>(`/api/providers/registry/${encodeURIComponent(providerId)}/install/prepare`, { method: "POST" });
}

export async function confirmProviderInstall(providerId: string, planId: string, confirmationToken: string): Promise<ProviderInstallResult> {
  return request<ProviderInstallResult>(`/api/providers/registry/${encodeURIComponent(providerId)}/install/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id: planId, confirmation_token: confirmationToken }),
  });
}

export async function configureProviderInstall(providerId: string, values: Record<string, string>): Promise<ProviderInstallResult> {
  return request<ProviderInstallResult>(`/api/providers/registry/${encodeURIComponent(providerId)}/configure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
}

export async function retryProviderInstall(providerId: string): Promise<ProviderInstallPrepareResponse> {
  return request<ProviderInstallPrepareResponse>(`/api/providers/registry/${encodeURIComponent(providerId)}/install/retry`, { method: "POST" });
}

export async function rollbackProviderInstall(providerId: string): Promise<ProviderInstallResult> {
  return request<ProviderInstallResult>(`/api/providers/registry/${encodeURIComponent(providerId)}/rollback`, { method: "POST" });
}

export async function fetchProviderInstallLogs(providerId: string): Promise<ProviderInstallLog[]> {
  return request<ProviderInstallLog[]>(`/api/providers/registry/${encodeURIComponent(providerId)}/install/logs`);
}

/** Persist the provider settings to the backend. */
export async function putProviderSettings(body: ProviderSettingsPayload, init?: Pick<RequestInit, "signal">): Promise<BackendProviderSettings> {
  return request<BackendProviderSettings>("/api/settings/providers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: init?.signal,
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
export function configToBackend(config: ProviderConfig, base?: BackendProviderSettings | null): ProviderSettingsPayload {
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

  const current: ProviderSettingsPayload = base ? {
    ...base,
    llm: { ...base.llm, api_key: base.llm.api_key ?? "" },
    image: { ...base.image, api_key: base.image.api_key ?? "" },
    audio: { ...base.audio, api_key: base.audio.api_key ?? "" },
    ocr: { ...base.ocr, api_key: base.ocr.api_key ?? "" },
    video: { ...base.video, api_key: base.video.api_key ?? "" },
  } : {
    llm: { provider: "deterministic", base_url: "", api_key: "", api_key_present: false, model: "deterministic-v1" },
    image: { provider: "placeholder", endpoint_url: "", api_key: "", api_key_present: false, model: "placeholder-svg" },
    audio: { provider: "placeholder", endpoint_url: "", api_key: "", api_key_present: false, model: "placeholder-tone", voice: "default" },
    ocr: { provider: "", deploy_mode: "local", api_key: "", api_key_present: false, endpoint_url: "", model: "", langs: "", use_gpu: false },
    video: { provider: "", deploy_mode: "local", api_key: "", api_key_present: false, endpoint_url: "", model: "" },
    capabilities: {},
  };
  const next: ProviderSettingsPayload = {
    ...current,
    llm: llm ? {
      ...current.llm,
      provider: llm.providerId,
      base_url: llmV.base_url || llmV.baseUrl || current.llm.base_url || "",
      api_key: preserveSecret(llmV.api_key ?? llmV.apiKey, current.llm.api_key ?? ""),
      model: nonEmptyString(llmV.model, current.llm.model ?? ""),
    } : current.llm,
    image: {
      ...current.image,
      provider: img?.providerId ?? current.image.provider,
      endpoint_url: nonEmptyString(imgV.endpoint ?? imgV.baseUrl ?? imgV.base_url, current.image.endpoint_url ?? ""),
      api_key: preserveSecret(imgV.apiKey ?? imgV.api_key, current.image.api_key ?? ""),
      model: nonEmptyString(imgV.model ?? imgV.deployment, current.image.model ?? ""),
    },
    audio: {
      ...current.audio,
      provider: tts?.providerId ?? current.audio.provider,
      endpoint_url: nonEmptyString(ttsV.endpoint ?? ttsV.baseUrl ?? ttsV.base_url, current.audio.endpoint_url ?? ""),
      api_key: preserveSecret(ttsV.apiKey ?? ttsV.api_key, current.audio.api_key ?? ""),
      model: nonEmptyString(ttsV.model, current.audio.model ?? ""),
      voice: nonEmptyString(ttsV.voice ?? ttsV.voiceId, current.audio.voice ?? ""),
    },
    ocr: {
      ...current.ocr,
      provider: ocr?.providerId ?? current.ocr.provider,
      deploy_mode: current.ocr.deploy_mode ?? "local",
      api_key: preserveSecret(ocrV.apiKey ?? ocrV.api_key, current.ocr.api_key ?? ""),
      endpoint_url: nonEmptyString(ocrV.endpoint ?? ocrV.endpoint_url, current.ocr.endpoint_url ?? ""),
      model: nonEmptyString(ocrV.model, current.ocr.model ?? ""),
      langs: ocrV.langs ?? current.ocr.langs ?? "",
      use_gpu: ocrV.useGpu === "true" || ocrV.use_gpu === "true" || current.ocr.use_gpu === true,
    },
    video: {
      ...current.video,
      provider: vid?.providerId ?? current.video.provider,
      deploy_mode: current.video.deploy_mode ?? "local",
      api_key: preserveSecret(vidV.apiKey ?? vidV.api_key, current.video.api_key ?? ""),
      endpoint_url: nonEmptyString(vidV.endpoint ?? vidV.endpoint_url, current.video.endpoint_url ?? ""),
      model: nonEmptyString(vidV.model, current.video.model ?? ""),
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
      values: { base_url: backend.llm.base_url ?? "", model: backend.llm.model ?? "" },
    };
  }
  if (backend.image?.provider && backend.image.provider !== "placeholder") {
    out.image = {
      providerId: backend.image.provider,
      values: normalizeProviderValues({ base_url: backend.image.endpoint_url ?? "", model: backend.image.model ?? "" }),
    };
  }
  if (backend.audio?.provider && backend.audio.provider !== "placeholder") {
    out.tts = {
      providerId: backend.audio.provider,
      values: normalizeProviderValues({ base_url: backend.audio.endpoint_url ?? "", model: backend.audio.model ?? "", voice: backend.audio.voice ?? "" }),
    };
  }
  if (backend.ocr?.provider) {
    out.ocr = {
      providerId: backend.ocr.provider,
      values: normalizeProviderValues({
        endpoint: backend.ocr.endpoint_url ?? "",
        langs: backend.ocr.langs ?? "",
        useGpu: backend.ocr.use_gpu ? "true" : "false",
      }),
    };
  }
  if (backend.video?.provider) {
    out.video = {
      providerId: backend.video.provider,
      values: normalizeProviderValues({ endpoint: backend.video.endpoint_url ?? "" }),
    };
  }
  return out;
}

function normalizeProviderValues(values: Record<string, string>): Record<string, string> {
  const safeValues = Object.fromEntries(
    Object.entries(values).filter(([key]) => key !== "api_key" && key !== "apiKey"),
  );
  return {
    ...safeValues,
    base_url: safeValues.base_url ?? safeValues.baseUrl ?? safeValues.endpoint ?? "",
    endpoint: safeValues.endpoint ?? safeValues.endpoint_url ?? safeValues.baseUrl ?? "",
    endpoint_url: safeValues.endpoint_url ?? safeValues.endpoint ?? safeValues.baseUrl ?? "",
    use_gpu: safeValues.use_gpu ?? safeValues.useGpu ?? "false",
    voice: safeValues.voice ?? safeValues.voiceId ?? "",
  };
}
