import type {
  AgentPackage,
  AgentValidation,
  ArtifactTree,
  ComponentRegistry,
  LessonBlueprint,
  LessonProfile,
  ProjectState
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

export function exportUrl(projectId: string): string {
  return `${API_BASE}/api/projects/${projectId}/export`;
}

export function previewUrl(path?: string | null): string | null {
  return path ? `${API_BASE}${path}` : null;
}
