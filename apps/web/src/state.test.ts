import { canUnifyVisualThemeMedia, canUseStageAction, exportActionsFromProject, getAvailableCapabilityProviders, getCapabilityProviders, getCapabilityRegistryProviders, getConfigurableCapabilityProviders, getNextWorkflowAction, getStageAccess, isCurrentRequest, pipelineStepsFromProject, providerConfigSnapshot, providerStatus, sanitizeProviderConfig, shouldFetchDesignSummary, shouldPersistProviderConfig } from "./state";
import type { ProjectState, ProviderRegistryCatalog } from "./types";

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

const nextActionProject = {
  ...project,
  stages: project.stages!.map((stage) => stage.stage_id === "profile"
    ? { ...stage, state: "ready" as const, available_actions: ["confirm_profile"] }
    : stage),
};
deepEqual(getNextWorkflowAction(nextActionProject), { stageId: "profile", action: "confirm_profile" });
deepEqual(getNextWorkflowAction(executableProject), { stageId: "quality", action: "render" });
equal(getNextWorkflowAction(null), null);
equal(shouldFetchDesignSummary(project), true);
equal(shouldFetchDesignSummary({ ...project, stages: project.stages!.map((stage) => stage.stage_id === "design" ? { ...stage, state: "ready" as const } : stage) }), false);
equal(shouldFetchDesignSummary({ ...project, stages: project.stages!.map((stage) => stage.stage_id === "design" ? { ...stage, stale: true } : stage) }), false);

const providerCatalog = [
  {
    id: "openai_compatible",
    name: "OpenAI-compatible",
    category: "cloud" as const,
    capability: "llm" as const,
    description: "",
    fields: [],
    implemented: true,
    configurable: true,
    configured: false,
    available: true,
    experimental: false,
    supported_operations: ["blueprint"],
  },
];
deepEqual(providerStatus({ providerId: "openai_compatible", values: { model: "draft" } }, "llm", providerCatalog), { configured: false, available: false });
deepEqual(providerStatus({ providerId: "openai_compatible", values: { model: "saved" } }, "llm", providerCatalog.map((item) => ({ ...item, configured: true }))), { configured: true, available: true });
deepEqual(providerStatus({ providerId: "openai_compatible", values: {} }, "llm", providerCatalog.map((item) => ({ ...item, configured: true, available: false }))), { configured: true, available: false });

const registry: ProviderRegistryCatalog = {
  providers: [
    {
      entry: {
        provider_id: "hcs_mock_ocr",
        capability: "ocr",
        display_name: "OCR sandbox",
        description: "",
        source_url: "https://github.com/xueyang-dev/HanClassStudio",
        repository: "xueyang-dev/HanClassStudio",
        publisher: "HanClassStudio",
        license: "MIT",
        trust_level: "first_party",
        version: "0.1.0",
        source_ref: "v0.1.0",
        checksum_sha256: "0".repeat(64),
        manifest_version: "1",
        manifest_digest: "1".repeat(64),
        configuration_schema: [],
        requirements: {},
        supported_operations: ["ocr"],
        executor: "mock",
        mock_only: true,
        experimental: true,
      },
      installation: {
        provider_id: "hcs_mock_ocr",
        capability: "ocr",
        install_state: "ready",
        installed_version: null,
        available_version: "0.1.0",
        active_version: null,
        previous_version: null,
        configuration_status: "unknown",
        api_key_present: false,
        environment_blockers: [],
        blockers: [],
        failure: null,
        rollback_available: false,
        current_plan_id: null,
        updated_at: "",
      },
      environment: { platform: "macos", architecture: "arm64", python_version: "3.11", free_disk_mb: 1000, gpu_available: false, blockers: [], checked_at: "" },
      install_actions: ["prepare_install"],
    },
  ],
};
const ocrCatalog = [
  { ...providerCatalog[0], id: "tesseract", name: "Tesseract", capability: "ocr" as const, category: "local" as const, available: false },
  { ...providerCatalog[0], id: "hcs_mock_ocr", name: "OCR sandbox", capability: "ocr" as const, category: "local" as const, available: false, experimental: true },
];
equal(getCapabilityProviders("ocr", "local", ocrCatalog).length, 2);
equal(getConfigurableCapabilityProviders("ocr", "local", ocrCatalog).length, 2);
equal(getAvailableCapabilityProviders("ocr", "local", ocrCatalog).length, 0);
equal(getCapabilityRegistryProviders("ocr", registry).length, 1);
deepEqual(getCapabilityRegistryProviders("llm", registry), []);
const availableOcrCatalog = ocrCatalog.map((item) => item.id === "hcs_mock_ocr" ? { ...item, available: true, configured: true } : item);
equal(getAvailableCapabilityProviders("ocr", "local", availableOcrCatalog).map((item) => item.id).join(","), "hcs_mock_ocr");
const codexBridgeCatalog = [{
  ...providerCatalog[0],
  id: "codex_chatgpt",
  name: "Codex ChatGPT Bridge",
  category: "local" as const,
  available: false,
  configured: false,
}];
equal(getConfigurableCapabilityProviders("llm", "local", codexBridgeCatalog).map((item) => item.id).join(","), "codex_chatgpt");
equal(getAvailableCapabilityProviders("llm", "local", codexBridgeCatalog).length, 0);

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
  tts: { providerId: "custom", values: { token: "third-secret", voice: "default" } },
});
deepEqual(persisted, {
  llm: { providerId: "openai_compatible", values: { model: "teacher" } },
  image: { providerId: "placeholder", values: { model: "svg" } },
  tts: { providerId: "custom", values: { voice: "default" } },
});

const providerBaseline = providerConfigSnapshot({
  llm: { providerId: "deterministic", values: { model: "deterministic-v1", api_key: "" } },
});
equal(providerConfigSnapshot({
  llm: { providerId: "deterministic", values: { api_key: "", model: "deterministic-v1" } },
}), providerBaseline);
equal(providerConfigSnapshot({
  llm: { providerId: "deterministic", values: { model: "teacher-edited", api_key: "" } },
}) === providerBaseline, false);
equal(shouldPersistProviderConfig({
  llm: { providerId: "deterministic", values: { model: "deterministic-v1", api_key: "" } },
}, providerBaseline, false), false);
equal(shouldPersistProviderConfig({
  llm: { providerId: "deterministic", values: { model: "teacher-edited", api_key: "" } },
}, providerBaseline, true), true);

equal(isCurrentRequest(2, 2), true);
equal(isCurrentRequest(1, 2), false);
equal(isCurrentRequest(2, 2, true), false);

const mixedThemeProject: ProjectState = {
  ...project,
  visual_theme: {
    selection: { mode: "manual", selected_theme_id: "warm-story", theme_version: "1" },
    effective_theme_id: "warm-story",
    effective_theme_version: "1",
    media_state: "mixed",
    mismatched_media_count: 2,
    mismatched_media_ids: ["hero", "scene"],
    provider_support: [],
    regeneration_available: true,
  },
  stages: project.stages!.map((stage) => stage.stage_id === "presentation"
    ? { ...stage, available_actions: ["edit_blueprint", "regenerate_media_for_theme"] }
    : stage),
};
equal(canUnifyVisualThemeMedia(mixedThemeProject), true);
equal(canUnifyVisualThemeMedia({
  ...mixedThemeProject,
  stages: mixedThemeProject.stages!.map((stage) => stage.stage_id === "presentation" ? { ...stage, available_actions: ["edit_blueprint"] } : stage),
}), false);
equal(canUnifyVisualThemeMedia({
  ...mixedThemeProject,
  visual_theme: { ...mixedThemeProject.visual_theme!, regeneration_available: false },
}), false);

console.log("frontend state contract tests passed");
