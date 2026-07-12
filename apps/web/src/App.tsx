import { type ChangeEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Clipboard,
  Cpu,
  FileUp,
  Image,
  Layers3,
  Loader2,
  MessageSquare,
  Mic,
  MonitorPlay,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  Video,
  X
} from "lucide-react";
import {
  backendToConfig,
  configToBackend,
  exportEditablePptx,
  exportUrl,
  fetchProviderSettings,
  forceExportProject,
  generateAgentPackage,
  generateBlueprint,
  generateMedia,
  getComponentRegistry,
  getOcrStatus,
  listProjectArtifacts,
  previewUrl,
  putProviderSettings,
  rerunOcr,
  renderProject,
  runPipeline,
  saveBlueprint,
  saveProfile,
  uploadProject,
  validateAgentOutput
} from "./api";
import { useI18n, UI_LANGUAGES, type UiLang } from "./i18n";
import type {
  AgentPackage,
  AgentValidation,
  ArtifactEntry,
  ArtifactTree,
  CapabilityConfig,
  ComponentConfig,
  ComponentRegistry,
  ContentBlock,
  EditablePptxExportResponse,
  GenerationMode,
  LessonBlueprint,
  LessonProfile,
  LessonSlide,
  OcrStatusResponse,
  ProviderCapability,
  ProviderConfig,
  ProviderDefinition,
  ProjectState,
  SlideComponent,
  SourceAnalysis,
  SourceAnalysisPage
} from "./types";

const languages = ["English", "Arabic", "Russian", "Thai", "Korean", "Japanese", "Vietnamese", "Indonesian"];

const PROVIDER_STORAGE_KEY = "hcs_provider_config";
const ONBOARDING_STORAGE_KEY = "hcs_onboarding_seen";

const CAPABILITY_ORDER: ProviderCapability[] = ["ocr", "image", "tts", "video"];

const CAPABILITY_META: Record<ProviderCapability, { labelKey: string; icon: typeof Cpu; defaultProvider: string }> = {
  ocr: { labelKey: "provider.ocr.label", icon: MessageSquare, defaultProvider: "paddle_ocr" },
  image: { labelKey: "provider.image.label", icon: Image, defaultProvider: "openai" },
  tts: { labelKey: "provider.tts.label", icon: Mic, defaultProvider: "openai_tts" },
  video: { labelKey: "provider.video.label", icon: Video, defaultProvider: "runway" },
};

const PROVIDER_CATALOG: ProviderDefinition[] = [
  {
    id: "openai",
    name: "OpenAI",
    category: "cloud",
    capabilities: ["image", "tts"],
    descriptionKey: "provider.desc.openai",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "baseUrl", labelKey: "provider.field.baseUrl", type: "url", placeholderKey: "provider.field.baseUrl.optional", required: false },
      { key: "model", labelKey: "provider.field.model", type: "select", required: true, options: [
        { value: "gpt-4o", label: "GPT-4o" },
        { value: "gpt-4o-mini", label: "GPT-4o Mini" },
        { value: "gpt-4-turbo", label: "GPT-4 Turbo" }
      ]}
    ]
  },
  {
    id: "anthropic",
    name: "Anthropic Claude",
    category: "cloud",
    capabilities: [],
    descriptionKey: "provider.desc.anthropic",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "model", labelKey: "provider.field.model", type: "select", required: true, options: [
        { value: "claude-3-5-sonnet-20240620", label: "Claude 3.5 Sonnet" },
        { value: "claude-3-opus-20240229", label: "Claude 3 Opus" },
        { value: "claude-3-haiku-20240307", label: "Claude 3 Haiku" }
      ]}
    ]
  },
  {
    id: "azure_openai",
    name: "Azure OpenAI",
    category: "cloud",
    capabilities: ["image"],
    descriptionKey: "provider.desc.azure",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "endpoint", labelKey: "provider.field.endpoint", type: "url", required: true },
      { key: "deployment", labelKey: "provider.field.deployment", type: "text", required: true }
    ]
  },
  {
    id: "google",
    name: "Google Gemini",
    category: "cloud",
    capabilities: ["image"],
    descriptionKey: "provider.desc.google",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "model", labelKey: "provider.field.model", type: "select", required: true, options: [
        { value: "gemini-1.5-pro", label: "Gemini 1.5 Pro" },
        { value: "gemini-1.5-flash", label: "Gemini 1.5 Flash" }
      ]}
    ]
  },
  {
    id: "ollama",
    name: "Ollama",
    category: "local",
    capabilities: ["image"],
    descriptionKey: "provider.desc.ollama",
    fields: [
      { key: "baseUrl", labelKey: "provider.field.baseUrl", type: "url", required: true, placeholderKey: "provider.field.baseUrl.ollama" },
      { key: "model", labelKey: "provider.field.model", type: "text", required: true, placeholderKey: "provider.field.model.example" }
    ]
  },
  {
    id: "lm_studio",
    name: "LM Studio",
    category: "local",
    capabilities: [],
    descriptionKey: "provider.desc.lm_studio",
    fields: [
      { key: "baseUrl", labelKey: "provider.field.baseUrl", type: "url", required: true, placeholderKey: "provider.field.baseUrl.lmstudio" },
      { key: "model", labelKey: "provider.field.model", type: "text", required: false, placeholderKey: "provider.field.model.optional" }
    ]
  },
  {
    id: "openai_tts",
    name: "OpenAI TTS",
    category: "cloud",
    capabilities: ["tts"],
    descriptionKey: "provider.desc.openai_tts",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "model", labelKey: "provider.field.ttsModel", type: "select", required: true, options: [
        { value: "tts-1", label: "TTS-1" },
        { value: "tts-1-hd", label: "TTS-1 HD" }
      ]},
      { key: "voice", labelKey: "provider.field.voice", type: "select", required: true, options: [
        { value: "alloy", label: "Alloy" },
        { value: "echo", label: "Echo" },
        { value: "fable", label: "Fable" },
        { value: "onyx", label: "Onyx" },
        { value: "nova", label: "Nova" },
        { value: "shimmer", label: "Shimmer" }
      ]}
    ]
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    category: "cloud",
    capabilities: ["tts"],
    descriptionKey: "provider.desc.elevenlabs",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "voiceId", labelKey: "provider.field.voiceId", type: "text", required: true }
    ]
  },
  {
    id: "macos_say",
    name: "macOS Say",
    category: "local",
    capabilities: ["tts"],
    descriptionKey: "provider.desc.macos_say",
    fields: [
      { key: "voice", labelKey: "provider.field.voice", type: "text", required: false, placeholderKey: "provider.field.voice.optional" }
    ]
  },
  {
    id: "runway",
    name: "Runway",
    category: "cloud",
    capabilities: ["video"],
    descriptionKey: "provider.desc.runway",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true }
    ]
  },
  {
    id: "paddle_ocr",
    name: "PaddleOCR",
    category: "local",
    capabilities: ["ocr"],
    descriptionKey: "provider.desc.paddle_ocr",
    fields: [
      { key: "useGpu", labelKey: "provider.field.useGpu", type: "select", required: false, options: [
        { value: "false", label: "CPU" },
        { value: "true", label: "GPU" }
      ]}
    ]
  },
  {
    id: "tesseract",
    name: "Tesseract",
    category: "local",
    capabilities: ["ocr"],
    descriptionKey: "provider.desc.tesseract",
    fields: [
      { key: "langs", labelKey: "provider.field.langs", type: "text", required: false, placeholderKey: "provider.field.langs.example" }
    ]
  },
  {
    id: "azure_doc",
    name: "Azure Document Intelligence",
    category: "cloud",
    capabilities: ["ocr"],
    descriptionKey: "provider.desc.azure_doc",
    fields: [
      { key: "apiKey", labelKey: "provider.field.apiKey", type: "password", required: true },
      { key: "endpoint", labelKey: "provider.field.endpoint", type: "url", required: true }
    ]
  }
];

function getProviderById(id: string): ProviderDefinition | undefined {
  return PROVIDER_CATALOG.find((p) => p.id === id);
}

function isCapabilityConfigured(config: CapabilityConfig | undefined): boolean {
  if (!config) return false;
  const def = getProviderById(config.providerId);
  if (!def) return false;
  return def.fields.filter((f) => f.required).every((f) => config.values[f.key]?.trim());
}

function readStoredProviderConfig(): ProviderConfig {
  try {
    const raw = localStorage.getItem(PROVIDER_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ProviderConfig) : {};
  } catch {
    return {};
  }
}

function writeStoredProviderConfig(config: ProviderConfig) {
  try {
    localStorage.setItem(PROVIDER_STORAGE_KEY, JSON.stringify(config));
  } catch {
    // ignore storage failures
  }
}

function readOnboardingSeen(): boolean {
  try {
    return localStorage.getItem(ONBOARDING_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeOnboardingSeen() {
  try {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, "1");
  } catch {
    // ignore
  }
}

const modes: Array<{ value: GenerationMode; titleKey: string; detailKey: string }> = [
  { value: "faithful", titleKey: "mode.faithful", detailKey: "mode.faithful.detail" },
  { value: "guided_redesign", titleKey: "mode.guided", detailKey: "mode.guided.detail" },
  { value: "reimagined", titleKey: "mode.reimagined", detailKey: "mode.reimagined.detail" }
];

const steps = [
  { id: "upload", titleKey: "step.upload", icon: FileUp },
  { id: "profile", titleKey: "step.profile", icon: Settings2 },
  { id: "mode", titleKey: "step.mode", icon: Sparkles },
  { id: "outline", titleKey: "step.outline", icon: Layers3 },
  { id: "preview", titleKey: "step.preview", icon: MonitorPlay }
] as const;

type StepId = (typeof steps)[number]["id"];
type PipelineStepStatus = "pending" | "running" | "done" | "error";

const pipelineStepKeys = [
  "pipeline.contract",
  "pipeline.blueprint",
  "pipeline.media",
  "pipeline.render",
  "pipeline.quality",
  "pipeline.export"
];

const emptyProfile: LessonProfile = {
  lesson_title: "",
  subject: "国际中文",
  learner_level: "Beginner",
  target_students: "国际中文学习者",
  scaffolding_language: "English",
  lesson_type: "New lesson",
  generation_mode: "guided_redesign",
  estimated_duration: "45 minutes"
};

function initialPipelineSteps(): Record<string, PipelineStepStatus> {
  return Object.fromEntries(pipelineStepKeys.map((label) => [label, "pending"])) as Record<string, PipelineStepStatus>;
}

function markPipelineStep(label: string, status: PipelineStepStatus = "running") {
  return (current: Record<string, PipelineStepStatus>) => ({ ...current, [label]: status });
}

function readableError(err: unknown, t: (key: string, vars?: Record<string, string | number>) => string): string {
  const message = err instanceof Error ? err.message : t("error.fallback");
  if (message.toLowerCase().includes("failed to fetch")) {
    return t("error.fetch");
  }
  if (message.includes("Project needs")) {
    return t("error.incomplete");
  }
  return message || t("error.fallback");
}

export function App() {
  const { t } = useI18n();
  const [activeStep, setActiveStep] = useState<StepId>("upload");
  const [project, setProject] = useState<ProjectState | null>(null);
  const [profile, setProfile] = useState<LessonProfile>(emptyProfile);
  const [blueprint, setBlueprint] = useState<LessonBlueprint | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [previewKey, setPreviewKey] = useState(0);
  const [confirmedProfileProjectId, setConfirmedProfileProjectId] = useState<string>("");
  const [pipelineSteps, setPipelineSteps] = useState<Record<string, PipelineStepStatus>>(() => initialPipelineSteps());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [artifactTree, setArtifactTree] = useState<ArtifactTree | null>(null);
  const [componentRegistry, setComponentRegistry] = useState<ComponentRegistry>({});
  const [ocrStatus, setOcrStatus] = useState<OcrStatusResponse | null>(null);
  const [agentPackage, setAgentPackage] = useState<AgentPackage | null>(null);
  const [agentValidation, setAgentValidation] = useState<AgentValidation | null>(null);
  const [agentCopied, setAgentCopied] = useState(false);
  const [pptxExport, setPptxExport] = useState<EditablePptxExportResponse | null>(null);
  const [autoFilledFields, setAutoFilledFields] = useState<Set<string>>(new Set());
  const [userEditedFields, setUserEditedFields] = useState<Set<string>>(new Set());
  const [providerConfig, setProviderConfig] = useState<ProviderConfig>(() => readStoredProviderConfig());
  const [settingsSynced, setSettingsSynced] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const settingsLoadedRef = useRef(false);

  const progressIndex = useMemo(() => {
    if (project?.preview_url) return 4;
    if (project?.lesson_blueprint) return 3;
    if (project?.lesson_profile) return 2;
    if (project?.source_material) return 1;
    return 0;
  }, [project]);

  const componentOptions = useMemo(
    () => Object.keys(componentRegistry).filter((name) => !componentRegistry[name]?.experimental).sort(),
    [componentRegistry]
  );

  useEffect(() => {
    getComponentRegistry()
      .then(setComponentRegistry)
      .catch((err) => setError(readableError(err, t)));
    if (!readOnboardingSeen()) {
      setOnboardingOpen(true);
    }
  }, []);

  // Load persisted provider settings from the backend (source of truth) on mount.
  useEffect(() => {
    fetchProviderSettings()
      .then((backend) => {
        const fromBackend = backendToConfig(backend);
        if (Object.keys(fromBackend).length > 0) {
          setProviderConfig(fromBackend);
          writeStoredProviderConfig(fromBackend);
        } else if (Object.keys(providerConfig).length > 0) {
          // Promote any existing local-only config to the server.
          putProviderSettings(configToBackend(providerConfig)).catch(() => {});
        }
        setSettingsSynced(true);
      })
      .catch(() => setSettingsSynced(false))
      .finally(() => {
        settingsLoadedRef.current = true;
      });
  }, []);

  // Persist provider settings to the backend whenever they change (best-effort,
  // debounced, and skipped until the initial load has resolved).
  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    const handle = setTimeout(() => {
      putProviderSettings(configToBackend(providerConfig))
        .then(() => setSettingsSynced(true))
        .catch(() => setSettingsSynced(false));
    }, 400);
    return () => clearTimeout(handle);
  }, [providerConfig]);

  useEffect(() => {
    getOcrStatus()
      .then(setOcrStatus)
      .catch(() => {
        // OCR status is non-critical; the panel degrades gracefully.
        setOcrStatus(null);
      });
  }, []);

  async function refreshArtifacts(projectId: string) {
    try {
      setArtifactTree(await listProjectArtifacts(projectId));
    } catch {
      setArtifactTree(null);
    }
  }

  function handleProfileChange(next: LessonProfile) {
    setProfile(next);
    // Track which fields the user has manually edited
    const edited = new Set(userEditedFields);
    for (const key of Object.keys(emptyProfile) as (keyof LessonProfile)[]) {
      if (next[key] !== profile[key]) {
        edited.add(key);
      }
    }
    setUserEditedFields(edited);
  }

  function updateProject(next: ProjectState) {
    setProject(next);
    if (next.lesson_profile) {
      setProfile(next.lesson_profile);
      // Detect which fields differ from emptyProfile defaults → auto-filled by backend
      const filled = new Set<string>();
      for (const key of Object.keys(emptyProfile) as (keyof LessonProfile)[]) {
        if (next.lesson_profile[key] !== emptyProfile[key] && String(next.lesson_profile[key]).trim() !== "") {
          filled.add(key);
        }
      }
      setAutoFilledFields(filled);
      setUserEditedFields(new Set()); // reset user edits on new upload
    }
    if (next.lesson_blueprint) setBlueprint(next.lesson_blueprint);
    void refreshArtifacts(next.project_id);
    if (next.preview_url) {
      setPreviewError("");
      setPreviewLoading(true);
      setPreviewKey((key) => key + 1);
    }
  }

  async function run(label: string, action: () => Promise<ProjectState>, nextStep?: StepId) {
    setBusy(label);
    setError("");
    try {
      const next = await action();
      updateProject(next);
      if (nextStep) setActiveStep(nextStep);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setConfirmedProfileProjectId("");
    setPipelineSteps(initialPipelineSteps());
    setArtifactTree(null);
    setAgentPackage(null);
    setAgentValidation(null);
    setAgentCopied(false);
    setPptxExport(null);
    setPreviewError("");
    setPreviewLoading(false);
    await run(t("busy.parsing"), () => uploadProject(file), "profile");
  }

  async function handleRerunOcr(engine?: string) {
    if (!project) return;
    setBusy(t("ocr.busy"));
    setError("");
    try {
      const next = await rerunOcr(project.project_id, engine);
      updateProject(next);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleSaveProfile(nextStep?: StepId) {
    if (!project) return;
    await run(
      t("busy.savingProfile"),
      async () => {
        const next = await saveProfile(project.project_id, profile);
        setConfirmedProfileProjectId(next.project_id);
        return next;
      },
      nextStep
    );
  }

  async function handleRunFullPipeline() {
    if (!project) return;
    setBusy(t("busy.generating"));
    setError("");
    setPipelineSteps(markPipelineStep("pipeline.contract"));
    try {
      const saved = await saveProfile(project.project_id, profile);
      setConfirmedProfileProjectId(saved.project_id);
      updateProject(saved);
      setPipelineSteps(markPipelineStep("pipeline.contract", "done"));
      setPipelineSteps(markPipelineStep("pipeline.blueprint"));
      const next = await runPipeline(project.project_id);
      const nextSteps = initialPipelineSteps();
      for (const label of pipelineStepKeys) {
        nextSteps[label] = "done";
      }
      if (next.quality_report?.state === "blocked") {
        nextSteps["pipeline.export"] = "error";
      }
      setPipelineSteps(nextSteps);
      updateProject(next);
      setActiveStep("preview");
    } catch (err) {
      setError(readableError(err, t));
      setPipelineSteps((current) => {
        const next = { ...current };
        const running = pipelineStepKeys.find((label) => next[label] === "running");
        if (running) next[running] = "error";
        return next;
      });
    } finally {
      setBusy("");
    }
  }

  async function handleForceExport() {
    if (!project) return;
    setBusy(t("busy.exporting"));
    setError("");
    try {
      const blob = await forceExportProject(project.project_id);
      downloadBlob(blob, `HanClassStudio_Output_${project.project_id}.zip`);
      setProject({ ...project, export_url: project.export_url ?? `/api/projects/${project.project_id}/export` });
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleEditablePptxExport(force = false) {
    if (!project) return;
    setBusy(force ? t("busy.exportingPptxForce") : t("busy.exportingPptx"));
    setError("");
    try {
      const next = await exportEditablePptx(project.project_id, force);
      setPptxExport(next);
      await refreshArtifacts(project.project_id);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleGenerateAgentPackage() {
    if (!project) return;
    setBusy(t("busy.agentPackage"));
    setError("");
    try {
      const next = await generateAgentPackage(project.project_id);
      setAgentPackage(next);
      setAgentValidation(null);
      await refreshArtifacts(project.project_id);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleValidateAgentOutput() {
    if (!project) return;
    setBusy(t("busy.agentValidate"));
    setError("");
    try {
      const next = await validateAgentOutput(project.project_id);
      setAgentValidation(next);
      await refreshArtifacts(project.project_id);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleCopyAgentTask() {
    if (!agentPackage) return;
    const text = `${agentPackage.task_text}\n\n---\n\n${agentPackage.rules_text}`;
    try {
      await navigator.clipboard.writeText(text);
      setAgentCopied(true);
      window.setTimeout(() => setAgentCopied(false), 1600);
    } catch (err) {
      setError(readableError(err, t));
    }
  }

  const qualityState = project?.quality_report?.state ?? project?.quality_state ?? null;
  const qualityBlocked = qualityState === "blocked";
  const issueCount = project?.quality_report
    ? safeList(project.quality_report.blocking).length + safeList(project.quality_report.warnings).length
    : 0;
  const profileConfirmed = Boolean(project?.project_id && confirmedProfileProjectId === project.project_id);
  const canRunPipeline = Boolean(project?.project_id && profileConfirmed && !busy);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label={t("nav.workflow")}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            H
          </div>
          <div>
            <strong>HanClassStudio</strong>
            <span>{t("app.version")}</span>
          </div>
        </div>
        <nav className="step-list" aria-label={t("nav.workflow")}>
          {steps.map((step, index) => {
            const Icon = step.icon;
            const available = index <= progressIndex + 1;
            return (
              <button
                key={step.id}
                type="button"
                className={activeStep === step.id ? "active" : ""}
                disabled={!available}
                onClick={() => setActiveStep(step.id)}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{t(step.titleKey)}</span>
                {index <= progressIndex && <CheckCircle2 size={16} aria-hidden="true" />}
              </button>
            );
          })}
        </nav>
        <ProviderStatusPanel config={providerConfig} onOpenSettings={() => setSettingsOpen(true)} />
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <p className="eyebrow">{t("topbar.eyebrow")}</p>
            <h1>{profile.lesson_title || t("topbar.newLesson")}</h1>
          </div>
          <div className="topbar-aside">
            <div className="status-strip">
              <span>{project?.project_id ? t("status.project", { id: project.project_id }) : t("status.noProject")}</span>
              <span>{project?.status ?? t("status.ready")}</span>
              <span>{project?.route ? t("status.route", { route: project.route }) : t("status.routePending")}</span>
              <span>{profileConfirmed ? t("status.profileConfirmed") : t("status.profilePending")}</span>
              <span>{qualityState ? t("status.quality", { state: qualityState }) : t("status.qualityPending")}</span>
              <span>{issueCount === 0 ? t("status.qualityPass") : t("status.issues", { n: issueCount })}</span>
            </div>
            <div className="top-actions">
              <button type="button" className="secondary" onClick={() => setSettingsOpen(true)}>
                <Settings2 size={18} aria-hidden="true" />
                {t("btn.modelSettings")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!canRunPipeline}
                onClick={handleRunFullPipeline}
                title={profileConfirmed ? t("btn.generate.titleReady") : t("btn.generate.title")}
              >
                <Sparkles size={18} aria-hidden="true" />
                {t("btn.generate")}
              </button>
            </div>
            <LanguageSwitcher />
          </div>
        </header>

        {error && <div className="notice error">{error}</div>}
        <PipelineStatus steps={pipelineSteps} />
        {busy && (
          <div className="notice loading">
            <Loader2 size={18} aria-hidden="true" />
            {busy}
          </div>
        )}

        {activeStep === "upload" && (
          <section className="panel">
            <PanelHeader icon={<FileUp size={22} />} title={t("panel.upload.title")} action={t("panel.upload.action")} />
            <label className="upload-zone">
              <FileUp size={34} aria-hidden="true" />
              <span>{t("upload.choose")}</span>
              <input type="file" accept=".pptx,.pdf" onChange={handleUpload} />
            </label>
            {project?.source_material && (
              <>
                <SourcePreview project={project} />
                <OcrRerunPanel project={project} ocrStatus={ocrStatus} onRerun={handleRerunOcr} busy={Boolean(busy)} />
              </>
            )}
          </section>
        )}

        {activeStep === "profile" && (
          <section className="panel">
            <PanelHeader icon={<Settings2 size={22} />} title={t("panel.profile.title")} action={t("panel.profile.action")} />
            <ProfileForm profile={profile} onChange={handleProfileChange} autoFilledFields={autoFilledFields} userEditedFields={userEditedFields} />
            <div className="action-row">
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy}
                onClick={() => handleSaveProfile("mode")}
              >
                <Save size={18} aria-hidden="true" />
                {t("btn.saveProfile")}
              </button>
            </div>
          </section>
        )}

        {activeStep === "mode" && (
          <section className="panel">
            <PanelHeader icon={<Sparkles size={22} />} title={t("panel.mode.title")} action={t("panel.mode.action")} />
            <fieldset className="field-group">
              <legend>{t("mode.legend")}</legend>
              <div className="segmented-grid">
                {modes.map((mode) => (
                  <button
                    key={mode.value}
                    type="button"
                    className={profile.generation_mode === mode.value ? "selected" : ""}
                    onClick={() => setProfile({ ...profile, generation_mode: mode.value })}
                  >
                    <strong>{t(mode.titleKey)}</strong>
                    <span>{t(mode.detailKey)}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <label className="field">
              <span>{t("mode.scaffoldLabel")}</span>
              <select
                value={profile.scaffolding_language}
                onChange={(event) => setProfile({ ...profile, scaffolding_language: event.target.value })}
              >
                {languages.map((language) => (
                  <option key={language} value={language}>
                    {language}
                  </option>
                ))}
              </select>
            </label>
            <div className="action-row">
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy}
                onClick={() =>
                  project &&
                  run(
                    t("busy.generatingOutline"),
                    async () => {
                      const saved = await saveProfile(project.project_id, profile);
                      setConfirmedProfileProjectId(saved.project_id);
                      return generateBlueprint(project.project_id);
                    },
                    "outline"
                  )
                }
              >
                <Play size={18} aria-hidden="true" />
                {t("btn.generateOutline")}
              </button>
            </div>
          </section>
        )}

        {activeStep === "outline" && (
          <section className="panel">
            <PanelHeader icon={<Pencil size={22} />} title={t("panel.outline.title")} action={t("panel.outline.action", { n: blueprint?.slides.length ?? 0 })} />
            {blueprint ? (
              <BlueprintEditor blueprint={blueprint} componentRegistry={componentRegistry} componentOptions={componentOptions} onChange={setBlueprint} />
            ) : (
              <EmptyState text={t("outline.empty")} />
            )}
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={!project || !blueprint || !!busy}
                onClick={() => project && blueprint && run(t("busy.savingOutline"), () => saveBlueprint(project.project_id, blueprint))}
              >
                <Save size={18} aria-hidden="true" />
                {t("btn.saveOutline")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !blueprint || !!busy}
                onClick={() =>
                  project &&
                  blueprint &&
                  run(
                    t("busy.generatingMedia"),
                    async () => {
                      await saveBlueprint(project.project_id, blueprint);
                      return generateMedia(project.project_id);
                    },
                    "preview"
                  )
                }
              >
                <Image size={18} aria-hidden="true" />
                {t("btn.generateMedia")}
              </button>
            </div>
          </section>
        )}

        {activeStep === "preview" && (
          <section className="panel preview-panel">
            <PanelHeader icon={<MonitorPlay size={22} />} title={t("panel.preview.title")} action={project?.preview_url ? t("panel.preview.actionRendered") : t("panel.preview.actionReady")} />
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy}
                onClick={() => project && run(t("busy.generatingMedia"), () => generateMedia(project.project_id))}
              >
                <Image size={18} aria-hidden="true" />
                {t("btn.regenerateMedia")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy}
                onClick={() => {
                  setPreviewError("");
                  setPreviewLoading(true);
                  project && run(t("busy.rendering"), () => renderProject(project.project_id));
                }}
              >
                <MonitorPlay size={18} aria-hidden="true" />
                {t("btn.rerender")}
              </button>
              <a
                className={project?.export_url && !qualityBlocked ? "download-link" : "download-link disabled"}
                href={project?.export_url && !qualityBlocked ? exportUrl(project.project_id) : undefined}
                aria-disabled={!project?.export_url || qualityBlocked}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                {qualityBlocked ? t("export.blocked") : project?.export_url ? t("btn.downloadZip") : t("export.waiting")}
              </a>
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy || !qualityBlocked}
                onClick={handleForceExport}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                {t("btn.forceExport")}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy || qualityBlocked}
                onClick={() => handleEditablePptxExport(false)}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                {t("btn.exportPptx")}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy || !qualityBlocked}
                onClick={() => handleEditablePptxExport(true)}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                {t("btn.forceExportPptx")}
              </button>
            </div>
            <p className="export-note">
              {t("export.note")}
            </p>
            <QualityReportView project={project} />
            <SpecLockSummary specLock={artifactTree?.spec_lock ?? null} />
            <AgentHandoffPanel
              project={project}
              agentPackage={agentPackage}
              validation={agentValidation}
              copied={agentCopied}
              busy={Boolean(busy)}
              onGenerate={handleGenerateAgentPackage}
              onCopy={handleCopyAgentTask}
              onValidate={handleValidateAgentOutput}
            />
            <ArtifactInspector tree={artifactTree} />
            {project?.export_url && !qualityBlocked && (
              <div className="export-ready">
                <CheckCircle2 size={18} aria-hidden="true" />
                <span>{t("export.ready")}</span>
                <a href={exportUrl(project.project_id)}>HanClassStudio_Output_*.zip</a>
              </div>
            )}
            {pptxExport && (
              <div className="export-ready">
                <CheckCircle2 size={18} aria-hidden="true" />
                <span>{t("export.pptxReady")}</span>
                <a href={previewUrl(pptxExport.download_url) ?? undefined}>{pptxExport.filename}</a>
              </div>
            )}
            {previewUrl(project?.preview_url) ? (
              <div className="preview-frame-wrap">
                {previewLoading && (
                  <div className="preview-state">
                    <Loader2 size={18} aria-hidden="true" />
                    {t("preview.loading")}
                  </div>
                )}
                {previewError && <div className="preview-state error">{previewError}</div>}
                <iframe
                  key={previewKey}
                  className="courseware-preview"
                  src={`${previewUrl(project?.preview_url)}?v=${previewKey}`}
                  title="HanClassStudio courseware preview"
                  onLoad={() => {
                    setPreviewLoading(false);
                    setPreviewError("");
                  }}
                  onError={() => {
                    setPreviewLoading(false);
                    setPreviewError(t("preview.error"));
                  }}
                />
              </div>
            ) : (
              <EmptyState text={t("preview.empty")} />
            )}
          </section>
        )}
      </main>
      {settingsOpen && (
        <ModelSettingsModal
          config={providerConfig}
          synced={settingsSynced}
          onChange={(next) => {
            setProviderConfig(next);
            writeStoredProviderConfig(next);
          }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
      {onboardingOpen && (
        <OnboardingWizard
          config={providerConfig}
          onChange={(next) => {
            setProviderConfig(next);
            writeStoredProviderConfig(next);
          }}
          onClose={() => {
            writeOnboardingSeen();
            setOnboardingOpen(false);
          }}
        />
      )}
    </div>
  );
}

const LANG_FLAGS: Record<UiLang, string> = {
  zh: "🇨🇳",
  en: "🇺🇸",
  ja: "🇯🇵",
  ko: "🇰🇷",
  ar: "🇸🇦",
  ru: "🇷🇺",
};

function LanguageSwitcher() {
  const { lang, setLang, t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = UI_LANGUAGES.find((item) => item.code === lang) ?? UI_LANGUAGES[0];

  return (
    <div className="lang-dropdown" ref={ref}>
      <button
        type="button"
        className="lang-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("lang.aria")}
        title={t("lang.label")}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="lang-flag" aria-hidden="true">{LANG_FLAGS[current.code]}</span>
        <span className="lang-current">{current.native}</span>
        <ChevronDown size={16} className={`lang-chevron${open ? " is-open" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <ul className="lang-menu" role="listbox" aria-label={t("lang.label")}>
          {UI_LANGUAGES.map((item) => (
            <li key={item.code} role="option" aria-selected={item.code === lang}>
              <button
                type="button"
                className={`lang-option${item.code === lang ? " active" : ""}`}
                onClick={() => {
                  setLang(item.code);
                  setOpen(false);
                }}
              >
                <span className="lang-flag" aria-hidden="true">{LANG_FLAGS[item.code]}</span>
                <span className="lang-option-text">
                  <span className="lang-option-native">{item.native}</span>
                  <span className="lang-option-english">{item.label}</span>
                </span>
                {item.code === lang && <Check size={16} className="lang-check" aria-hidden="true" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProviderStatusPanel({
  config,
  onOpenSettings,
}: {
  config: ProviderConfig;
  onOpenSettings: () => void;
}) {
  const { t } = useI18n();
  const total = CAPABILITY_ORDER.length;
  const configured = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c])).length;

  return (
    <section className="provider-status" aria-label={t("provider.title")}>
      <button
        type="button"
        className="provider-summary-card"
        onClick={onOpenSettings}
        aria-label={t("provider.open")}
      >
        <div className="provider-summary-icon">
          <Boxes size={22} aria-hidden="true" />
        </div>
        <div className="provider-summary-text">
          <strong>{t("provider.title")}</strong>
          <span>{t("provider.summary", { configured, total })}</span>
        </div>
        <Settings2 size={18} aria-hidden="true" />
      </button>
    </section>
  );
}

function PipelineStatus({ steps }: { steps: Record<string, PipelineStepStatus> }) {
  const { t } = useI18n();
  const hasActivity = pipelineStepKeys.some((label) => steps[label] !== "pending");
  if (!hasActivity) return null;
  return (
    <section className="pipeline-status" aria-label={t("btn.generate")}>
      {pipelineStepKeys.map((label) => (
        <div className={`pipeline-step ${steps[label]}`} key={label}>
          <span aria-hidden="true">{steps[label] === "done" ? <CheckCircle2 size={15} /> : steps[label] === "running" ? <Loader2 size={15} /> : steps[label] === "error" ? <X size={15} /> : null}</span>
          <strong>{t(label)}</strong>
        </div>
      ))}
    </section>
  );
}

function getProvidersForCapabilityByMode(
  capability: ProviderCapability,
  mode: "local" | "cloud"
): ProviderDefinition[] {
  return PROVIDER_CATALOG.filter((p) => p.capabilities.includes(capability) && p.category === mode);
}

function CapabilityConfigPanel({
  capability,
  config,
  onChange,
}: {
  capability: ProviderCapability;
  config: ProviderConfig;
  onChange: (next: ProviderConfig) => void;
}) {
  const { t } = useI18n();
  const cfg = config[capability];
  const selectedProvider = cfg ? getProviderById(cfg.providerId) : undefined;
  const [mode, setMode] = useState<"local" | "cloud">(selectedProvider?.category ?? "local");
  const providers = getProvidersForCapabilityByMode(capability, mode);
  const selectedId = selectedProvider && selectedProvider.category === mode ? selectedProvider.id : "";

  function applyProvider(id: string) {
    const def = getProviderById(id);
    if (!def) return;
    const defaults: Record<string, string> = {};
    def.fields.forEach((f) => {
      defaults[f.key] = f.type === "select" && f.options?.length ? f.options[0].value : "";
    });
    onChange({ ...config, [capability]: { providerId: id, values: defaults } });
  }

  function switchMode(next: "local" | "cloud") {
    setMode(next);
    const list = getProvidersForCapabilityByMode(capability, next);
    if (list.length) {
      applyProvider(list[0].id);
    } else {
      onChange({ ...config, [capability]: undefined });
    }
  }

  function setValue(key: string, value: string) {
    if (!cfg) return;
    onChange({
      ...config,
      [capability]: { ...cfg, values: { ...cfg.values, [key]: value } }
    });
  }

  return (
    <div className="capability-config-panel">
      <div className="deploy-mode">
        <span className="deploy-mode-label">{t("provider.deployMode")}</span>
        <div className="segmented-toggle" role="group" aria-label={t("provider.deployMode")}>
          <button
            type="button"
            className={mode === "local" ? "active" : ""}
            onClick={() => switchMode("local")}
          >
            {t("provider.mode.local")}
          </button>
          <button
            type="button"
            className={mode === "cloud" ? "active" : ""}
            onClick={() => switchMode("cloud")}
          >
            {t("provider.mode.cloud")}
          </button>
        </div>
      </div>

      {providers.length === 0 ? (
        <p className="muted-text">{t("provider.noProviders")}</p>
      ) : (
        <label className="field">
          <span>{t("provider.selectProvider")}</span>
          <select value={selectedId} onChange={(e) => applyProvider(e.target.value)}>
            <option value="">{t("provider.chooseProvider")}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {t(p.descriptionKey)}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedProvider && selectedProvider.category === mode && (
        <div className="provider-fields">
          {selectedProvider.fields.map((field) => (
            <label className="field" key={field.key}>
              <span>
                {t(field.labelKey)}
                {field.required && <span className="required-mark">*</span>}
              </span>
              {field.type === "select" ? (
                <select
                  value={cfg?.values[field.key] ?? ""}
                  onChange={(e) => setValue(field.key, e.target.value)}
                >
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === "password" ? "password" : field.type === "url" ? "url" : "text"}
                  value={cfg?.values[field.key] ?? ""}
                  placeholder={field.placeholderKey ? t(field.placeholderKey) : ""}
                  onChange={(e) => setValue(field.key, e.target.value)}
                />
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelSettingsModal({
  config,
  onChange,
  onClose,
  synced,
}: {
  config: ProviderConfig;
  onChange: (next: ProviderConfig) => void;
  onClose: () => void;
  synced?: boolean;
}) {
  const { t } = useI18n();
  const [activeCapability, setActiveCapability] = useState<ProviderCapability>("ocr");

  const configuredCount = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c])).length;

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal provider-settings-modal" role="dialog" aria-modal="true" aria-labelledby="modelSettingsTitle">
        <header>
          <div>
            <p className="eyebrow">{t("settings.eyebrow")}</p>
            <h2 id="modelSettingsTitle">{t("settings.title")}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t("settings.close")}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <div className="settings-progress">
          <span>{t("provider.configuredCount", { n: configuredCount, total: CAPABILITY_ORDER.length })}</span>
          <div className="settings-progress-bar">
            <div
              className="settings-progress-fill"
              style={{ width: `${(configuredCount / CAPABILITY_ORDER.length) * 100}%` }}
            />
          </div>
        </div>

        <div className="provider-settings-layout">
          <nav className="capability-tabs">
            {CAPABILITY_ORDER.map((capability) => {
              const meta = CAPABILITY_META[capability];
              const ok = isCapabilityConfigured(config[capability]);
              const Icon = meta.icon;
              return (
                <button
                  type="button"
                  key={capability}
                  className={`capability-tab ${activeCapability === capability ? "active" : ""} ${ok ? "ok" : ""}`}
                  onClick={() => setActiveCapability(capability)}
                >
                  <Icon size={16} aria-hidden="true" />
                  <span>{t(meta.labelKey)}</span>
                  {ok && <Check size={14} aria-hidden="true" />}
                </button>
              );
            })}
          </nav>

          <div className="capability-tab-content">
            <CapabilityConfigPanel capability={activeCapability} config={config} onChange={onChange} />
          </div>
        </div>

        <p className={`settings-saved-note ${synced ? "ok" : ""}`}>
          {synced ? t("settings.savedToServer") : t("settings.note")}
        </p>

        <div className="action-row">
          <button type="button" className="secondary" onClick={onClose}>
            {t("settings.cancel")}
          </button>
          <button type="button" className="primary" onClick={onClose}>
            {t("settings.save")}
          </button>
        </div>
      </section>
    </div>
  );
}

function OnboardingWizard({
  config,
  onChange,
  onClose,
}: {
  config: ProviderConfig;
  onChange: (next: ProviderConfig) => void;
  onClose: () => void;
}) {
  const { t, lang, setLang } = useI18n();
  const [step, setStep] = useState(0);
  const [activeCapability, setActiveCapability] = useState<ProviderCapability>("ocr");

  const configuredCount = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c])).length;

  const steps = [
    { id: "welcome", titleKey: "onboarding.welcome.title", icon: Sparkles },
    { id: "providers", titleKey: "onboarding.providers.title", icon: Boxes },
    { id: "done", titleKey: "onboarding.done.title", icon: CheckCircle2 }
  ];

  function nextStep() {
    if (step < steps.length - 1) setStep(step + 1);
  }

  function prevStep() {
    if (step > 0) setStep(step - 1);
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="onboardingTitle">
        <header>
          <div>
            <p className="eyebrow">{t("onboarding.eyebrow")}</p>
            <h2 id="onboardingTitle">{t(steps[step].titleKey)}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t("settings.close")}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <div className="onboarding-steps">
          {steps.map((s, idx) => {
            const Icon = s.icon;
            const state = idx === step ? "active" : idx < step ? "done" : "";
            return (
              <div key={s.id} className={`onboarding-step ${state}`}>
                <span className="onboarding-step-marker">
                  <span className="onboarding-step-icon">
                    {idx < step ? <Check size={14} /> : <Icon size={16} />}
                  </span>
                  {idx < steps.length - 1 && <span className="onboarding-step-line" />}
                </span>
                <span className="onboarding-step-label">{t(s.titleKey)}</span>
              </div>
            );
          })}
        </div>

        <div className="onboarding-step-pane" key={step}>
          {step === 0 && (
            <div className="onboarding-body onboarding-welcome">
              <div className="onboarding-hero">
                <Boxes size={48} aria-hidden="true" />
                <h3>{t("onboarding.welcome.heading")}</h3>
                <p>{t("onboarding.welcome.body")}</p>
              </div>
              <div className="onboarding-lang">
                <span className="onboarding-lang-label">{t("onboarding.chooseLanguage")}</span>
                <div className="lang-grid">
                  {UI_LANGUAGES.map((item) => (
                    <button
                      type="button"
                      key={item.code}
                      className={`lang-chip ${lang === item.code ? "active" : ""}`}
                      onClick={() => setLang(item.code)}
                      aria-pressed={lang === item.code}
                    >
                      <span className="lang-chip-flag" aria-hidden="true">{LANG_FLAGS[item.code]}</span>
                      <span className="lang-chip-native">{item.native}</span>
                      {lang === item.code && <Check size={16} className="lang-chip-check" aria-hidden="true" />}
                    </button>
                  ))}
                </div>
              </div>
              <div className="onboarding-welcome-actions">
                <button type="button" className="secondary" onClick={onClose}>
                  {t("onboarding.skip")}
                </button>
                <button type="button" className="primary" onClick={nextStep}>
                  {t("onboarding.selectProvider")}
                </button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="onboarding-body">
              <div className="onboarding-progress">
                <span>{t("provider.configuredCount", { n: configuredCount, total: CAPABILITY_ORDER.length })}</span>
              </div>
              <div className="provider-settings-layout">
                <nav className="capability-tabs">
                  {CAPABILITY_ORDER.map((capability) => {
                    const meta = CAPABILITY_META[capability];
                    const ok = isCapabilityConfigured(config[capability]);
                    const Icon = meta.icon;
                    return (
                      <button
                        type="button"
                        key={capability}
                        className={`capability-tab ${activeCapability === capability ? "active" : ""} ${ok ? "ok" : ""}`}
                        onClick={() => setActiveCapability(capability)}
                      >
                        <Icon size={16} aria-hidden="true" />
                        <span>{t(meta.labelKey)}</span>
                        {ok && <Check size={14} aria-hidden="true" />}
                      </button>
                    );
                  })}
                </nav>
                <div className="capability-tab-content">
                  <CapabilityConfigPanel capability={activeCapability} config={config} onChange={onChange} />
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="onboarding-body">
              <div className="onboarding-hero">
                <CheckCircle2 size={48} aria-hidden="true" />
                <h3>{t("onboarding.done.heading")}</h3>
                <p>{t("onboarding.done.body", { n: configuredCount })}</p>
              </div>
              <div className="onboarding-summary">
                {CAPABILITY_ORDER.map((capability) => {
                  const meta = CAPABILITY_META[capability];
                  const cfg = config[capability];
                  const ok = isCapabilityConfigured(cfg);
                  const def = cfg ? getProviderById(cfg.providerId) : undefined;
                  const Icon = meta.icon;
                  return (
                    <div className="onboarding-summary-row" key={capability}>
                      <Icon size={16} aria-hidden="true" />
                      <span>{t(meta.labelKey)}</span>
                      <span className={`onboarding-summary-status ${ok ? "ok" : ""}`}>
                        {def ? def.name : t("provider.notConfigured")}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {step > 0 && (
          <div className="action-row">
            {step < steps.length - 1 && (
              <button type="button" className="secondary" onClick={prevStep}>
                {t("onboarding.back")}
              </button>
            )}
            {step < steps.length - 1 ? (
              <button type="button" className="primary" onClick={nextStep}>
                {t("onboarding.next")}
              </button>
            ) : (
              <button type="button" className="primary" onClick={onClose}>
                {t("onboarding.finish")}
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function PanelHeader({ icon, title, action }: { icon: ReactNode; title: string; action: string }) {
  return (
    <div className="panel-header">
      <div>
        <span className="panel-icon">{icon}</span>
        <h2>{title}</h2>
      </div>
      <span>{action}</span>
    </div>
  );
}

function ProfileForm({
  profile,
  onChange,
  autoFilledFields = new Set(),
  userEditedFields = new Set(),
}: {
  profile: LessonProfile;
  onChange: (profile: LessonProfile) => void;
  autoFilledFields?: Set<string>;
  userEditedFields?: Set<string>;
}) {
  const { t } = useI18n();
  function set<K extends keyof LessonProfile>(key: K, value: LessonProfile[K]) {
    onChange({ ...profile, [key]: value });
  }

  // Determine the badge for each field
  function fieldBadge(fieldKey: string): "ai" | "edited" | null {
    if (userEditedFields.has(fieldKey)) return "edited";
    if (autoFilledFields.has(fieldKey)) return "ai";
    return null;
  }

  const fields: Array<{ key: keyof LessonProfile; labelKey: string }> = [
    { key: "lesson_title", labelKey: "profile.title.label" },
    { key: "learner_level", labelKey: "profile.level" },
    { key: "target_students", labelKey: "profile.audience" },
    { key: "lesson_type", labelKey: "profile.type" },
    { key: "estimated_duration", labelKey: "profile.duration" },
    { key: "subject", labelKey: "profile.subject" },
  ];

  const filledCount = autoFilledFields.size;
  const editedCount = userEditedFields.size;

  return (
    <div>
      {filledCount > 0 && (
        <div className="auto-fill-notice">
          <Sparkles size={14} aria-hidden="true" />
          {t("profile.autoFillNotice", { n: filledCount })}
          {editedCount > 0 && <span className="auto-fill-edited"> · {t("profile.editedCount", { n: editedCount })}</span>}
        </div>
      )}
      <div className="form-grid">
        {fields.map(({ key, labelKey }) => {
          const badge = fieldBadge(key);
          return (
            <label key={String(key)} className={`field ${badge ? `field--${badge}` : ""}`}>
              <span>{t(labelKey)}</span>
              <div className="field-input-wrap">
                <input value={profile[key]} onChange={(event) => set(key, (event.target as HTMLInputElement).value as never)} />
                {badge === "ai" && <span className="field-badge field-badge--ai" title={t("profile.badge.ai")}>{t("profile.badge.aiLabel")}</span>}
                {badge === "edited" && <span className="field-badge field-badge--edited" title={t("profile.badge.edited")}>{t("profile.badge.editedLabel")}</span>}
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function ocrMethodLabel(method: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  return t(`ocr.method.${method}`) || method;
}

function ocrConfClass(conf: number): string {
  return conf >= 90 ? "high" : conf >= 70 ? "mid" : "low";
}

function OcrSummary({ analysis }: { analysis: SourceAnalysis }) {
  const { t } = useI18n();
  const conf = Math.round(analysis.overall_confidence * 100);
  const engines = Object.entries(analysis.source_method_summary)
    .map(([method, count]) => `${ocrMethodLabel(method, t)} ×${count}`)
    .join("，");
  return (
    <section className="ocr-summary" aria-label={t("ocr.summaryTitle")}>
      <div className="ocr-summary-head">
        <strong>{t("ocr.summaryTitle")}</strong>
        <span className={`ocr-conf ocr-conf--${ocrConfClass(conf)}`}>{conf}%</span>
      </div>
      <div className="ocr-summary-meta">
        <span>
          <b>{t("ocr.engineUsed")}:</b> {engines || "—"}
        </span>
        {analysis.needs_review_count > 0 && (
          <span className="ocr-flag">{t("ocr.needsReview")}: {analysis.needs_review_count}</span>
        )}
      </div>
      {analysis.notes.length > 0 && (
        <ul className="ocr-notes">
          {analysis.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function OcrPageBadge({ page }: { page: SourceAnalysisPage }) {
  const { t } = useI18n();
  const conf = page.blocks.length
    ? Math.round((page.blocks.reduce((sum, b) => sum + b.confidence, 0) / page.blocks.length) * 100)
    : null;
  const needsReview = page.blocks.some((b) => b.needs_review);
  return (
    <div className="ocr-page-badge">
      <span className="ocr-method">{ocrMethodLabel(page.source_method, t)}</span>
      {conf !== null && <span className={`ocr-conf ocr-conf--${ocrConfClass(conf)}`}>{conf}%</span>}
      {needsReview && <span className="ocr-flag">{t("ocr.needsReview")}</span>}
    </div>
  );
}

function SourcePreview({ project }: { project: ProjectState }) {
  const source = project.source_material;
  if (!source) return null;
  const analysis = source.source_analysis;
  return (
    <div className="source-list">
      {analysis && <OcrSummary analysis={analysis} />}
      {source.pages.map((page) => {
        const pa = analysis?.pages.find((p) => p.page_number === page.page_number);
        return (
          <article className="source-item" key={page.page_number}>
            <span>{page.page_number}</span>
            <div>
              <h3>{page.title}</h3>
              <p>{page.text_blocks.map((block) => block.text).join(" · ").slice(0, 180)}</p>
              {pa && <OcrPageBadge page={pa} />}
            </div>
            <small>{page.images.length} images</small>
          </article>
        );
      })}
    </div>
  );
}

function OcrRerunPanel({
  ocrStatus,
  onRerun,
  busy,
}: {
  project: ProjectState;
  ocrStatus: OcrStatusResponse | null;
  onRerun: (engine?: string) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [engine, setEngine] = useState("auto");
  const paddle = ocrStatus?.engines.find((e) => e.name === "paddle_ocr");
  const tess = ocrStatus?.engines.find((e) => e.name === "tesseract");
  const canPaddle = Boolean(paddle?.available);
  const canTess = Boolean(tess?.available);
  const canOcr = canPaddle || canTess;
  return (
    <section className="ocr-rerun">
      <div className="ocr-rerun-head">
        <strong>
          <RefreshCw size={15} aria-hidden="true" /> {t("ocr.rerun")}
        </strong>
        <span>{t("ocr.rerunHint")}</span>
      </div>
      <div className="ocr-rerun-controls">
        <select
          value={engine}
          disabled={busy || !canOcr}
          onChange={(event) => setEngine(event.target.value)}
          aria-label={t("ocr.engineLabel")}
        >
          <option value="auto">{t("ocr.engine.auto")}</option>
          {canPaddle && <option value="paddle_ocr">{t("ocr.engine.paddle_ocr")}</option>}
          {canTess && <option value="tesseract">{t("ocr.engine.tesseract")}</option>}
        </select>
        <button
          type="button"
          className="secondary"
          disabled={busy || !canOcr}
          onClick={() => onRerun(engine)}
        >
          <RefreshCw size={16} aria-hidden="true" /> {t("ocr.rerun")}
        </button>
      </div>
      {!canOcr && <p className="ocr-rerun-note">{t("ocr.noEngine")}</p>}
    </section>
  );
}

function BlueprintEditor({
  blueprint,
  componentRegistry,
  componentOptions,
  onChange
}: {
  blueprint: LessonBlueprint;
  componentRegistry: ComponentRegistry;
  componentOptions: string[];
  onChange: (blueprint: LessonBlueprint) => void;
}) {
  const { t } = useI18n();
  const [expandedSlides, setExpandedSlides] = useState<Set<number>>(() => new Set([blueprint.slides[0]?.id ?? 1]));

  function normalizedSlide(slide: LessonSlide): LessonSlide {
    return {
      ...slide,
      content_blocks: slide.content_blocks ?? [],
      components: slide.components ?? [],
      media_requirements: slide.media_requirements ?? {}
    };
  }

  function updateSlide(index: number, patch: Partial<LessonSlide>) {
    const slides = blueprint.slides.map((slide, slideIndex) => (slideIndex === index ? { ...normalizedSlide(slide), ...patch } : slide));
    onChange({ ...blueprint, slides });
  }

  function updateContentBlock(slideIndex: number, blockIndex: number, patch: Partial<ContentBlock>) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    const blocks = slide.content_blocks.length
      ? slide.content_blocks
      : [{ id: `slide_${slide.id}_block_1`, block_type: "text", text: "", scaffolding_text: "" }];
    updateSlide(slideIndex, {
      content_blocks: blocks.map((block, index) => (index === blockIndex ? { ...block, ...patch } : block))
    });
  }

  function addContentBlock(slideIndex: number) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      content_blocks: [
        ...slide.content_blocks,
        {
          id: `slide_${slide.id}_block_${slide.content_blocks.length + 1}`,
          block_type: "text",
          text: "",
          scaffolding_text: ""
        }
      ]
    });
  }

  function removeContentBlock(slideIndex: number, blockIndex: number) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      content_blocks: slide.content_blocks.filter((_, index) => index !== blockIndex)
    });
  }

  function updateMedia(slideIndex: number, key: keyof LessonSlide["media_requirements"], value: string) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      media_requirements: {
        ...slide.media_requirements,
        [key]: value
      }
    });
  }

  function updateComponent(slideIndex: number, componentIndex: number, patch: Partial<SlideComponent>) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      components: slide.components.map((component, index) => (index === componentIndex ? { ...component, ...patch } : component))
    });
  }

  function addComponent(slideIndex: number, componentType: string) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      components: [
        ...slide.components,
        {
          id: `${componentType.toLowerCase()}_${slide.id}_${slide.components.length + 1}`,
          component_type: componentType,
          title: componentType,
          data: defaultComponentData(componentType, componentRegistry[componentType])
        }
      ]
    });
  }

  function removeComponent(slideIndex: number, componentIndex: number) {
    const slide = normalizedSlide(blueprint.slides[slideIndex]);
    updateSlide(slideIndex, {
      components: slide.components.filter((_, index) => index !== componentIndex)
    });
  }

  function toggleSlide(slideId: number) {
    setExpandedSlides((current) => {
      const next = new Set(current);
      if (next.has(slideId)) next.delete(slideId);
      else next.add(slideId);
      return next;
    });
  }

  return (
    <div className="outline-list">
      {blueprint.slides.map((rawSlide, index) => {
        const slide = normalizedSlide(rawSlide);
        const isExpanded = expandedSlides.has(slide.id);
        const blocks = slide.content_blocks.length
          ? slide.content_blocks
          : [{ id: `slide_${slide.id}_block_1`, block_type: "text", text: "", scaffolding_text: "" }];
        return (
          <article className="outline-item" key={slide.id}>
            <button type="button" className="slide-summary" onClick={() => toggleSlide(slide.id)} aria-expanded={isExpanded}>
              <span className="slide-number">{slide.id}</span>
              <span>
                <strong>{slide.title || t("editor.pageFallback", { id: slide.id })}</strong>
                <small>{slide.slide_type || "页面"} · {slide.layout_variant || "布局"}</small>
              </span>
              {isExpanded ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
            </button>
            {isExpanded && (
              <div className="outline-fields">
                <label className="field">
                  <span>{t("editor.pageTitle")}</span>
                  <input value={slide.title} onChange={(event) => updateSlide(index, { title: event.target.value })} />
                </label>
                <div className="compact-grid">
                  <label className="field">
                    <span>{t("editor.pageType")}</span>
                    <input value={slide.slide_type} onChange={(event) => updateSlide(index, { slide_type: event.target.value })} />
                  </label>
                  <label className="field">
                    <span>{t("editor.layout")}</span>
                    <input value={slide.layout_variant} onChange={(event) => updateSlide(index, { layout_variant: event.target.value })} />
                  </label>
                </div>

                <section className="editor-section">
                  <div className="editor-section-header">
                    <h3>{t("editor.contentBlocks")}</h3>
                    <button type="button" className="secondary small-button" onClick={() => addContentBlock(index)}>
                      <Plus size={16} aria-hidden="true" />
                      {t("editor.addContent")}
                    </button>
                  </div>
                  {blocks.map((block, blockIndex) => (
                    <div className="content-block-editor" key={block.id || blockIndex}>
                      <div className="compact-grid">
                        <label className="field">
                          <span>{t("editor.blockType")}</span>
                          <input value={block.block_type} onChange={(event) => updateContentBlock(index, blockIndex, { block_type: event.target.value })} />
                        </label>
                        <button type="button" className="icon-text danger" onClick={() => removeContentBlock(index, blockIndex)}>
                          <Trash2 size={16} aria-hidden="true" />
                          {t("editor.deleteContent")}
                        </button>
                      </div>
                      <label className="field">
                        <span>{t("editor.chineseContent")}</span>
                        <textarea value={block.text} onChange={(event) => updateContentBlock(index, blockIndex, { text: event.target.value })} />
                      </label>
                      <label className="field">
                        <span>{t("editor.scaffold")}</span>
                        <textarea
                          value={block.scaffolding_text}
                          onChange={(event) => updateContentBlock(index, blockIndex, { scaffolding_text: event.target.value })}
                        />
                      </label>
                    </div>
                  ))}
                </section>

                <section className="editor-section">
                  <h3>{t("editor.media")}</h3>
                  <label className="field">
                    <span>{t("editor.imagePrompt")}</span>
                    <textarea
                      value={slide.media_requirements.image_prompt ?? ""}
                      onChange={(event) => updateMedia(index, "image_prompt", event.target.value)}
                    />
                  </label>
                  <div className="compact-grid">
                    <label className="field">
                      <span>{t("editor.audioText")}</span>
                      <input value={slide.media_requirements.audio_text ?? ""} onChange={(event) => updateMedia(index, "audio_text", event.target.value)} />
                    </label>
                    <label className="field">
                      <span>{t("editor.videoPrompt")}</span>
                      <input
                        value={slide.media_requirements.video_scene_prompt ?? ""}
                        onChange={(event) => updateMedia(index, "video_scene_prompt", event.target.value)}
                      />
                    </label>
                  </div>
                </section>

                <section className="editor-section">
                  <div className="editor-section-header">
                    <h3>{t("editor.components")}</h3>
                    <select
                      aria-label={t("editor.addComponent")}
                      defaultValue=""
                      onChange={(event) => {
                        if (!event.target.value) return;
                        addComponent(index, event.target.value);
                        event.target.value = "";
                      }}
                    >
                      <option value="" disabled>
                        {componentOptions.length ? t("editor.addComponent") : t("editor.loadingComponents")}
                      </option>
                      {componentOptions.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </div>
                  {slide.components.length ? (
                    <div className="component-editor-list">
                      {slide.components.map((component, componentIndex) => (
                        <div className="component-editor" key={component.id || componentIndex}>
                          <div className="compact-grid">
                            <label className="field">
                              <span>{t("editor.componentType")}</span>
                              <select
                                value={component.component_type}
                                onChange={(event) => updateComponent(index, componentIndex, { component_type: event.target.value })}
                              >
                                {componentOptions.map((type) => (
                                  <option key={type} value={type}>
                                    {type}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="field">
                              <span>{t("editor.componentTitle")}</span>
                              <input value={component.title} onChange={(event) => updateComponent(index, componentIndex, { title: event.target.value })} />
                            </label>
                          </div>
                          <button type="button" className="icon-text danger" onClick={() => removeComponent(index, componentIndex)}>
                            <Trash2 size={16} aria-hidden="true" />
                            {t("editor.deleteComponent")}
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted-text">{t("editor.noComponents")}</p>
                  )}
                </section>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function defaultComponentData(componentType: string, config?: ComponentConfig): Record<string, unknown> {
  if (!config?.requires?.length) return { component_type: componentType };
  return Object.fromEntries(config.requires.map((key) => [key, defaultComponentValue(key)]));
}

function defaultComponentValue(key: string): unknown {
  if (["items", "words", "answer", "choices", "pairs", "parts"].includes(key)) return [];
  return "";
}

function SpecLockSummary({ specLock }: { specLock: Record<string, unknown> | null }) {
  const { t } = useI18n();
  if (!specLock) return <EmptyState text={t("spec.empty")} />;
  const lesson = objectValue(specLock.lesson);
  const templates = objectValue(specLock.templates);
  const components = objectValue(specLock.components);
  const quality = objectValue(specLock.quality);
  const allowed = arrayValue(components.allowed).join(", ") || "—";
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>{t("spec.title")}</h3>
        <span>{stringValue(specLock.schema)}</span>
      </div>
      <div className="spec-grid">
        <SpecItem label={t("spec.route")} value={stringValue(specLock.route)} />
        <SpecItem label={t("spec.mode")} value={stringValue(specLock.generation_mode)} />
        <SpecItem label={t("spec.scaffold")} value={stringValue(lesson.scaffolding_language)} />
        <SpecItem label={t("spec.runtime")} value={stringValue(templates.runtime)} />
        <SpecItem label={t("spec.components")} value={allowed} />
        <SpecItem label={t("spec.quality")} value={qualityPolicySummary(quality)} />
      </div>
    </section>
  );
}

function SpecItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="spec-item">
      <span>{label}</span>
      <strong>{value || "—"}</strong>
    </div>
  );
}

function ArtifactInspector({ tree }: { tree: ArtifactTree | null }) {
  const { t } = useI18n();
  if (!tree) return <EmptyState text={t("artifact.empty")} />;
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>{t("artifact.title")}</h3>
        <span>{t("artifact.project", { id: tree.project_id })}</span>
      </div>
      <div className="artifact-grid">
        {tree.groups.map((group) => (
          <section className="artifact-group" key={group.name}>
            <h4>{group.name}</h4>
            <ul>
              {group.items.map((item) => (
                <li className={item.exists ? "exists" : "missing"} key={item.path}>
                  <span>{item.exists ? "✓" : "!"}</span>
                  <code>{item.path}</code>
                  <small>{artifactMeta(item)}</small>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </section>
  );
}

function AgentHandoffPanel({
  project,
  agentPackage,
  validation,
  copied,
  busy,
  onGenerate,
  onCopy,
  onValidate
}: {
  project: ProjectState | null;
  agentPackage: AgentPackage | null;
  validation: AgentValidation | null;
  copied: boolean;
  busy: boolean;
  onGenerate: () => void;
  onCopy: () => void;
  onValidate: () => void;
}) {
  const { t } = useI18n();
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>{t("agent.title")}</h3>
        <span>{agentPackage ? t("agent.subtitle") : t("agent.generate")}</span>
      </div>
      <div className="agent-actions">
        <button type="button" className="secondary" disabled={!project || busy} onClick={onGenerate}>
          <FileUp size={16} aria-hidden="true" />
          {t("agent.generate")}
        </button>
        <button type="button" className="secondary" disabled={!agentPackage || busy} onClick={onCopy}>
          <Clipboard size={16} aria-hidden="true" />
          {copied ? t("agent.copied") : t("agent.copy")}
        </button>
        <button type="button" className="primary" disabled={!project || busy} onClick={onValidate}>
          <CheckCircle2 size={16} aria-hidden="true" />
          {t("agent.validate")}
        </button>
      </div>
      {agentPackage && (
        <div className="agent-copy">
          <div>
            <span>{t("agent.task")}</span>
            <code>{agentPackage.task_path}</code>
          </div>
          <textarea readOnly value={`${agentPackage.task_text}\n\n---\n\n${agentPackage.rules_text}`} />
        </div>
      )}
      {validation && (
        <div className={`agent-validation ${validation.state}`}>
          <strong>{t("agent.validation", { state: validation.state })}</strong>
          <ValidationList title={t("agent.blocking")} items={validation.blocking} empty={t("agent.blocking.empty")} />
          <ValidationList title={t("agent.warnings")} items={validation.warnings} empty={t("agent.warnings.empty")} />
          <ValidationList title={t("agent.passed")} items={validation.passed} empty={t("agent.passed.empty")} />
        </div>
      )}
    </section>
  );
}

function ValidationList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <section>
      <h4>{title}</h4>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </section>
  );
}

function QualityReportView({ project }: { project: ProjectState | null }) {
  const { t } = useI18n();
  const report = project?.quality_report;
  if (!report) return <EmptyState text={t("quality.emptyState")} />;
  const blocking = safeList(report.blocking).length
    ? safeList(report.blocking)
    : [...safeList(report.resource_errors), ...safeList(report.invalid_interactions)];
  const warnings = safeList(report.warnings).length
    ? safeList(report.warnings)
    : [...safeList(report.missing_titles), ...safeList(report.missing_audio), ...safeList(report.missing_images), ...safeList(report.empty_prompts)];
  const passed = safeList(report.passed).length
    ? safeList(report.passed)
    : safeList(report.suggestions).length
      ? safeList(report.suggestions)
      : [t("quality.pending")];
  const groups = [
    [t("quality.blocking"), blocking, t("quality.blocking.detail")],
    [t("quality.warnings"), warnings, t("quality.warnings.detail")],
    [t("quality.passed"), passed, t("quality.passed.detail")]
  ] as const;
  return (
    <>
      <div className={`quality-state ${report.state}`}>
        <strong>{t("quality.title", { state: report.state })}</strong>
        <span>{report.schema}</span>
      </div>
      <div className="quality-grid">
        {groups.map(([title, items, detail]) => (
          <section className="quality-group" key={title}>
            <h3>{title}</h3>
            <p>{detail}</p>
            {items.length ? (
              <ul>
                {items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>{t("quality.empty")}</p>
            )}
          </section>
        ))}
      </div>
    </>
  );
}

function safeList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function qualityPolicySummary(policy: Record<string, unknown>): string {
  const parts = [];
  if (policy.block_on_missing_files) parts.push("block missing files");
  if (policy.block_on_missing_interaction_answers) parts.push("block missing answers");
  if (policy.warn_on_placeholder_media) parts.push("warn placeholders");
  if (policy.allow_forced_export) parts.push("force export allowed");
  return parts.join(", ");
}

function artifactMeta(item: ArtifactEntry): string {
  const size = typeof item.size === "number" ? `${item.size} B` : item.artifact_type;
  return item.updated_at ? `${size} · ${item.updated_at}` : size;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}
