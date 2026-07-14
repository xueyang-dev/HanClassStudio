import type { ProjectState, ProviderCapability, ProviderConfig, StageState } from "./types";

export type PipelineStepStatus = "pending" | "running" | "done" | "error";

export type WorkflowStageId = "material" | "profile" | "design" | "presentation" | "quality" | "delivery";

export interface StageAccess {
  viewable: boolean;
  editable: boolean;
  executable: boolean;
  state: StageState;
  availableActions: string[];
  blockers: string[];
  warnings: string[];
}

export interface WorkflowAction {
  stageId: WorkflowStageId;
  action: string;
}

const EDITABLE_ACTIONS = new Set([
  "upload",
  "rerun_ocr",
  "infer_profile",
  "confirm_profile",
  "edit_blueprint",
  "generate_blueprint",
  "generate_media",
  "review_media",
  "replace_media",
  "force_regenerate_media",
]);

/**
 * Keep navigation visibility separate from backend-declared operations. A
 * blocked or not-yet-run stage remains viewable so its explanation can be
 * inspected, while only actions returned by the backend are executable.
 */
export function getStageAccess(project: ProjectState | null, stageId: WorkflowStageId): StageAccess {
  const stage = project?.stages?.find((item) => item.stage_id === stageId);
  if (!stage) {
    return {
      viewable: stageId === "material",
      editable: false,
      executable: false,
      state: "not_started",
      availableActions: [],
      blockers: [],
      warnings: [],
    };
  }
  const availableActions = Array.isArray(stage.available_actions) ? stage.available_actions : [];
  return {
    viewable: true,
    editable: availableActions.some((action) => EDITABLE_ACTIONS.has(action)),
    executable: availableActions.length > 0,
    state: stage.state,
    availableActions,
    blockers: stage.blockers ?? [],
    warnings: stage.warnings ?? [],
  };
}

export function canUseStageAction(project: ProjectState | null, stageId: WorkflowStageId, action: string): boolean {
  const access = getStageAccess(project, stageId);
  return access.executable && access.availableActions.includes(action);
}

/**
 * Return one backend-declared action that moves the workflow forward. This is
 * intentionally a single answer: when an upstream prerequisite is available,
 * downstream panels should not present several misleading executable buttons.
 */
export function getNextWorkflowAction(project: ProjectState | null): WorkflowAction | null {
  if (!project) return null;
  const priority: Array<[WorkflowStageId, string[]]> = [
    ["profile", ["confirm_profile", "infer_profile"]],
    ["design", ["generate_blueprint", "run_pipeline"]],
    ["presentation", ["generate_media", "edit_blueprint"]],
    ["quality", ["render", "run_quality"]],
    ["delivery", ["export", "force_export"]],
  ];
  for (const [stageId, actions] of priority) {
    const access = getStageAccess(project, stageId);
    if (access.state === "completed" || access.state === "warning") continue;
    const action = actions.find((candidate) => access.availableActions.includes(candidate));
    if (action) return { stageId, action };
  }
  return null;
}

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

/** Stable in-memory comparison key for provider edits. It intentionally keeps
 * credential fields in memory for change detection but is never persisted or
 * sent to logs/storage by this helper. */
export function providerConfigSnapshot(config: ProviderConfig): string {
  const ordered = Object.keys(config)
    .sort()
    .reduce<Record<string, unknown>>((result, capability) => {
      const value = config[capability as ProviderCapability];
      if (!value) return result;
      result[capability] = {
        providerId: value.providerId,
        values: Object.keys(value.values ?? {})
          .sort()
          .reduce<Record<string, string>>((values, key) => {
            values[key] = value.values[key];
            return values;
          }, {}),
      };
      return result;
    }, {});
  return JSON.stringify(ordered);
}

export function shouldPersistProviderConfig(config: ProviderConfig, baseline: string | null, loaded: boolean): boolean {
  return loaded && baseline !== providerConfigSnapshot(config);
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
