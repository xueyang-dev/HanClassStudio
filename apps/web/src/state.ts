import type { ProjectState, ProviderCapability, ProviderConfig } from "./types";

export type PipelineStepStatus = "pending" | "running" | "done" | "error";

export const PIPELINE_STEP_KEYS = [
  "pipeline.contract",
  "pipeline.blueprint",
  "pipeline.media",
  "pipeline.render",
  "pipeline.quality",
  "pipeline.export",
] as const;

/**
 * Provider credentials are write-only from the browser's perspective. Keep
 * them in memory only long enough to submit an explicit edit, never in
 * localStorage or other persisted client state.
 */
export function sanitizeProviderConfig(config: ProviderConfig): ProviderConfig {
  const sanitized: ProviderConfig = {};
  for (const [capability, value] of Object.entries(config) as [ProviderCapability, ProviderConfig[ProviderCapability]][]) {
    if (!value?.providerId) continue;
    const values = Object.fromEntries(
      Object.entries(value.values ?? {}).filter(([key]) => key !== "api_key" && key !== "apiKey"),
    );
    sanitized[capability] = { providerId: value.providerId, values };
  }
  return sanitized;
}

export function isCurrentRequest(sequence: number, currentSequence: number, aborted = false): boolean {
  return !aborted && sequence === currentSequence;
}

const PIPELINE_STAGE_MAP: Record<string, string> = {
  "pipeline.contract": "profile",
  "pipeline.blueprint": "design",
  "pipeline.media": "presentation",
  "pipeline.export": "delivery",
};

function statusFromStage(state: string | undefined): PipelineStepStatus {
  return state === "completed" || state === "warning"
    ? "done"
    : state === "running"
      ? "running"
      : state === "blocked" || state === "failed" || state === "stale"
        ? "error"
        : "pending";
}

export function pipelineStepsFromProject(project: ProjectState): Record<string, PipelineStepStatus> {
  const stages = new Map((project.stages ?? []).map((stage) => [stage.stage_id, stage.state]));
  const qualityState = project.gate_summary?.quality_report.state;
  const renderStale = project.stale_state?.stale_stages?.includes("render") ?? false;
  const renderState: PipelineStepStatus = renderStale
    ? "error"
    : project.artifacts?.render
      ? "done"
      : statusFromStage(stages.get("quality")) === "running"
        ? "running"
        : statusFromStage(stages.get("quality")) === "error"
          ? "error"
          : "pending";
  const qualityStatus: PipelineStepStatus = qualityState === "passed" || qualityState === "warning"
    ? "done"
    : qualityState === "running"
      ? "running"
      : qualityState === "blocked" || qualityState === "failed" || qualityState === "stale"
        ? "error"
        : "pending";
  const steps: Record<string, PipelineStepStatus> = {};
  for (const label of PIPELINE_STEP_KEYS) {
    if (label === "pipeline.render") {
      steps[label] = renderState;
    } else if (label === "pipeline.quality") {
      steps[label] = qualityStatus;
    } else {
      steps[label] = statusFromStage(stages.get(PIPELINE_STAGE_MAP[label]));
    }
  }
  return steps;
}

export function exportActionsFromProject(project: ProjectState | null): {
  normal: boolean;
  force: boolean;
  qualityState: string;
} {
  const summary = project?.gate_summary;
  return {
    normal: Boolean(summary?.export_allowed),
    force: Boolean(summary?.force_export_allowed && !summary.export_allowed),
    qualityState: summary?.quality_report.state ?? "not_run",
  };
}
