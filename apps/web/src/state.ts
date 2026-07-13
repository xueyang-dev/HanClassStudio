import type { ProjectState } from "./types";

export type PipelineStepStatus = "pending" | "running" | "done" | "error";

export const PIPELINE_STEP_KEYS = [
  "pipeline.contract",
  "pipeline.blueprint",
  "pipeline.media",
  "pipeline.render",
  "pipeline.quality",
  "pipeline.export",
] as const;

const PIPELINE_STAGE_MAP: Record<string, string> = {
  "pipeline.contract": "profile",
  "pipeline.blueprint": "design",
  "pipeline.media": "presentation",
  "pipeline.render": "quality",
  "pipeline.quality": "quality",
  "pipeline.export": "delivery",
};

export function pipelineStepsFromProject(project: ProjectState): Record<string, PipelineStepStatus> {
  const stages = new Map((project.stages ?? []).map((stage) => [stage.stage_id, stage.state]));
  return Object.fromEntries(PIPELINE_STEP_KEYS.map((label) => {
    const state = stages.get(PIPELINE_STAGE_MAP[label]);
    const status: PipelineStepStatus = state === "completed" || state === "warning"
      ? "done"
      : state === "running"
        ? "running"
        : state === "blocked" || state === "failed" || state === "stale"
          ? "error"
          : "pending";
    return [label, status];
  })) as Record<string, PipelineStepStatus>;
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
