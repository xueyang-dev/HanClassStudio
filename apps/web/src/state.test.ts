import { exportActionsFromProject, pipelineStepsFromProject } from "./state";
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

const actions = exportActionsFromProject(project);
deepEqual(actions, { normal: false, force: true, qualityState: "not_run" });

console.log("frontend state contract tests passed");
