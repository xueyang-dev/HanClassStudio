import { canUseStageAction, exportActionsFromProject, getStageAccess, isCurrentRequest, pipelineStepsFromProject, sanitizeProviderConfig } from "./state";
import type { ProjectState } from "./types";

function equal(actual: unknown, expected: unknown): void {
  if (actual !== expected) throw new Error(`Expected ${String(expected)}, got ${String(actual)}`);
}

function deepEqual(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

const project: ProjectState = {
  project_id: "contract-test",
  status: "parsed",
  stages: [
    { stage_id: "profile", state: "completed", stale: false, blockers: [], warnings: [], required_artifacts: [], available_actions: [] },
    { stage_id: "design", state: "completed", stale: false, blockers: [], warnings: [], required_artifacts: [], available_actions: [] },
    { stage_id: "presentation", state: "blocked", stale: false, blockers: ["binding"], warnings: [], required_artifacts: [], available_actions: [] },
    { stage_id: "quality", state: "not_started", stale: false, blockers: [], warnings: [], required_artifacts: [], available_actions: [] },
    { stage_id: "delivery", state: "not_started", stale: false, blockers: [], warnings: [], required_artifacts: [], available_actions: [] },
  ],
  gate_summary: {
    evidence_alignment: { state: "passed", blocking_reasons: [], warnings: [], stale: false },
    presentation_readiness: { state: "not_run", blocking_reasons: [], warnings: [], stale: false },
    presentation_binding: { state: "blocked", blocking_reasons: ["binding"], warnings: [], stale: false },
    quality_report: { state: "not_run", blocking_reasons: [], warnings: [], stale: false },
    overall_state: "blocked",
    export_allowed: false,
    force_export_allowed: true,
    blocking_reasons: ["binding"],
    warnings: [],
    stale: false,
  },
};

const pipeline = pipelineStepsFromProject(project);
equal(pipeline["pipeline.contract"], "done");
equal(pipeline["pipeline.blueprint"], "done");
equal(pipeline["pipeline.media"], "error");
equal(pipeline["pipeline.quality"], "pending");
equal(pipeline["pipeline.export"], "pending");

const renderedButQualityNotRun = pipelineStepsFromProject({
  ...project,
  artifacts: { render: true },
  stale_state: { stale: false, stale_stages: [], reasons: [] },
  stages: [
    ...project.stages!.filter((stage) => stage.stage_id !== "quality"),
    { stage_id: "quality", state: "completed", stale: false, blockers: [], warnings: [], required_artifacts: [], available_actions: [] },
  ],
  gate_summary: {
    ...project.gate_summary!,
    quality_report: { state: "not_run", blocking_reasons: [], warnings: [], stale: false },
  },
});
equal(renderedButQualityNotRun["pipeline.render"], "done");
equal(renderedButQualityNotRun["pipeline.quality"], "pending");

const actions = exportActionsFromProject(project);
deepEqual(actions, { normal: false, force: true, qualityState: "not_run" });

const qualityAccess = getStageAccess(project, "quality");
equal(qualityAccess.viewable, true);
equal(qualityAccess.executable, false);
equal(canUseStageAction(project, "quality", "render"), false);
equal(getStageAccess(null, "material").viewable, true);
equal(getStageAccess(null, "quality").viewable, false);

const executableProject = {
  ...project,
  stages: project.stages!.map((stage) => stage.stage_id === "quality"
    ? { ...stage, state: "ready" as const, available_actions: ["render"] }
    : stage),
};
equal(getStageAccess(executableProject, "quality").editable, false);
equal(canUseStageAction(executableProject, "quality", "render"), true);

const notRunExport = exportActionsFromProject({
  ...project,
  gate_summary: {
    ...project.gate_summary!,
    force_export_allowed: false,
  },
});
deepEqual(notRunExport, { normal: false, force: false, qualityState: "not_run" });

const persisted = sanitizeProviderConfig({
  llm: { providerId: "openai_compatible", values: { api_key: "secret", model: "teacher" } },
  image: { providerId: "placeholder", values: { apiKey: "another-secret", model: "svg" } },
});
deepEqual(persisted, {
  llm: { providerId: "openai_compatible", values: { model: "teacher" } },
  image: { providerId: "placeholder", values: { model: "svg" } },
});

equal(isCurrentRequest(2, 2), true);
equal(isCurrentRequest(1, 2), false);
equal(isCurrentRequest(2, 2, true), false);

console.log("frontend state contract tests passed");
