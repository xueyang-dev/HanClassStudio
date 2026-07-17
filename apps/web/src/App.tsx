import { type ChangeEvent, type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Clipboard,
  Cpu,
  FileArchive,
  FileUp,
  GitBranch,
  Image,
  LayoutTemplate,
  Loader2,
  MessageSquare,
  Mic,
  Monitor,
  MonitorPlay,
  Moon,
  Pencil,
  Play,
  PackageCheck,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  UsersRound,
  Video,
  X
} from "lucide-react";
import {
  backendToConfig,
  configToBackend,
  exportEditablePptx,
  exportUrl,
  fetchProject,
  fetchDesignSummary,
  fetchHealth,
  fetchProviderCapabilities,
  fetchProviderInstallLogs,
  fetchProviderRegistry,
  fetchProviderSettings,
  refreshProviderRegistry,
  forceExportProject,
  generateAgentPackage,
  generateBlueprint,
  generateMedia,
  getComponentRegistry,
  getOcrStatus,
  listProjectArtifacts,
  listProjects,
  previewUrl,
  putProviderSettings,
  configureProviderInstall,
  confirmProviderInstall,
  prepareProviderInstall,
  retryProviderInstall,
  rollbackProviderInstall,
  replaceMedia,
  rerunOcr,
  renderProject,
  reviewMedia,
  runPipeline,
  saveBlueprint,
  saveProfile,
  uploadProject,
  validateAgentOutput
} from "./api";
import type { BackendProviderSettings } from "./api";
import { useI18n, UI_LANGUAGES, type UiLang } from "./i18n";
import type {
  AgentPackage,
  AgentValidation,
  ArtifactEntry,
  ArtifactTree,
  AssetFile,
  AssetManifest,
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
  ProviderInstallLog,
  ProviderInstallPrepareResponse,
  ProviderRegistryCatalog,
  ProviderRegistryRefreshResponse,
  ProviderRegistryStatus,
  ProjectState,
  ProjectSummary,
  SlideComponent,
  SourceAnalysis,
  SourceAnalysisPage,
  StateFirstTeacherSummary,
  StageStatus
} from "./types";
import { canUseStageAction, getAvailableCapabilityProviders, getCapabilityProviders, getCapabilityRegistryProviders, getConfigurableCapabilityProviders, getNextWorkflowAction, getStageAccess, PIPELINE_STEP_KEYS as pipelineStepKeys, isCurrentRequest, pipelineStepsFromProject, providerConfigSnapshot, providerStatus, sanitizeProviderConfig, shouldFetchDesignSummary, shouldPersistProviderConfig, type PipelineStepStatus, type StageAccess, type WorkflowStageId } from "./state";
import { ProjectLoadingSkeleton } from "./components/ProjectLoadingSkeleton";

const languages = ["English", "Arabic", "Russian", "Thai", "Korean", "Japanese", "Vietnamese", "Indonesian"];

const PROVIDER_STORAGE_KEY = "hcs_provider_config";
const ONBOARDING_STORAGE_KEY = "hcs_onboarding_seen";
const THEME_STORAGE_KEY = "hcs_theme_mode";

const CAPABILITY_ORDER: ProviderCapability[] = ["llm", "ocr", "image", "tts", "video"];

const CAPABILITY_META: Record<ProviderCapability, { labelKey: string; icon: typeof Cpu }> = {
  llm: { labelKey: "provider.llm.label", icon: Cpu },
  ocr: { labelKey: "provider.ocr.label", icon: MessageSquare },
  image: { labelKey: "provider.image.label", icon: Image },
  tts: { labelKey: "provider.tts.label", icon: Mic },
  video: { labelKey: "provider.video.label", icon: Video },
};

function getProviderById(id: string, capability: ProviderCapability, catalog: ProviderDefinition[]): ProviderDefinition | undefined {
  return catalog.find((p) => p.id === id && p.capability === capability);
}

function isCapabilityConfigured(config: CapabilityConfig | undefined, capability: ProviderCapability, catalog: ProviderDefinition[]): boolean {
  return providerStatus(config, capability, catalog).configured;
}

function isCapabilityAvailable(config: CapabilityConfig | undefined, capability: ProviderCapability, catalog: ProviderDefinition[]): boolean {
  return providerStatus(config, capability, catalog).available;
}

function readStoredProviderConfig(): ProviderConfig {
  try {
    const raw = localStorage.getItem(PROVIDER_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as ProviderConfig) : {};
    const sanitized = sanitizeProviderConfig(parsed);
    // Remove credentials left by older builds as soon as the app starts.
    localStorage.setItem(PROVIDER_STORAGE_KEY, JSON.stringify(sanitized));
    return sanitized;
  } catch {
    return {};
  }
}

function writeStoredProviderConfig(config: ProviderConfig) {
  try {
    localStorage.setItem(PROVIDER_STORAGE_KEY, JSON.stringify(sanitizeProviderConfig(config)));
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

function readStoredTheme(): ThemeMode {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

function writeStoredTheme(theme: ThemeMode) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // ignore storage failures
  }
}

const modes: Array<{ value: GenerationMode; titleKey: string; detailKey: string }> = [
  { value: "faithful", titleKey: "mode.faithful", detailKey: "mode.faithful.detail" },
  { value: "guided_redesign", titleKey: "mode.guided", detailKey: "mode.guided.detail" },
  { value: "reimagined", titleKey: "mode.reimagined", detailKey: "mode.reimagined.detail" }
];

const steps = [
  { id: "material", titleKey: "step.material", icon: FileUp },
  { id: "profile", titleKey: "step.learners", icon: UsersRound },
  { id: "design", titleKey: "step.design", icon: GitBranch },
  { id: "presentation", titleKey: "step.presentation", icon: LayoutTemplate },
  { id: "quality", titleKey: "step.quality", icon: ShieldCheck },
  { id: "delivery", titleKey: "step.delivery", icon: PackageCheck }
] as const;

type StepId = (typeof steps)[number]["id"];
type ThemeMode = "light" | "dark" | "system";

function asStepId(value: string | null | undefined): StepId | undefined {
  return steps.some((step) => step.id === value) ? value as StepId : undefined;
}

function resolveProjectStage(project: ProjectState, requestedStage?: string | null): StepId {
  const requested = asStepId(requestedStage);
  if (requested && getStageAccess(project, requested).viewable) return requested;
  const current = asStepId(project.current_stage);
  if (current && getStageAccess(project, current).viewable) return current;
  return "material";
}

function requestedProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("project_id");
}

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
  return message ? localizeBackendMessage(message, t) : t("error.fallback");
}

/** Keep modal keyboard/focus behavior identical for settings, onboarding, and
 * confirmation dialogs. The native dialog supplies inert background handling;
 * this hook adds focus restoration and a defensive Tab loop. */
function useNativeDialog(dialogRef: RefObject<HTMLDialogElement | null>, onClose: () => void) {
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!dialog.open) dialog.showModal();
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ));
    const focusFirst = () => {
      const first = focusable()[0];
      (first ?? dialog).focus();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const handleCancel = (event: Event) => {
      event.preventDefault();
      closeRef.current();
    };
    const previousBodyOverflow = document.body.style.overflow;
    dialog.addEventListener("keydown", handleKeyDown);
    dialog.addEventListener("cancel", handleCancel);
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(focusFirst);
    return () => {
      dialog.removeEventListener("keydown", handleKeyDown);
      dialog.removeEventListener("cancel", handleCancel);
      if (dialog.open) dialog.close();
      document.body.style.overflow = previousBodyOverflow;
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [dialogRef]);
}

export function App() {
  const { t } = useI18n();
  const routeProjectId = requestedProjectId();
  const [activeStep, setActiveStep] = useState<StepId>("material");
  const [project, setProject] = useState<ProjectState | null>(null);
  const [projectLoading, setProjectLoading] = useState(Boolean(routeProjectId));
  const [designSummary, setDesignSummary] = useState<StateFirstTeacherSummary | null>(null);
  const [profile, setProfile] = useState<LessonProfile>(emptyProfile);
  const [blueprint, setBlueprint] = useState<LessonBlueprint | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [previewKey, setPreviewKey] = useState(0);
  const [pipelineSteps, setPipelineSteps] = useState<Record<string, PipelineStepStatus>>(() => initialPipelineSteps());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [providerSaveError, setProviderSaveError] = useState("");
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
  const [providerCatalog, setProviderCatalog] = useState<ProviderDefinition[]>([]);
  const [providerRegistry, setProviderRegistry] = useState<ProviderRegistryCatalog | null>(null);
  const [recentProjects, setRecentProjects] = useState<ProjectSummary[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [healthStatus, setHealthStatus] = useState<"unknown" | "online" | "offline">("unknown");
  const [settingsSynced, setSettingsSynced] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(() => readStoredTheme());
  const [navNotice, setNavNotice] = useState("");
  const [exportFormat, setExportFormat] = useState<"html" | "pptx">("html");
  const [forceExportType, setForceExportType] = useState<"html" | "pptx" | null>(null);
  const providerSettingsRef = useRef<BackendProviderSettings | null>(null);
  const settingsLoadedRef = useRef(false);
  const providerConfigBaselineRef = useRef<string | null>(null);
  const settingsSaveSequenceRef = useRef(0);
  const settingsSaveControllerRef = useRef<AbortController | null>(null);
  const activeProjectIdRef = useRef<string | null>(null);
  const projectLoadSequenceRef = useRef(0);
  const artifactRequestSequenceRef = useRef(0);
  const providerRefreshSequenceRef = useRef(0);
  const codexBridgeSelected = providerConfig.llm?.providerId === "codex_chatgpt"
    || providerConfig.image?.providerId === "codex_image";

  const stageAccess = useMemo<Record<StepId, StageAccess>>(
    () => Object.fromEntries(steps.map((step) => [step.id, getStageAccess(project, step.id as WorkflowStageId)])) as Record<StepId, StageAccess>,
    [project],
  );

  const canUseAction = (stageId: StepId, action: string) => canUseStageAction(project, stageId as WorkflowStageId, action);

  const completedSteps = useMemo<Record<StepId, boolean>>(() => ({
    material: project?.stages?.find((stage) => stage.stage_id === "material")?.state === "completed",
    profile: project?.stages?.find((stage) => stage.stage_id === "profile")?.state === "completed",
    design: project?.stages?.find((stage) => stage.stage_id === "design")?.state === "completed",
    presentation: project?.stages?.find((stage) => stage.stage_id === "presentation")?.state === "completed",
    quality: ["completed", "warning"].includes(project?.stages?.find((stage) => stage.stage_id === "quality")?.state ?? ""),
    delivery: project?.stages?.find((stage) => stage.stage_id === "delivery")?.state === "completed" || Boolean(pptxExport)
  }), [project, pptxExport]);

  const componentOptions = useMemo(
    () => Object.keys(componentRegistry).filter((name) => !componentRegistry[name]?.experimental).sort(),
    [componentRegistry]
  );

  useEffect(() => {
    getComponentRegistry()
      .then(setComponentRegistry)
      .catch((err) => setError(readableError(err, t)));
    if (!readOnboardingSeen() && !routeProjectId) {
      setOnboardingOpen(true);
    }
  }, [routeProjectId, t]);

  useEffect(() => {
    let cancelled = false;
    setProjectsLoading(true);
    void listProjects()
      .then((items) => {
        if (!cancelled) setRecentProjects(items);
      })
      .catch(() => {
        if (!cancelled) setRecentProjects([]);
      })
      .finally(() => {
        if (!cancelled) setProjectsLoading(false);
      });
    const params = new URLSearchParams(window.location.search);
    const projectId = params.get("project_id");
    if (projectId) {
      setProjectLoading(true);
      const loadSequence = ++projectLoadSequenceRef.current;
      activeProjectIdRef.current = projectId;
      void fetchProject(projectId)
        .then((next) => {
          if (cancelled || loadSequence !== projectLoadSequenceRef.current) return;
          updateProject(next);
          setActiveStep(resolveProjectStage(next, params.get("stage")));
        })
        .catch((err) => {
          if (!cancelled) setError(readableError(err, t));
        })
        .finally(() => {
          if (!cancelled) setProjectLoading(false);
        });
    } else {
      setProjectLoading(false);
    }
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!project?.project_id) return;
    const url = new URL(window.location.href);
    url.searchParams.set("project_id", project.project_id);
    url.searchParams.set("stage", activeStep);
    window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
  }, [project?.project_id, activeStep]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const resolved = theme === "system" ? (media.matches ? "dark" : "light") : theme;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.style.colorScheme = resolved;
    };
    applyTheme();
    if (theme !== "system") return;
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [theme]);

  function handleThemeChange(next: ThemeMode) {
    setTheme(next);
    writeStoredTheme(next);
  }

  // Load persisted provider settings from the backend (source of truth) on mount.
  useEffect(() => {
    fetchProviderSettings()
      .then((backend) => {
        providerSettingsRef.current = backend;
        const fromBackend = backendToConfig(backend);
        const initialConfig = Object.keys(fromBackend).length > 0 ? fromBackend : providerConfig;
        providerConfigBaselineRef.current = providerConfigSnapshot(initialConfig);
        if (Object.keys(fromBackend).length > 0) setProviderConfig(fromBackend);
        writeStoredProviderConfig(initialConfig);
        setSettingsSynced(true);
        settingsLoadedRef.current = true;
      })
      .catch(() => {
        // Do not promote browser-only settings while the backend is unavailable.
        // Mark the load attempt complete so a later, explicit field edit can
        // retry the save through the normal debounced path without causing an
        // initialization PUT.
        providerConfigBaselineRef.current = providerConfigSnapshot(providerConfig);
        setSettingsSynced(false);
        settingsLoadedRef.current = true;
      });
  }, []);

  function reloadProviderContracts() {
    const sequence = ++providerRefreshSequenceRef.current;
    void Promise.allSettled([fetchProviderRegistry(), fetchProviderCapabilities()]).then(([registryResult, catalogResult]) => {
      if (sequence !== providerRefreshSequenceRef.current) return;
      setProviderRegistry(registryResult.status === "fulfilled" ? registryResult.value : null);
      setProviderCatalog(catalogResult.status === "fulfilled" ? catalogResult.value : []);
    });
  }

  async function discoverProviderSources(): Promise<ProviderRegistryRefreshResponse> {
    // Invalidate any local GET already in flight. The POST below is the only
    // action that may contact the official Registry feed.
    providerRefreshSequenceRef.current += 1;
    const result = await refreshProviderRegistry();
    const catalog = await fetchProviderCapabilities();
    providerRefreshSequenceRef.current += 1;
    setProviderRegistry(result.catalog);
    setProviderCatalog(catalog);
    return result;
  }

  useEffect(() => {
    reloadProviderContracts();
    return () => {
      providerRefreshSequenceRef.current += 1;
    };
  }, []);

  // Codex availability is tied to a short-lived agent heartbeat. Refresh the
  // backend-owned capability facts while either bridge Provider is selected so
  // connect/disconnect state changes without a manual browser reload.
  useEffect(() => {
    if (!codexBridgeSelected) return;
    reloadProviderContracts();
    const timer = window.setInterval(reloadProviderContracts, 15_000);
    return () => window.clearInterval(timer);
  }, [codexBridgeSelected]);

  useEffect(() => {
    if (!project?.project_id) {
      setDesignSummary(null);
      return;
    }
    // A ready/not-started design stage has no State-first artifacts yet. Do not
    // probe the summary endpoint in that state: the backend correctly returns
    // 404 for an unavailable summary, but a request for an expected empty state
    // would still surface as a browser console error.
    if (!shouldFetchDesignSummary(project)) {
      setDesignSummary(null);
      return;
    }
    fetchDesignSummary(project.project_id)
      .then(setDesignSummary)
      .catch(() => setDesignSummary(null));
  }, [project?.project_id, project?.project_revision, project?.stages]);

  // Persist provider settings to the backend whenever they change (best-effort,
  // debounced, and skipped until the initial load has resolved).
  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    const snapshot = providerConfigSnapshot(providerConfig);
    if (!shouldPersistProviderConfig(providerConfig, providerConfigBaselineRef.current, settingsLoadedRef.current)) return;
    const sequence = ++settingsSaveSequenceRef.current;
    settingsSaveControllerRef.current?.abort();
    const controller = new AbortController();
    settingsSaveControllerRef.current = controller;
    setSettingsSynced(false);
    const handle = setTimeout(() => {
      putProviderSettings(configToBackend(providerConfig, providerSettingsRef.current), { signal: controller.signal })
        .then((next) => {
          if (!isCurrentRequest(sequence, settingsSaveSequenceRef.current, controller.signal.aborted)) return;
          providerSettingsRef.current = next;
          providerConfigBaselineRef.current = snapshot;
          setProviderSaveError("");
          setSettingsSynced(true);
          return fetchProviderCapabilities().then((catalog) => {
            if (isCurrentRequest(sequence, settingsSaveSequenceRef.current, controller.signal.aborted)) setProviderCatalog(catalog);
          }).catch(() => undefined);
        })
        .catch((error: unknown) => {
          if (!isCurrentRequest(sequence, settingsSaveSequenceRef.current, controller.signal.aborted)) return;
          setSettingsSynced(false);
          setProviderSaveError(readableError(error, t));
        });
    }, 400);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [providerConfig]);

  useEffect(() => {
    getOcrStatus()
      .then(setOcrStatus)
      .catch(() => {
        // OCR status is non-critical; the panel degrades gracefully.
        setOcrStatus(null);
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = () => {
      fetchHealth()
        .then((health) => {
          if (!cancelled) setHealthStatus(health.status === "ok" ? "online" : "offline");
        })
        .catch(() => {
          if (!cancelled) setHealthStatus("offline");
        });
    };
    check();
    const timer = window.setInterval(check, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function refreshArtifacts(projectId: string) {
    const requestSequence = ++artifactRequestSequenceRef.current;
    try {
      const next = await listProjectArtifacts(projectId);
      if (requestSequence === artifactRequestSequenceRef.current && activeProjectIdRef.current === projectId) {
        setArtifactTree(next);
      }
    } catch {
      if (requestSequence === artifactRequestSequenceRef.current && activeProjectIdRef.current === projectId) {
        setArtifactTree(null);
      }
    }
  }

  async function refreshRecentProjects() {
    try {
      setRecentProjects(await listProjects());
    } catch {
      // Recent-project navigation is an enhancement; the current project stays usable.
    }
  }

  async function openProject(projectId: string, stage?: string) {
    const loadSequence = ++projectLoadSequenceRef.current;
    activeProjectIdRef.current = projectId;
    setProject(null);
    setProfile(emptyProfile);
    setProjectLoading(true);
    setBusy(t("busy.openingProject"));
    setError("");
    try {
      const next = await fetchProject(projectId);
      if (loadSequence !== projectLoadSequenceRef.current) return;
      updateProject(next);
      setActiveStep(resolveProjectStage(next, stage));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setProjectLoading(false);
      setBusy("");
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
    if (activeProjectIdRef.current && activeProjectIdRef.current !== next.project_id) return;
    activeProjectIdRef.current = next.project_id;
    setProject(next);
    setPipelineSteps(pipelineStepsFromProject(next));
    setDesignSummary(null);
    setAgentPackage(null);
    setAgentValidation(null);
    setPptxExport(null);
    setArtifactTree(null);
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
    } else {
      setProfile(emptyProfile);
      setAutoFilledFields(new Set());
      setUserEditedFields(new Set());
    }
    setBlueprint(next.lesson_blueprint ?? null);
    void refreshArtifacts(next.project_id);
    if (next.preview_url) {
      setPreviewError("");
      setPreviewLoading(true);
      setPreviewKey((key) => key + 1);
    } else {
      setPreviewError("");
      setPreviewLoading(false);
    }
    void refreshRecentProjects();
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
    activeProjectIdRef.current = null;
    projectLoadSequenceRef.current += 1;
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
    if (!project || !canUseAction("material", "rerun_ocr")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    setBusy(t("ocr.busy"));
    setError("");
    try {
      const next = await rerunOcr(project.project_id, engine, project.project_revision);
      updateProject(next);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleReviewMedia(assetId: string, state: string, candidateId?: string) {
    if (!project || !canUseAction("quality", "review_media")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    setBusy(t("busy.reviewingMedia"));
    setError("");
    try {
      await reviewMedia(project.project_id, assetId, { state, candidate_id: candidateId }, project.project_revision);
      updateProject(await fetchProject(project.project_id));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleReplaceMedia(assetId: string, file: File) {
    if (!project || !canUseAction("quality", "replace_media")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    setBusy(t("busy.replacingMedia"));
    setError("");
    try {
      await replaceMedia(project.project_id, assetId, file, "", project.project_revision);
      updateProject(await fetchProject(project.project_id));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleForceRegenerateMedia() {
    if (!project || !canUseAction("presentation", "generate_media")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    await run(t("busy.regeneratingMedia"), () => generateMedia(project.project_id, true, project.project_revision), "quality");
  }

  async function handleSaveProfile(nextStep?: StepId) {
    if (!project || !canUseAction("profile", "confirm_profile")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    await run(
      t("busy.savingProfile"),
      async () => {
        const next = await saveProfile(project.project_id, profile, project.project_revision);
        return next;
      },
      nextStep
    );
  }

  async function handleRunFullPipeline() {
    if (!project || !canUseAction("design", "run_pipeline")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    setBusy(t("busy.generating"));
    setError("");
    setPipelineSteps(markPipelineStep("pipeline.contract"));
    try {
      const saved = await saveProfile(project.project_id, profile, project.project_revision);
      updateProject(saved);
      setPipelineSteps(markPipelineStep("pipeline.contract", "done"));
      setPipelineSteps(markPipelineStep("pipeline.blueprint"));
      const next = await runPipeline(project.project_id, saved.project_revision);
      setPipelineSteps(pipelineStepsFromProject(next));
      updateProject(next);
      const backendStage = next.current_stage as StepId | undefined;
      if (backendStage && steps.some((step) => step.id === backendStage)) {
        setActiveStep(backendStage);
      } else {
        setActiveStep("quality");
      }
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
    if (!project || !canUseAction("delivery", "force_export") || !gateSummary?.force_export_allowed) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
    setBusy(t("busy.exporting"));
    setError("");
    try {
      const blob = await forceExportProject(project.project_id);
      downloadBlob(blob, `HanClassStudio_Output_${project.project_id}.zip`);
      updateProject(await fetchProject(project.project_id));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusy("");
    }
  }

  async function handleEditablePptxExport(force = false) {
    const action = force ? "force_export" : "export";
    if (!project || !canUseAction("delivery", action) || (force ? !gateSummary?.force_export_allowed : !gateSummary?.export_allowed)) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
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
    if (!project || !canUseAction("delivery", "agent_package")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
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
    if (!project || !canUseAction("delivery", "agent_validate")) {
      setNavNotice(t("status.actionUnavailable"));
      return;
    }
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

  const gateSummary = project?.gate_summary;
  const qualityState = gateSummary?.quality_report.state ?? "not_run";
  const qualityBlocked = gateSummary?.overall_state === "blocked" || gateSummary?.overall_state === "failed" || gateSummary?.overall_state === "stale";
  const exportBlocked = Boolean(project && gateSummary && !gateSummary.export_allowed);
  const issueCount = safeList(gateSummary?.blocking_reasons).length + safeList(gateSummary?.warnings).length;
  const profileConfirmed = project?.profile_state === "confirmed";
  const canRunPipeline = Boolean(
    project?.project_id
      && profileConfirmed
      && !busy
      && canUseAction("profile", "confirm_profile")
      && canUseAction("design", "run_pipeline"),
  );
  const nextWorkflowAction = getNextWorkflowAction(project);
  const qualityLabel = gateStateLabel(qualityState, t);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label={t("nav.workflow")}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            汉
          </div>
          <div>
            <strong>HanClassStudio</strong>
            <span>{t("app.version")}</span>
          </div>
        </div>
        <nav className="step-list" aria-label={t("nav.workflow")}>
          {steps.map((step) => {
            const Icon = step.icon;
            const access = stageAccess[step.id];
            return (
              <button
                key={step.id}
                type="button"
                className={activeStep === step.id ? "active" : ""}
                aria-current={activeStep === step.id ? "step" : undefined}
                aria-disabled={!access.viewable || undefined}
                disabled={!access.viewable}
                title={!access.viewable ? t("nav.locked") : undefined}
                onClick={() => {
                  if (access.viewable) {
                    setActiveStep(step.id);
                    setNavNotice("");
                  } else {
                    setNavNotice(t("nav.locked"));
                  }
                }}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{t(step.titleKey)}</span>
                {completedSteps[step.id] && <CheckCircle2 size={16} aria-hidden="true" />}
              </button>
            );
          })}
        </nav>
        <RecentProjects projects={recentProjects} loading={projectsLoading} currentProjectId={project?.project_id} onOpen={openProject} />
        <ProviderStatusPanel config={providerConfig} catalog={providerCatalog} onOpenSettings={() => setSettingsOpen(true)} />
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <p className="eyebrow">{t("topbar.eyebrow")}</p>
            <h1>{projectLoading ? <span className="skeleton-line skeleton-line-title" aria-hidden="true" /> : profile.lesson_title || t("topbar.newLesson")}</h1>
          </div>
          <div className="topbar-aside">
            <details className="project-status-menu">
              <summary aria-label={projectLoading ? t("status.loadingProject") : project ? qualityLabel : t("status.ready")}>
                <ShieldCheck size={17} aria-hidden="true" />
                <span className="project-status-label">
                  {projectLoading ? t("status.loadingProject") : project ? qualityLabel : t("status.ready")}
                </span>
                <ChevronDown size={16} aria-hidden="true" />
              </summary>
              <div>
                <span>{healthStatus === "online" ? t("status.backendOnline") : healthStatus === "offline" ? t("status.backendOffline") : t("status.backendChecking")}</span>
                <span>{project?.project_id ? t("status.project", { id: project.project_id }) : t("status.noProject")}</span>
                <span>{project?.route ? t("status.route", { route: project.route }) : t("status.routePending")}</span>
                <span>{profileConfirmed ? t("status.profileConfirmed") : t("status.profilePending")}</span>
                <span>{issueCount === 0 ? qualityLabel : t("status.issues", { n: issueCount })}</span>
              </div>
            </details>
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
            <ThemeSwitcher theme={theme} onChange={handleThemeChange} />
            <LanguageSwitcher />
          </div>
        </header>

        <MobileWorkflowNav activeStep={activeStep} stageAccess={stageAccess} onChange={setActiveStep} />

        {error && <div className="notice error">{error}</div>}
        {navNotice && <div className="notice">{navNotice}</div>}
        <PipelineStatus steps={pipelineSteps} />
        {busy && (
          <div className="notice loading">
            <Loader2 size={18} aria-hidden="true" />
            {busy}
          </div>
        )}

        {projectLoading ? (
          <ProjectLoadingSkeleton />
        ) : activeStep === "material" && (
          <section className="panel">
            <PanelHeader icon={<FileUp size={22} />} title={t("panel.upload.title")} action={t("panel.upload.action")} state={stageAccess.material.state} />
            <label className="upload-zone">
              <FileUp size={34} aria-hidden="true" />
              <span>{t("upload.choose")}</span>
              <input type="file" accept=".pptx,.pdf,.png,.jpg,.jpeg" onChange={handleUpload} />
            </label>
            {project?.source_material && (
              <>
                <SourcePreview project={project} />
                <OcrRerunPanel project={project} ocrStatus={ocrStatus} onRerun={handleRerunOcr} busy={Boolean(busy)} canRerun={canUseAction("material", "rerun_ocr")} />
              </>
            )}
          </section>
        )}

        {activeStep === "profile" && (
          <section className="panel">
            <PanelHeader icon={<UsersRound size={22} />} title={t("panel.profile.title")} action={t("panel.profile.action")} state={stageAccess.profile.state} />
            <ProfileForm profile={profile} onChange={handleProfileChange} editable={stageAccess.profile.editable} autoFilledFields={autoFilledFields} userEditedFields={userEditedFields} />
            <fieldset className="field-group">
              <legend>{t("mode.legend")}</legend>
              <div className="segmented-grid">
                {modes.map((mode) => (
                  <button
                    key={mode.value}
                    type="button"
                    className={profile.generation_mode === mode.value ? "selected" : ""}
                    disabled={!stageAccess.profile.editable}
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
                disabled={!stageAccess.profile.editable}
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
                disabled={!project || !!busy || !canUseAction("profile", "confirm_profile")}
                onClick={() => handleSaveProfile("design")}
              >
                <Save size={18} aria-hidden="true" />
                {t("btn.saveProfile")}
              </button>
            </div>
          </section>
        )}

        {activeStep === "design" && (
          <section className="panel design-boundary">
            <PanelHeader icon={<GitBranch size={22} />} title={t("design.title")} action={t("design.action")} state={stageAccess.design.state} />
            <div className="state-flow" aria-label={t("design.flowLabel")}>
              <span>{t("design.state")}</span><ChevronRight size={16} /><span>{t("design.goal")}</span><ChevronRight size={16} /><span>{t("design.evidence")}</span><ChevronRight size={16} /><span>{t("design.activity")}</span>
            </div>
            <div className="boundary-note">
              <strong>{t("design.boundaryTitle")}</strong>
              <p>{t("design.boundaryBody")}</p>
            </div>
            <StateFirstSummaryView summary={designSummary} />
            <div className="action-row">
              <button type="button" className="secondary" onClick={() => setActiveStep("profile")}>{t("design.back")}</button>
              <button type="button" className="primary" disabled={!stageAccess.presentation.viewable} onClick={() => setActiveStep("presentation")}>{t("design.continue")}</button>
            </div>
          </section>
        )}

        {activeStep === "presentation" && (
          <section className="panel">
            <PanelHeader icon={<LayoutTemplate size={22} />} title={t("presentation.title")} action={t("panel.outline.action", { n: blueprint?.slides.length ?? 0 })} state={stageAccess.presentation.state} />
            <StageNotice stage={project?.stages?.find((item) => item.stage_id === "presentation")} />
            <p className="production-note">{t("presentation.compatibility")}</p>
            {blueprint ? (
              <BlueprintEditor blueprint={blueprint} componentRegistry={componentRegistry} componentOptions={componentOptions} editable={stageAccess.presentation.editable} onChange={setBlueprint} />
            ) : (
              <EmptyState text={t("presentation.empty")} />
            )}
            <div className="action-row">
              {!blueprint && (
                  <button type="button" className="primary" disabled={!project || !!busy || !canUseAction("presentation", "generate_blueprint")} onClick={() => project && run(t("busy.generatingOutline"), async () => {
                  const saved = await saveProfile(project.project_id, profile, project.project_revision);
                  return generateBlueprint(project.project_id, saved.project_revision);
                }, "presentation")}>
                  <Play size={18} aria-hidden="true" />{t("btn.generateOutline")}
                </button>
              )}
              <button
                type="button"
                className="secondary"
                disabled={!project || !blueprint || !!busy || !canUseAction("presentation", "edit_blueprint")}
                onClick={() => project && blueprint && run(t("busy.savingOutline"), () => saveBlueprint(project.project_id, blueprint, project.project_revision))}
              >
                <Save size={18} aria-hidden="true" />
                {t("btn.saveOutline")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !blueprint || !!busy || !canUseAction("presentation", "generate_media")}
                onClick={() =>
                  project &&
                  blueprint &&
                  run(
                    t("busy.generatingMedia"),
                    async () => {
                      const saved = await saveBlueprint(project.project_id, blueprint, project.project_revision);
                      return generateMedia(project.project_id, false, saved.project_revision);
                    },
                    "quality"
                  )
                }
              >
                <Image size={18} aria-hidden="true" />
                {t("btn.generateMedia")}
              </button>
            </div>
          </section>
        )}

        {activeStep === "quality" && (
          <section className="panel preview-panel">
            <PanelHeader icon={<MonitorPlay size={22} />} title={t("panel.preview.title")} action={project?.preview_url ? t("panel.preview.actionRendered") : t("panel.preview.actionReady")} state={stageAccess.quality.state} />
            <StageNotice stage={project?.stages?.find((item) => item.stage_id === "quality")} />
            <WorkflowResolution
              blockers={safeList(gateSummary?.blocking_reasons)}
              nextStage={nextWorkflowAction?.stageId as StepId | undefined}
              activeStage="quality"
              onNavigate={setActiveStep}
            />
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy || nextWorkflowAction?.stageId !== "presentation" || nextWorkflowAction.action !== "generate_media"}
                onClick={() => project && nextWorkflowAction?.stageId === "presentation" && nextWorkflowAction.action === "generate_media" && run(t("busy.generatingMedia"), () => generateMedia(project.project_id, false, project.project_revision))}
              >
                <Image size={18} aria-hidden="true" />
                {t("btn.regenerateMedia")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy || nextWorkflowAction?.stageId !== "quality" || nextWorkflowAction.action !== "render"}
                onClick={() => {
                  if (!project || nextWorkflowAction?.stageId !== "quality" || nextWorkflowAction.action !== "render") {
                    setNavNotice(t("status.actionUnavailable"));
                    return;
                  }
                  setPreviewError("");
                  setPreviewLoading(true);
                  run(t("busy.rendering"), () => renderProject(project.project_id, project.project_revision));
                }}
              >
                <MonitorPlay size={18} aria-hidden="true" />
                {t("btn.rerender")}
              </button>
            </div>
            <MediaReviewPanel
              projectId={project?.project_id}
              manifest={project?.asset_manifest ?? null}
              busy={Boolean(busy)}
              canReview={canUseAction("quality", "review_media")}
              canReplace={canUseAction("quality", "replace_media")}
              canRegenerate={canUseAction("presentation", "generate_media")}
              onReview={handleReviewMedia}
              onReplace={handleReplaceMedia}
              onForceRegenerate={handleForceRegenerateMedia}
            />
            <QualityReportView project={project} />
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
            <div className="action-row">
              <button type="button" className="primary" disabled={!project || !stageAccess.delivery.viewable} onClick={() => setActiveStep("delivery")}>{t("quality.toDelivery")}</button>
            </div>
          </section>
        )}

        {activeStep === "delivery" && (
          <section className="panel delivery-panel">
            <PanelHeader icon={<PackageCheck size={22} />} title={t("delivery.title")} action={t("delivery.action")} state={stageAccess.delivery.state} />
            <div className={`delivery-gate ${qualityBlocked ? "blocked" : exportBlocked ? "pending" : "pass"}`}>
              <ShieldCheck size={20} aria-hidden="true" />
              <div><strong>{qualityBlocked ? t("export.blocked") : exportBlocked ? qualityLabel : t("status.qualityPass")}</strong><span>{issueCount ? t("status.issues", { n: issueCount }) : qualityLabel}</span></div>
            </div>
            <WorkflowResolution
              blockers={safeList(gateSummary?.blocking_reasons)}
              nextStage={nextWorkflowAction?.stageId as StepId | undefined}
              activeStage="delivery"
              onNavigate={setActiveStep}
            />
            <div className="export-format-grid" role="radiogroup" aria-label={t("delivery.format") }>
              <button type="button" role="radio" aria-checked={exportFormat === "html"} className={exportFormat === "html" ? "export-format-card selected" : "export-format-card"} onClick={() => setExportFormat("html")}>
                <FileArchive size={24} /><strong>{t("delivery.html")}</strong><span>{t("delivery.htmlDetail")}</span>{exportFormat === "html" && <CheckCircle2 size={16} aria-label={t("delivery.selected")} />}
              </button>
              <button type="button" role="radio" aria-checked={exportFormat === "pptx"} className={exportFormat === "pptx" ? "export-format-card selected" : "export-format-card"} onClick={() => setExportFormat("pptx")}>
                <LayoutTemplate size={24} /><strong>{t("delivery.pptx")}</strong><span>{t("delivery.pptxDetail")}</span>{exportFormat === "pptx" && <CheckCircle2 size={16} aria-label={t("delivery.selected")} />}
              </button>
            </div>
            <div className="action-row">
              {exportFormat === "html" ? (
                <a className={project?.export_url && gateSummary?.export_allowed && canUseAction("delivery", "export") ? "download-link" : "download-link disabled"} href={project?.export_url && gateSummary?.export_allowed && canUseAction("delivery", "export") ? exportUrl(project.project_id) : undefined} aria-disabled={!project?.export_url || !gateSummary?.export_allowed || !canUseAction("delivery", "export")}>
                  <ArrowDownToLine size={18} />{project?.export_url ? t("btn.downloadZip") : t("export.waiting")}
                </a>
              ) : (
                <button type="button" className="primary" disabled={!project || !!busy || !gateSummary?.export_allowed || !canUseAction("delivery", "export")} onClick={() => handleEditablePptxExport(false)}>
                  <ArrowDownToLine size={18} />{t("btn.exportPptx")}
                </button>
              )}
            </div>
            <details className="more-actions">
              <summary>{t("delivery.more")}</summary>
              <p>{t("export.note")}</p>
              <div className="action-row">
                <button type="button" className="danger-button" disabled={!project || !!busy || !gateSummary?.force_export_allowed || gateSummary.export_allowed || !canUseAction("delivery", "force_export")} onClick={() => setForceExportType("html")}>{t("btn.forceExport")}</button>
                <button type="button" className="danger-button" disabled={!project || !!busy || !gateSummary?.force_export_allowed || gateSummary.export_allowed || !canUseAction("delivery", "force_export")} onClick={() => setForceExportType("pptx")}>{t("btn.forceExportPptx")}</button>
              </div>
            </details>
            <details className="advanced-details">
              <summary>{t("delivery.advanced")}</summary>
              <SpecLockSummary specLock={artifactTree?.spec_lock ?? null} />
              <AgentHandoffPanel
                project={project}
                agentPackage={agentPackage}
                validation={agentValidation}
                copied={agentCopied}
                busy={Boolean(busy)}
                canGenerate={canUseAction("delivery", "agent_package")}
                canValidate={canUseAction("delivery", "agent_validate")}
                onGenerate={handleGenerateAgentPackage}
                onCopy={handleCopyAgentTask}
                onValidate={handleValidateAgentOutput}
              />
              <ArtifactInspector tree={artifactTree} />
            </details>
            {project?.export_url && gateSummary?.export_allowed && <div className="export-ready"><CheckCircle2 size={18} /><span>{t("export.ready")}</span><a href={exportUrl(project.project_id)}>HanClassStudio_Output_*.zip</a></div>}
            {pptxExport && <div className="export-ready"><CheckCircle2 size={18} /><span>{t("export.pptxReady")}</span><a href={previewUrl(pptxExport.download_url) ?? undefined}>{pptxExport.filename}</a></div>}
          </section>
        )}
      </main>
      {settingsOpen && (
        <ModelSettingsModal
          config={providerConfig}
          catalog={providerCatalog}
          registry={providerRegistry}
          onRegistryRefresh={reloadProviderContracts}
          onRegistryDiscover={discoverProviderSources}
          synced={settingsSynced}
          error={providerSaveError}
          onChange={(next) => {
            setProviderConfig(next);
            writeStoredProviderConfig(next);
          }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
      {forceExportType && (
        <ForceExportDialog
          type={forceExportType}
          issueCount={issueCount}
          project={project}
          busy={Boolean(busy)}
          gateSummary={gateSummary}
          canExport={canUseAction("delivery", "force_export")}
          onCancel={() => setForceExportType(null)}
          onConfirm={async (type) => {
            setForceExportType(null);
            if (type === "html") await handleForceExport();
            else await handleEditablePptxExport(true);
          }}
        />
      )}
      {onboardingOpen && (
        <OnboardingWizard
          config={providerConfig}
          catalog={providerCatalog}
          registry={providerRegistry}
          theme={theme}
          onChange={(next) => {
            setProviderConfig(next);
            writeStoredProviderConfig(next);
          }}
          onRegistryRefresh={reloadProviderContracts}
          onRegistryDiscover={discoverProviderSources}
          onThemeChange={handleThemeChange}
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
  zh: "中",
  en: "EN",
  ja: "日",
  ko: "한",
  ar: "ع",
  ru: "РУ",
};

function RecentProjects({
  projects,
  loading,
  currentProjectId,
  onOpen,
}: {
  projects: ProjectSummary[];
  loading: boolean;
  currentProjectId?: string;
  onOpen: (projectId: string, stage?: string) => void;
}) {
  const { t } = useI18n();
  return (
    <section className="recent-projects" aria-label={t("project.recent")}>
      <div className="recent-projects-heading"><strong>{t("project.recent")}</strong>{loading && <Loader2 size={13} className="spin" aria-hidden="true" />}</div>
      {projects.length ? projects.slice(0, 5).map((item) => (
        <button
          type="button"
          key={item.project_id}
          className={item.project_id === currentProjectId ? "selected" : ""}
          onClick={() => onOpen(item.project_id, item.current_stage)}
          title={item.source_filename ?? item.project_id}
        >
          <span>{item.source_filename || item.project_id}</span>
          <small>{stageTitleLabel(item.current_stage, t)}</small>
        </button>
      )) : <p>{t("project.noRecent")}</p>}
    </section>
  );
}

function MobileWorkflowNav({
  activeStep,
  stageAccess,
  onChange,
}: {
  activeStep: StepId;
  stageAccess: Record<StepId, StageAccess>;
  onChange: (step: StepId) => void;
}) {
  const { t } = useI18n();
  const index = steps.findIndex((step) => step.id === activeStep);
  const previous = [...steps.slice(0, index)].reverse().find((step) => stageAccess[step.id].viewable);
  const next = steps.slice(index + 1).find((step) => stageAccess[step.id].viewable);
  return (
    <nav className="mobile-workflow" aria-label={t("nav.workflow")}>
      <button type="button" className="secondary small-button" disabled={!previous} onClick={() => previous && onChange(previous.id)}>
        <ChevronRight size={16} className="mobile-workflow-prev-icon" aria-hidden="true" />
        {t("mobileWorkflow.previous")}
      </button>
      <div className="mobile-workflow-current" aria-live="polite">
        <strong>{t("mobileWorkflow.step", { n: index + 1, stage: stageTitleLabel(activeStep, t) })}</strong>
      </div>
      <button type="button" className="secondary small-button" disabled={!next} onClick={() => next && onChange(next.id)}>
        {t("mobileWorkflow.next")}
        <ChevronRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}

function ThemeSwitcher({
  theme,
  onChange,
  inOnboarding = false,
}: {
  theme: ThemeMode;
  onChange: (theme: ThemeMode) => void;
  inOnboarding?: boolean;
}) {
  const { t } = useI18n();
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  return (
    <label className={`theme-switcher${inOnboarding ? " theme-switcher--field" : ""}`} title={t("theme.label")}>
      {inOnboarding && <span>{t("theme.label")}</span>}
      <span className="theme-select-wrap">
        <Icon size={16} aria-hidden="true" />
        <select value={theme} onChange={(event) => onChange(event.target.value as ThemeMode)} aria-label={t("theme.label")}>
          <option value="light">{t("theme.light")}</option>
          <option value="dark">{t("theme.dark")}</option>
          <option value="system">{t("theme.system")}</option>
        </select>
      </span>
    </label>
  );
}

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
  catalog,
  onOpenSettings,
}: {
  config: ProviderConfig;
  catalog: ProviderDefinition[];
  onOpenSettings: () => void;
}) {
  const { t } = useI18n();
  const total = CAPABILITY_ORDER.length;
  const configured = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c], c, catalog)).length;
  const available = CAPABILITY_ORDER.filter((c) => isCapabilityAvailable(config[c], c, catalog)).length;

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
          <span>{t("provider.summary", { configured, available, total })}</span>
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

function CapabilityConfigPanel({
  capability,
  config,
  catalog,
  onChange,
  registry,
  onRegistryRefresh,
  onRegistryDiscover,
  showRegistryEntry = false,
}: {
  capability: ProviderCapability;
  config: ProviderConfig;
  catalog: ProviderDefinition[];
  onChange: (next: ProviderConfig) => void;
  registry?: ProviderRegistryCatalog | null;
  onRegistryRefresh?: () => void;
  onRegistryDiscover?: () => Promise<ProviderRegistryRefreshResponse>;
  showRegistryEntry?: boolean;
}) {
  const { t } = useI18n();
  const cfg = config[capability];
  const selectedProvider = cfg ? getProviderById(cfg.providerId, capability, catalog) : undefined;
  const [mode, setMode] = useState<"local" | "cloud">(selectedProvider?.category ?? "local");
  const providers = getCapabilityProviders(capability, mode, catalog);
  const availableProviders = getAvailableCapabilityProviders(capability, mode, catalog);
  const selectableProviders = showRegistryEntry
    ? availableProviders
    : getConfigurableCapabilityProviders(capability, mode, catalog);
  const selectedId = selectedProvider && selectedProvider.category === mode ? selectedProvider.id : "";
  const optionProviders = selectableProviders.some((provider) => provider.id === selectedId)
    ? selectableProviders
    : [...selectableProviders, ...providers.filter((provider) => provider.id === selectedId)];
  const registryProviders = getCapabilityRegistryProviders(capability, registry ?? null);
  const showOnboardingRegistry = showRegistryEntry && mode === "local" && availableProviders.length === 0;
  const providerSelectRef = useRef<HTMLSelectElement>(null);
  const hadAvailableProviderRef = useRef(availableProviders.length > 0);
  const previousCapabilityRef = useRef(capability);

  useEffect(() => {
    if (previousCapabilityRef.current === capability) return;
    previousCapabilityRef.current = capability;
    setMode(selectedProvider?.category ?? "local");
  }, [capability, selectedProvider?.category]);

  useEffect(() => {
    const wasAvailable = hadAvailableProviderRef.current;
    hadAvailableProviderRef.current = availableProviders.length > 0;
    if (showRegistryEntry && !wasAvailable && availableProviders.length > 0) {
      window.requestAnimationFrame(() => providerSelectRef.current?.focus());
    }
  }, [availableProviders.length, showRegistryEntry]);

  useEffect(() => {
    if (selectedProvider && selectedProvider.category !== mode) {
      setMode(selectedProvider.category);
      return;
    }
    if (!cfg) {
      const first = getAvailableCapabilityProviders(capability, mode, catalog)[0];
      if (first && first.category !== mode) setMode(first.category);
    }
  }, [capability, catalog, cfg, mode, selectedProvider]);

  function applyProvider(id: string) {
    const def = getProviderById(id, capability, catalog);
    if (!def || !def.implemented || !def.configurable || (showRegistryEntry && !def.available)) return;
    const defaults: Record<string, string> = {};
    def.fields.forEach((f) => {
      defaults[f.key] = f.type === "select" && f.options?.length ? f.options[0].value : "";
    });
    onChange({ ...config, [capability]: { providerId: id, values: defaults } });
  }

  function switchMode(next: "local" | "cloud") {
    setMode(next);
    const selectable = (showRegistryEntry
      ? getAvailableCapabilityProviders(capability, next, catalog)
      : getConfigurableCapabilityProviders(capability, next, catalog))[0];
    if (selectable) {
      applyProvider(selectable.id);
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
        <select
          className="deploy-mode-native-select"
          value={mode}
          onChange={(event) => switchMode(event.target.value as "local" | "cloud")}
          aria-label={t("provider.deployMode")}
        >
          <option value="local">{t("provider.mode.local")}</option>
          <option value="cloud">{t("provider.mode.cloud")}</option>
        </select>
        <div className="segmented-toggle deploy-mode-toggle" role="group" aria-label={t("provider.deployMode")}>
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

      {selectableProviders.length === 0 ? (
        <p className="muted-text">{t("provider.noProviders")}</p>
      ) : (
        <label className="field">
          <span>{t("provider.selectProvider")}</span>
          <select ref={providerSelectRef} value={selectedId} onChange={(e) => applyProvider(e.target.value)}>
            <option value="">{t("provider.chooseProvider")}</option>
            {optionProviders.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.implemented || !p.configurable || (showRegistryEntry && !p.available)}>
                  {p.name} — {p.description}
                </option>
            ))}
          </select>
        </label>
      )}

      {availableProviders.length === 0 && showOnboardingRegistry && (
        <section className="onboarding-provider-registry" aria-labelledby={`onboardingRegistryTitle-${capability}`}>
          <div className="onboarding-provider-registry-intro">
            <strong id={`onboardingRegistryTitle-${capability}`}>
              {t("provider.registry.onboarding.emptyTitle", { capability: t(CAPABILITY_META[capability].labelKey) })}
            </strong>
            <p>{t("provider.registry.onboarding.emptyBody")}</p>
          </div>
          <ProviderRegistryPanel
            registry={registry ?? null}
            capability={capability}
            compact
            onRefresh={onRegistryRefresh ?? (() => undefined)}
            onDiscover={onRegistryDiscover ?? (() => Promise.reject(new Error(t("provider.registry.refreshUnavailable"))))}
          />
        </section>
      )}

      {availableProviders.length > 0 && showRegistryEntry && registryProviders.some((status) => status.installation.install_state === "available") && (
        <div className="notice success" role="status">
          {t("provider.registry.onboarding.availableNotice")}
        </div>
      )}

      {cfg && (!selectedProvider || !selectedProvider.implemented || !selectedProvider.available) && (
        <div className="notice error" role="status">
          {selectedProvider?.unavailable_reason ? localizeBackendMessage(selectedProvider.unavailable_reason, t) : t("provider.unavailable")}
        </div>
      )}

      {selectedProvider && selectedProvider.category === mode && (
        <>
          {(selectedProvider.official_url || selectedProvider.api_signup_url || selectedProvider.license_name || selectedProvider.terms_url) && (
            <div className="provider-official-links" aria-label={t("provider.sourceLinks")}>
              {selectedProvider.official_url && (
                <a href={selectedProvider.official_url} target="_blank" rel="noreferrer">
                  {t(selectedProvider.category === "local" ? "provider.officialProject" : "provider.officialWebsite")}
                </a>
              )}
              {selectedProvider.api_signup_url && (
                <a href={selectedProvider.api_signup_url} target="_blank" rel="noreferrer">{t("provider.applyApi")}</a>
              )}
              {selectedProvider.terms_url && (
                <a href={selectedProvider.terms_url} target="_blank" rel="noreferrer">{t("provider.terms")}</a>
              )}
              {selectedProvider.license_name && <span>{t("provider.licenseName", { license: selectedProvider.license_name })}</span>}
            </div>
          )}
          <div className="provider-fields">
          {selectedProvider.fields.map((field) => (
            <label className="field" key={field.key}>
              <span>
                {field.label}
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
                  placeholder={field.placeholder ?? ""}
                  onChange={(e) => setValue(field.key, e.target.value)}
                />
              )}
            </label>
          ))}
          </div>
        </>
      )}
    </div>
  );
}

function registryBlockerLabel(code: string, t: (key: string) => string): string {
  if (code === "platform_unsupported" || code === "architecture_unsupported") return t("provider.registry.blocker.platform");
  if (code === "disk_space_insufficient") return t("provider.registry.blocker.disk");
  if (code === "python_unsupported") return t("provider.registry.blocker.python");
  if (code === "memory_insufficient") return t("provider.registry.blocker.memory");
  if (code === "gpu_unavailable") return t("provider.registry.blocker.gpu");
  if (code === "configuration_required" || code === "provider_configuration_missing") return t("provider.registry.blocker.configuration");
  return t("provider.registry.blocker.generic");
}

function RegistryInstallConfirmDialog({
  prepared,
  onCancel,
  onConfirm,
}: {
  prepared: ProviderInstallPrepareResponse;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  useNativeDialog(dialogRef, onCancel);

  async function confirm() {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby="registryInstallTitle" aria-describedby="registryInstallDescription" aria-modal="true">
      <section className="confirm-modal">
        <h2 id="registryInstallTitle">{t("provider.registry.confirmTitle")}</h2>
        <p id="registryInstallDescription">{t("provider.registry.confirmBody")}</p>
        <dl className="provider-registry-plan">
          <div><dt>{t("provider.registry.version")}</dt><dd>{prepared.plan.version}</dd></div>
          <div><dt>{t("provider.registry.source")}</dt><dd>{prepared.plan.source_ref}</dd></div>
          <div><dt>{t("provider.registry.checksum")}</dt><dd>{prepared.plan.checksum_sha256.slice(0, 12)}…</dd></div>
        </dl>
        <ol className="provider-install-steps">
          {prepared.plan.steps.map((step) => <li key={step.kind}>{step.label}</li>)}
        </ol>
        <div className="action-row">
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>{t("provider.registry.cancel")}</button>
          <button type="button" className="primary" onClick={() => void confirm()} disabled={busy}>
            {busy ? t("provider.registry.installing") : t("provider.registry.confirm")}
          </button>
        </div>
      </section>
    </dialog>
  );
}

function ProviderRegistryPanel({
  registry,
  capability,
  compact = false,
  onRefresh,
  onDiscover,
}: {
  registry: ProviderRegistryCatalog | null;
  capability?: ProviderCapability;
  compact?: boolean;
  onRefresh: () => void;
  onDiscover: () => Promise<ProviderRegistryRefreshResponse>;
}) {
  const { t } = useI18n();
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [error, setError] = useState("");
  const [refreshNotice, setRefreshNotice] = useState("");
  const [prepared, setPrepared] = useState<ProviderInstallPrepareResponse | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, Record<string, string>>>({});
  const [logs, setLogs] = useState<Record<string, ProviderInstallLog[]>>({});
  const pendingTriggerRef = useRef<HTMLElement | null>(null);

  const statuses = capability
    ? (registry?.providers ?? []).filter((status) => status.entry.capability === capability)
    : (registry?.providers ?? []);
  const titleId = capability ? `providerRegistryTitle-${capability}` : "providerRegistryTitle";

  async function discover() {
    setDiscovering(true);
    setError("");
    setRefreshNotice("");
    try {
      const result = await onDiscover();
      setRefreshNotice(t("provider.registry.refreshed", { n: result.changed_provider_ids.length }));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setDiscovering(false);
    }
  }

  async function prepare(status: ProviderRegistryStatus, retry = false, trigger?: HTMLElement) {
    pendingTriggerRef.current = trigger ?? null;
    setBusyProvider(status.entry.provider_id);
    setError("");
    try {
      const result = retry ? await retryProviderInstall(status.entry.provider_id) : await prepareProviderInstall(status.entry.provider_id);
      setPrepared(result);
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusyProvider(null);
    }
  }

  async function confirm() {
    if (!prepared) return;
    setBusyProvider(prepared.plan.provider_id);
    setError("");
    try {
      await confirmProviderInstall(prepared.plan.provider_id, prepared.plan.plan_id, prepared.confirmation_token);
      setPrepared(null);
      onRefresh();
      window.requestAnimationFrame(() => pendingTriggerRef.current?.focus());
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusyProvider(null);
    }
  }

  function closePrepared() {
    setPrepared(null);
    window.requestAnimationFrame(() => pendingTriggerRef.current?.focus());
  }

  async function configure(status: ProviderRegistryStatus) {
    const values = configValues[status.entry.provider_id] ?? {};
    setBusyProvider(status.entry.provider_id);
    setError("");
    try {
      await configureProviderInstall(status.entry.provider_id, values);
      onRefresh();
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusyProvider(null);
    }
  }

  async function rollback(status: ProviderRegistryStatus) {
    setBusyProvider(status.entry.provider_id);
    setError("");
    try {
      await rollbackProviderInstall(status.entry.provider_id);
      onRefresh();
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusyProvider(null);
    }
  }

  async function loadLogs(providerId: string) {
    setBusyProvider(providerId);
    try {
      const nextLogs = await fetchProviderInstallLogs(providerId);
      setLogs((current) => ({ ...current, [providerId]: nextLogs }));
    } catch (err) {
      setError(readableError(err, t));
    } finally {
      setBusyProvider(null);
    }
  }

  return (
    <section className={`provider-registry${compact ? " provider-registry-compact" : ""}`} aria-labelledby={titleId}>
      <header className="provider-registry-header">
        <div>
          <h3 id={titleId}>{capability ? t("provider.registry.onboarding.title", { capability: t(CAPABILITY_META[capability].labelKey) }) : t("provider.registry.title")}</h3>
          <p>{capability ? t("provider.registry.onboarding.subtitle") : t("provider.registry.subtitle")}</p>
        </div>
        <div className="provider-registry-header-actions">
          <ShieldCheck size={20} aria-hidden="true" />
          <button type="button" className="secondary provider-registry-refresh" disabled={discovering} onClick={() => void discover()}>
            <RefreshCw size={15} className={discovering ? "spin" : ""} aria-hidden="true" />
            {discovering ? t("provider.registry.refreshing") : t("provider.registry.refresh")}
          </button>
        </div>
      </header>
      <div className="provider-registry-source-status">
        <span>
          {registry?.source.kind === "remote" && registry.source.last_refreshed_at
            ? t("provider.registry.lastRefreshed", { time: new Date(registry.source.last_refreshed_at).toLocaleString() })
            : t("provider.registry.bundledSource")}
        </span>
        {registry?.source.source_url && <a href={registry.source.source_url} target="_blank" rel="noreferrer">{t("provider.registry.catalogSource")}</a>}
      </div>
      <p className="provider-registry-rights">{t("provider.registry.rightsNotice")}</p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {refreshNotice && <div className="notice success" role="status">{refreshNotice}</div>}
      <div className="provider-registry-list">
        {statuses.map((status) => {
          const entry = status.entry;
          const installation = status.installation;
          const providerBusy = busyProvider === entry.provider_id;
          const values = configValues[entry.provider_id] ?? {};
          const platforms = Array.isArray(entry.requirements.platforms) ? entry.requirements.platforms.join(", ") : "—";
          const modelFiles = Array.isArray(entry.requirements.model_files) && entry.requirements.model_files.length
            ? entry.requirements.model_files.join(", ")
            : "—";
          return (
            <article className="provider-registry-card" key={entry.provider_id}>
              <div className="provider-registry-card-heading">
                <div>
                  <h4>{entry.display_name}</h4>
                  <p>{entry.description}</p>
                </div>
                <span className={`provider-registry-state ${installation.install_state}`}>
                  {t(`provider.registry.state.${installation.install_state}`)}
                </span>
              </div>
              <dl className="provider-registry-meta">
                <div><dt>{t("provider.registry.source")}</dt><dd><a href={entry.source_url} target="_blank" rel="noreferrer">{entry.repository}</a></dd></div>
                <div><dt>{t("provider.registry.publisher")}</dt><dd>{entry.publisher}</dd></div>
                <div><dt>{t("provider.registry.license")}</dt><dd>{entry.license}</dd></div>
                <div><dt>{t("provider.registry.available")}</dt><dd>{installation.available_version ?? entry.version}</dd></div>
                <div><dt>{t("provider.registry.installed")}</dt><dd>{installation.installed_version ?? "—"}</dd></div>
              </dl>
              <p className="provider-registry-requirements">
                <strong>{t("provider.registry.requirements")}:</strong> {String(entry.requirements.runtime ?? "isolated environment")} · {t("provider.registry.platform")}: {platforms} · {t("provider.registry.memory")}: {String(entry.requirements.min_memory_mb ?? 0)} MB · {t("provider.registry.disk")}: {String(entry.requirements.min_disk_mb ?? 0)} MB · {t("provider.registry.modelFiles")}: {modelFiles}{Boolean(entry.requirements.api_key_required) && <> · {t("provider.registry.credential")}</>}
              </p>
              {entry.mock_only && <p className="provider-registry-mock-note">{t("provider.registry.mockOnly")}</p>}
              {(status.environment.blockers.length > 0 || installation.blockers.length > 0) && (
                <ul className="provider-registry-blockers">
                  {[...status.environment.blockers, ...installation.blockers].map((blocker, index) => (
                    <li key={`${blocker.code}-${index}`}>{registryBlockerLabel(blocker.code, t)}{blocker.requirement ? ` (${blocker.requirement})` : ""}</li>
                  ))}
                </ul>
              )}
              {entry.configuration_schema.length > 0 && ["installed", "configuring"].includes(installation.install_state) && (
                <div className="provider-registry-config">
                  {entry.configuration_schema.map((field) => (
                    <label className="field" key={field.key}>
                      <span>{field.label}{field.required && <span className="required-mark">*</span>}</span>
                      <input
                        type={field.type === "password" ? "password" : field.type}
                        value={values[field.key] ?? ""}
                        placeholder={field.placeholder ?? ""}
                        onChange={(event) => setConfigValues((current) => ({ ...current, [entry.provider_id]: { ...values, [field.key]: event.target.value } }))}
                      />
                    </label>
                  ))}
                  {installation.api_key_present && <p className="muted-text">{t("provider.registry.apiKeyPresent")}</p>}
                </div>
              )}
              <div className="action-row provider-registry-actions">
                {status.install_actions.includes("prepare_install") && <button type="button" className="primary" disabled={providerBusy} onClick={(event) => void prepare(status, false, event.currentTarget)}>{t("provider.registry.prepare")}</button>}
                {status.install_actions.includes("retry_install") && <button type="button" className="secondary" disabled={providerBusy} onClick={(event) => void prepare(status, true, event.currentTarget)}>{t("provider.registry.retry")}</button>}
                {status.install_actions.includes("configure") && <button type="button" className="primary" disabled={providerBusy} onClick={() => void configure(status)}>{t("provider.registry.configure")}</button>}
                {status.install_actions.includes("rollback") && <button type="button" className="secondary" disabled={providerBusy} onClick={() => void rollback(status)}>{t("provider.registry.rollback")}</button>}
                {status.install_actions.includes("view_logs") && <button type="button" className="secondary" disabled={providerBusy} onClick={() => void loadLogs(entry.provider_id)}>{t("provider.registry.logs")}</button>}
                {status.install_actions.length === 0 && <button type="button" className="secondary" disabled>{t("provider.registry.noAction")}</button>}
              </div>
              {logs[entry.provider_id] && (
                <details className="provider-registry-logs" open>
                  <summary>{t("provider.registry.logs")}</summary>
                  <ol>{logs[entry.provider_id].map((item, index) => <li key={`${item.timestamp}-${index}`}><time>{item.timestamp}</time> {item.message}</li>)}</ol>
                </details>
              )}
            </article>
          );
        })}
      </div>
      {statuses.length === 0 && <p className="muted-text">{t("provider.registry.onboarding.noProviders")}</p>}
      {prepared && <RegistryInstallConfirmDialog prepared={prepared} onCancel={closePrepared} onConfirm={confirm} />}
    </section>
  );
}

function ModelSettingsModal({
  config,
  catalog,
  registry,
  onRegistryRefresh,
  onRegistryDiscover,
  onChange,
  onClose,
  synced,
  error,
}: {
  config: ProviderConfig;
  catalog: ProviderDefinition[];
  registry: ProviderRegistryCatalog | null;
  onRegistryRefresh: () => void;
  onRegistryDiscover: () => Promise<ProviderRegistryRefreshResponse>;
  onChange: (next: ProviderConfig) => void;
  onClose: () => void;
  synced?: boolean;
  error?: string;
}) {
  const { t } = useI18n();
  const [activeCapability, setActiveCapability] = useState<ProviderCapability>("ocr");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onClose);

  const configuredCount = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c], c, catalog)).length;

  return (
    <dialog ref={dialogRef} className="modal-backdrop settings-dialog" aria-labelledby="modelSettingsTitle" aria-describedby="modelSettingsDescription" aria-modal="true">
      <section className="settings-modal provider-settings-modal">
        <header>
          <div>
            <p className="eyebrow">{t("settings.eyebrow")}</p>
            <h2 id="modelSettingsTitle">{t("settings.title")}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t("settings.close")}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <p id="modelSettingsDescription" className="sr-only">{t("settings.autoSaveNote")}</p>
        {error && <div className="notice error" role="alert" aria-live="assertive">{error}</div>}

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
              const ok = isCapabilityConfigured(config[capability], capability, catalog);
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
            <CapabilityConfigPanel capability={activeCapability} config={config} catalog={catalog} onChange={onChange} />
          </div>
        </div>

        <ProviderRegistryPanel registry={registry} onRefresh={onRegistryRefresh} onDiscover={onRegistryDiscover} />

        <p className={`settings-saved-note ${synced ? "ok" : ""}`}>
          {synced ? t("settings.savedToServer") : t("settings.autoSaveNote")}
        </p>

        <div className="action-row">
          <button type="button" className="primary" onClick={onClose}>
            {t("settings.done")}
          </button>
        </div>
      </section>
    </dialog>
  );
}

function ForceExportDialog({
  type,
  issueCount,
  project,
  busy,
  gateSummary,
  canExport,
  onCancel,
  onConfirm,
}: {
  type: "html" | "pptx";
  issueCount: number;
  project: ProjectState | null;
  busy: boolean;
  gateSummary?: ProjectState["gate_summary"];
  canExport: boolean;
  onCancel: () => void;
  onConfirm: (type: "html" | "pptx") => Promise<void>;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onCancel);
  const allowed = Boolean(project && gateSummary?.force_export_allowed && !gateSummary.export_allowed && canExport);

  return (
    <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby="forceExportTitle" aria-describedby="forceExportDescription" aria-modal="true">
      <section className="confirm-modal" role="alertdialog" aria-modal="true">
        <h2 id="forceExportTitle">{t("delivery.forceTitle")}</h2>
        <p id="forceExportDescription">{t("delivery.forceBody", { n: issueCount })}</p>
        <div className="action-row">
          <button type="button" className="secondary" onClick={onCancel}>{t("delivery.cancel")}</button>
          <button type="button" className="danger-button filled" disabled={busy || !allowed} onClick={() => void onConfirm(type)}>{t("delivery.confirmForce")}</button>
        </div>
      </section>
    </dialog>
  );
}

function OnboardingWizard({
  config,
  catalog,
  registry,
  theme,
  onChange,
  onRegistryRefresh,
  onRegistryDiscover,
  onThemeChange,
  onClose,
}: {
  config: ProviderConfig;
  catalog: ProviderDefinition[];
  registry: ProviderRegistryCatalog | null;
  theme: ThemeMode;
  onChange: (next: ProviderConfig) => void;
  onRegistryRefresh: () => void;
  onRegistryDiscover: () => Promise<ProviderRegistryRefreshResponse>;
  onThemeChange: (theme: ThemeMode) => void;
  onClose: () => void;
}) {
  const { t, lang, setLang } = useI18n();
  const [step, setStep] = useState(0);
  const [activeCapability, setActiveCapability] = useState<ProviderCapability>("ocr");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onClose);

  const configuredCount = CAPABILITY_ORDER.filter((c) => isCapabilityConfigured(config[c], c, catalog)).length;

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
    <dialog ref={dialogRef} className="settings-dialog onboarding-dialog" aria-labelledby="onboardingTitle" aria-describedby="onboardingDescription" aria-modal="true">
      <section className="settings-modal onboarding-modal">
        <header>
          <div>
            <p className="eyebrow">{t("onboarding.eyebrow")}</p>
            <h2 id="onboardingTitle">{t(steps[step].titleKey)}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t("settings.close")}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <p id="onboardingDescription" className="sr-only">{t("onboarding.welcome.body")}</p>

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
              <div className="onboarding-preferences">
                <label className="field">
                  <span>{t("onboarding.chooseLanguage")}</span>
                  <select value={lang} onChange={(event) => setLang(event.target.value as UiLang)}>
                    {UI_LANGUAGES.map((item) => (
                      <option key={item.code} value={item.code}>
                        {item.native} · {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <ThemeSwitcher theme={theme} onChange={onThemeChange} inOnboarding />
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
                        const ok = isCapabilityConfigured(config[capability], capability, catalog);
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
                  <CapabilityConfigPanel
                    capability={activeCapability}
                    config={config}
                    catalog={catalog}
                    onChange={onChange}
                    registry={registry}
                    onRegistryRefresh={onRegistryRefresh}
                    onRegistryDiscover={onRegistryDiscover}
                    showRegistryEntry
                  />
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
                  const ok = isCapabilityConfigured(cfg, capability, catalog);
                  const def = cfg ? getProviderById(cfg.providerId, capability, catalog) : undefined;
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
    </dialog>
  );
}

function PanelHeader({ icon, title, action, state }: { icon: ReactNode; title: string; action: string; state?: string }) {
  const { t } = useI18n();
  return (
    <div className="panel-header">
      <div>
        <span className="panel-icon">{icon}</span>
        <h2>{title}</h2>
      </div>
      <div className="panel-header-meta">
        <span className="panel-action">{action}</span>
        {state && <span className={`stage-state stage-state-${state}`}>{stageStateLabel(state, t)}</span>}
      </div>
    </div>
  );
}

function ProfileForm({
  profile,
  onChange,
  editable = true,
  autoFilledFields = new Set(),
  userEditedFields = new Set(),
}: {
  profile: LessonProfile;
  onChange: (profile: LessonProfile) => void;
  editable?: boolean;
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
                <input disabled={!editable} value={profile[key]} onChange={(event) => set(key, (event.target as HTMLInputElement).value as never)} />
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
  canRerun,
}: {
  project: ProjectState;
  ocrStatus: OcrStatusResponse | null;
  onRerun: (engine?: string) => void;
  busy: boolean;
  canRerun: boolean;
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
          disabled={busy || !canOcr || !canRerun}
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
          disabled={busy || !canOcr || !canRerun}
          onClick={() => onRerun(engine)}
        >
          <RefreshCw size={16} aria-hidden="true" /> {t("ocr.rerun")}
        </button>
      </div>
      {!canOcr && <p className="ocr-rerun-note">{t("ocr.noEngine")}</p>}
      {canOcr && !canRerun && <p className="ocr-rerun-note">{t("status.actionUnavailable")}</p>}
    </section>
  );
}

function BlueprintEditor({
  blueprint,
  componentRegistry,
  componentOptions,
  editable = true,
  onChange
}: {
  blueprint: LessonBlueprint;
  componentRegistry: ComponentRegistry;
  componentOptions: string[];
  editable?: boolean;
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
                <small>{slide.slide_type || t("editor.pageDefaultType")} · {slide.layout_variant || t("editor.layoutDefault")}</small>
              </span>
              {isExpanded ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
            </button>
            {isExpanded && (
              <div className="outline-fields">
                <label className="field">
                  <span>{t("editor.pageTitle")}</span>
                  <input disabled={!editable} value={slide.title} onChange={(event) => updateSlide(index, { title: event.target.value })} />
                </label>
                <div className="compact-grid">
                  <label className="field">
                    <span>{t("editor.pageType")}</span>
                    <input disabled={!editable} value={slide.slide_type} onChange={(event) => updateSlide(index, { slide_type: event.target.value })} />
                  </label>
                  <label className="field">
                    <span>{t("editor.layout")}</span>
                    <input disabled={!editable} value={slide.layout_variant} onChange={(event) => updateSlide(index, { layout_variant: event.target.value })} />
                  </label>
                </div>

                <section className="editor-section">
                  <div className="editor-section-header">
                    <h3>{t("editor.contentBlocks")}</h3>
                    <button type="button" className="secondary small-button" disabled={!editable} onClick={() => addContentBlock(index)}>
                      <Plus size={16} aria-hidden="true" />
                      {t("editor.addContent")}
                    </button>
                  </div>
                  {blocks.map((block, blockIndex) => (
                    <div className="content-block-editor" key={block.id || blockIndex}>
                      <div className="compact-grid">
                        <label className="field">
                          <span>{t("editor.blockType")}</span>
                          <input disabled={!editable} value={block.block_type} onChange={(event) => updateContentBlock(index, blockIndex, { block_type: event.target.value })} />
                        </label>
                        <button type="button" className="icon-text danger" disabled={!editable} onClick={() => removeContentBlock(index, blockIndex)}>
                          <Trash2 size={16} aria-hidden="true" />
                          {t("editor.deleteContent")}
                        </button>
                      </div>
                      <label className="field">
                        <span>{t("editor.chineseContent")}</span>
                        <textarea readOnly={!editable} value={block.text} onChange={(event) => updateContentBlock(index, blockIndex, { text: event.target.value })} />
                      </label>
                      <label className="field">
                        <span>{t("editor.scaffold")}</span>
                        <textarea
                          value={block.scaffolding_text}
                          readOnly={!editable}
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
                      readOnly={!editable}
                      onChange={(event) => updateMedia(index, "image_prompt", event.target.value)}
                    />
                  </label>
                  <div className="compact-grid">
                    <label className="field">
                      <span>{t("editor.audioText")}</span>
                    <input readOnly={!editable} value={slide.media_requirements.audio_text ?? ""} onChange={(event) => updateMedia(index, "audio_text", event.target.value)} />
                    </label>
                    <label className="field">
                      <span>{t("editor.videoPrompt")}</span>
                      <input
                        readOnly={!editable}
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
                      disabled={!editable}
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
                                disabled={!editable}
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
                              <input disabled={!editable} value={component.title} onChange={(event) => updateComponent(index, componentIndex, { title: event.target.value })} />
                            </label>
                          </div>
                          <button type="button" className="icon-text danger" disabled={!editable} onClick={() => removeComponent(index, componentIndex)}>
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
        <SpecItem label={t("spec.quality")} value={qualityPolicySummary(quality, t)} />
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
          <details className="artifact-group" key={group.name}>
            <summary><span>{group.name}</span><small>{group.items.length}</small></summary>
            <ul>
              {group.items.map((item) => (
                <li className={item.exists ? "exists" : "missing"} key={item.path}>
                  <span>{item.exists ? "✓" : "!"}</span>
                  <code>{item.path}</code>
                  <small>{artifactMeta(item)}</small>
                </li>
              ))}
            </ul>
          </details>
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
  canGenerate,
  canValidate,
  onGenerate,
  onCopy,
  onValidate
}: {
  project: ProjectState | null;
  agentPackage: AgentPackage | null;
  validation: AgentValidation | null;
  copied: boolean;
  busy: boolean;
  canGenerate: boolean;
  canValidate: boolean;
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
        <button type="button" className="secondary" disabled={!project || busy || !canGenerate} onClick={onGenerate}>
          <FileUp size={16} aria-hidden="true" />
          {t("agent.generate")}
        </button>
        <button type="button" className="secondary" disabled={!agentPackage || busy} onClick={onCopy}>
          <Clipboard size={16} aria-hidden="true" />
          {copied ? t("agent.copied") : t("agent.copy")}
        </button>
        <button type="button" className="primary" disabled={!project || busy || !canValidate} onClick={onValidate}>
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
          <strong>{t("agent.validation", { state: gateStateLabel(validation.state, t) })}</strong>
          <ValidationList title={t("agent.blocking")} items={localizeMessages(validation.blocking, t)} empty={t("agent.blocking.empty")} />
          <ValidationList title={t("agent.warnings")} items={localizeMessages(validation.warnings, t)} empty={t("agent.warnings.empty")} />
          <ValidationList title={t("agent.passed")} items={localizeMessages(validation.passed, t)} empty={t("agent.passed.empty")} />
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
          {items.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>{empty}</p>
      )}
    </section>
  );
}

function StateFirstSummaryView({ summary }: { summary: StateFirstTeacherSummary | null }) {
  const { t } = useI18n();
  if (!summary) return <EmptyState text={t("design.summaryEmpty")} />;
  const goals = arrayLength(summary.learning_state_plan?.learning_goals ?? summary.learning_state_plan?.goals);
  const states = arrayLength(summary.learning_state_plan?.states);
  const evidence = arrayLength(summary.evidence_plan?.evidence_specs);
  const activities = arrayLength(summary.activity_plan?.activities);
  const alignmentState = typeof summary.evidence_alignment?.state === "string" ? summary.evidence_alignment.state : "not_run";
  return (
    <section className="state-first-summary" aria-label={t("design.summaryTitle")}>
      <div className="summary-heading">
        <strong>{t("design.summaryTitle")}</strong>
        <span>{t("design.alignment", { state: gateStateLabel(alignmentState, t) })}</span>
      </div>
      <div className="summary-metrics">
        <span><strong>{states}</strong>{t("design.states")}</span>
        <span><strong>{goals}</strong>{t("design.goals")}</span>
        <span><strong>{evidence}</strong>{t("design.evidenceItems")}</span>
        <span><strong>{activities}</strong>{t("design.activities")}</span>
      </div>
      {(summary.blockers.length > 0 || summary.warnings.length > 0) && (
        <div className="summary-issues">
          {localizeMessages(summary.blockers, t).map((item, index) => <p className="error-text" key={`blocker-${item}-${index}`}>{item}</p>)}
          {localizeMessages(summary.warnings, t).map((item, index) => <p className="warning-text" key={`warning-${item}-${index}`}>{item}</p>)}
        </div>
      )}
    </section>
  );
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

const BACKEND_MESSAGE_KEYS: Array<[RegExp, string]> = [
  [/official Provider Registry could not be reached/i, "provider.registry.refreshFetchError"],
  [/Provider Registry response (?:failed schema validation|was not valid JSON|had an invalid shape|exceeded the size limit)/i, "provider.registry.refreshInvalidError"],
  [/Provider Registry refresh source is not an approved/i, "provider.registry.refreshSourceError"],
  [/blueprint artifact is missing/i, "status.blocker.blueprintMissing"],
  [/generate a lesson blueprint first|blueprint.*missing/i, "status.blocker.blueprintMissing"],
  [/render artifact is missing/i, "status.blocker.renderMissing"],
  [/media artifact is stale|regenerate media before rendering/i, "status.blocker.mediaStale"],
  [/source material|uploaded source file/i, "status.blocker.sourceMissing"],
  [/asset manifest/i, "status.blocker.mediaMissing"],
  [/evidence alignment/i, "status.blocker.evidenceAlignment"],
  [/presentation readiness/i, "status.blocker.readiness"],
  [/presentation binding/i, "status.blocker.binding"],
  [/quality gate/i, "status.blocker.quality"],
  [/credentials or required configuration are missing|configure a bridge token/i, "status.blocker.providerConfig"],
  [/codex agent bridge.*no live agent heartbeat/i, "status.blocker.codexBridgeDisconnected"],
  [/not implemented.*capability|not implemented in the production media pipeline/i, "status.blocker.providerUnavailable"],
  [/ocr engine is not available/i, "status.blocker.ocrUnavailable"],
  [/profile changed|lineage is unknown|upstream stale/i, "status.blocker.stale"],
  [/project changed elsewhere|revision conflict/i, "status.blocker.revision"],
  [/platform .* not supported|platform .* requirement/i, "provider.registry.blocker.platform"],
  [/not enough free disk|disk space/i, "provider.registry.blocker.disk"],
  [/configuration is required|required field .* is missing/i, "provider.registry.blocker.configuration"],
];

function localizeBackendMessage(message: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  const trimmed = message.trim();
  const known = BACKEND_MESSAGE_KEYS.find(([pattern]) => pattern.test(trimmed));
  if (known) return t(known[1]);
  return /[^\x00-\x7F]/.test(trimmed) ? trimmed : t("status.blocker.generic");
}

function localizeMessages(messages: string[], t: (key: string, vars?: Record<string, string | number>) => string): string[] {
  return messages.map((message) => localizeBackendMessage(message, t));
}

function stageStateLabel(state: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  const knownStates = new Set(["not_started", "ready", "running", "completed", "warning", "blocked", "failed", "stale"]);
  return knownStates.has(state) ? t(`status.stage.${state}`) : t("status.stage.unknown");
}

function stageTitleLabel(stageId: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  const step = steps.find((item) => item.id === stageId);
  return step ? t(step.titleKey) : t("status.stage.unknown");
}

function mediaReviewStateLabel(state: string | null | undefined, t: (key: string, vars?: Record<string, string | number>) => string): string {
  switch (state) {
    case "accepted": return t("status.media.accepted");
    case "rejected": return t("status.media.rejected");
    case "fallback_accepted": return t("status.media.fallbackAccepted");
    case "replaced": return t("status.media.replaced");
    case "pending_review": return t("status.media.pendingReview");
    default: return t("status.media.pendingReview");
  }
}

function StageNotice({ stage }: { stage?: StageStatus }) {
  const { t } = useI18n();
  if (!stage || (!stage.blockers.length && !stage.warnings.length && stage.state !== "stale")) return null;
  const stateLabel = stageStateLabel(stage.state, t);
  return (
    <div className={`stage-notice ${stage.state === "warning" ? "warning" : "blocked"}`} role="status">
      <strong>{stateLabel}</strong>
      {localizeMessages(stage.blockers, t).map((item, index) => <span key={`blocker-${item}-${index}`}>{item}</span>)}
      {localizeMessages(stage.warnings, t).map((item, index) => <span key={`warning-${item}-${index}`}>{item}</span>)}
    </div>
  );
}

function WorkflowResolution({
  blockers,
  nextStage,
  activeStage,
  onNavigate,
}: {
  blockers: string[];
  nextStage?: StepId;
  activeStage: StepId;
  onNavigate: (stage: StepId) => void;
}) {
  const { t } = useI18n();
  const messages = localizeMessages(blockers, t);
  const canNavigate = Boolean(nextStage && nextStage !== activeStage);
  if (!messages.length && !canNavigate) return null;
  return (
    <div className="workflow-resolution" role="status">
      <div>
        <strong>{messages.length ? t("export.blocked") : t("status.nextStep", { stage: stageTitleLabel(nextStage!, t) })}</strong>
        {messages.slice(0, 2).map((message) => <span key={message}>{message}</span>)}
      </div>
      {canNavigate && <button type="button" className="secondary small-button" onClick={() => onNavigate(nextStage!)}>{t("status.goResolve")}</button>}
    </div>
  );
}

function MediaReviewPanel({
  projectId,
  manifest,
  busy,
  canReview,
  canReplace,
  canRegenerate,
  onReview,
  onReplace,
  onForceRegenerate,
}: {
  projectId?: string;
  manifest: AssetManifest | null;
  busy: boolean;
  canReview: boolean;
  canReplace: boolean;
  canRegenerate: boolean;
  onReview: (assetId: string, state: string, candidateId?: string) => void;
  onReplace: (assetId: string, file: File) => void;
  onForceRegenerate: () => void;
}) {
  const { t } = useI18n();
  const assets = manifest ? [...manifest.images, ...manifest.audio, ...manifest.video] : [];
  if (!assets.length) return <EmptyState text={t("media.reviewEmpty")} />;
  return (
    <section className="media-review" aria-label={t("media.reviewTitle")}>
      <div className="summary-heading">
        <strong>{t("media.reviewTitle")}</strong>
        <button type="button" className="secondary small-button" disabled={busy || !canRegenerate} onClick={onForceRegenerate}>
          <RefreshCw size={14} aria-hidden="true" />{t("btn.forceRegenerateMedia")}
        </button>
      </div>
      <div className="media-review-list">
        {assets.map((asset) => (
          <MediaReviewCard key={asset.id} projectId={projectId} asset={asset} busy={busy} canReview={canReview} canReplace={canReplace} onReview={onReview} onReplace={onReplace} />
        ))}
      </div>
    </section>
  );
}

function MediaReviewCard({
  projectId,
  asset,
  busy,
  canReview,
  canReplace,
  onReview,
  onReplace,
}: {
  projectId?: string;
  asset: AssetFile;
  busy: boolean;
  canReview: boolean;
  canReplace: boolean;
  onReview: (assetId: string, state: string, candidateId?: string) => void;
  onReplace: (assetId: string, file: File) => void;
}) {
  const { t } = useI18n();
  const assetUrl = projectId && asset.path ? `${import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"}/runtime/projects/${projectId}/${asset.path}` : null;
  return (
    <article className="media-review-card">
      <div className="media-review-preview">
        {asset.kind === "image" && assetUrl ? <img src={assetUrl} alt={asset.prompt || asset.id} /> : <span>{asset.kind.toUpperCase()}</span>}
      </div>
      <div className="media-review-body">
        <div className="media-review-title"><strong>{asset.id}</strong><span>{mediaReviewStateLabel(asset.review_state, t)}</span></div>
        <p>{asset.prompt || asset.text || asset.path}</p>
        <div className="media-review-actions">
          {(asset.candidates ?? []).map((candidate) => (
            <button type="button" className="small-button" key={candidate.id} disabled={busy || !canReview} onClick={() => onReview(asset.id, candidate.source === "fallback" ? "fallback_accepted" : "accepted", candidate.id)}>
              {t("media.acceptCandidate", { source: mediaCandidateSourceLabel(candidate.source, t) })}
            </button>
          ))}
          <button type="button" className="small-button" disabled={busy || !canReview} onClick={() => onReview(asset.id, "rejected")}>{t("media.reject")}</button>
          <label className={`small-button file-button${canReplace ? "" : " disabled"}`} aria-disabled={!canReplace}>
            {t("media.replace")}
            <input type="file" accept="image/png,image/jpeg" disabled={busy || !canReplace} onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onReplace(asset.id, file);
              event.currentTarget.value = "";
            }} />
          </label>
        </div>
      </div>
    </article>
  );
}

function QualityReportView({ project }: { project: ProjectState | null }) {
  const { t } = useI18n();
  const summary = project?.gate_summary;
  const report = project?.quality_report;
  const gates = summary
    ? [
        [t("quality.gate.evidence"), summary.evidence_alignment],
        [t("quality.gate.readiness"), summary.presentation_readiness],
        [t("quality.gate.binding"), summary.presentation_binding],
        [t("quality.gate.quality"), summary.quality_report],
      ] as const
    : [];
  const blocking = report
    ? (safeList(report.blocking).length
      ? safeList(report.blocking)
      : [...safeList(report.resource_errors), ...safeList(report.invalid_interactions)])
    : [];
  const warnings = report
    ? (safeList(report.warnings).length
      ? safeList(report.warnings)
      : [...safeList(report.missing_titles), ...safeList(report.missing_audio), ...safeList(report.missing_images), ...safeList(report.empty_prompts)])
    : [];
  const passed = report
    ? (safeList(report.passed).length
      ? safeList(report.passed)
      : safeList(report.suggestions).length
        ? safeList(report.suggestions)
        : [t("quality.pending")])
    : [];
  const groups = [
    [t("quality.blocking"), blocking, t("quality.blocking.detail")],
    [t("quality.warnings"), warnings, t("quality.warnings.detail")],
    [t("quality.passed"), passed, t("quality.passed.detail")]
  ] as const;
  return (
    <>
      {summary && (
        <section className="gate-summary" aria-label={t("quality.gates") }>
          <div className={`quality-state ${summary.overall_state}`}>
            <strong>{t("quality.title", { state: gateStateLabel(summary.overall_state, t) })}</strong>
            <span>{summary.export_allowed ? t("export.ready") : gateStateLabel(summary.overall_state, t)}</span>
          </div>
          <div className="gate-grid">
            {gates.map(([title, gate]) => (
              <article className={`gate-card ${gate.state}`} key={title}>
                <strong>{title}</strong>
                <span>{gateStateLabel(gate.state, t)}</span>
                {gate.blocking_reasons.length > 0 && <small>{localizeMessages(gate.blocking_reasons, t).join("；")}</small>}
                {gate.warnings.length > 0 && <small>{localizeMessages(gate.warnings, t).join("；")}</small>}
              </article>
            ))}
          </div>
          {!report && <EmptyState text={t("quality.emptyState")} />}
        </section>
      )}
      {report && (
        <>
          <div className={`quality-state ${summary?.quality_report.state === "stale" ? "stale" : report.state}`}>
            <strong>{t("quality.title", { state: gateStateLabel(summary?.quality_report.state ?? report.state, t) })}</strong>
            <span>{report.schema}</span>
          </div>
          <div className="quality-grid">
            {groups.map(([title, items, detail]) => (
              <section className="quality-group" key={title}>
                <h3>{title}</h3>
                <p>{detail}</p>
                {items.length ? (
                  <ul>
                        {localizeMessages(items, t).map((item, index) => (
                          <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{t("quality.empty")}</p>
                )}
              </section>
            ))}
          </div>
        </>
      )}
      {!summary && !report && <EmptyState text={t("quality.emptyState")} />}
    </>
  );
}

function gateStateLabel(state: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (state === "passed" || state === "pass") return t("status.qualityPass");
  if (state === "not_run") return t("status.qualityNotRun");
  if (state === "warning") return t("status.qualityWarning");
  if (state === "running") return t("status.qualityRunning");
  if (state === "blocked" || state === "failed") return t("status.qualityBlocked");
  if (state === "stale") return t("status.qualityStale");
  return t("status.stage.unknown");
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

function qualityPolicySummary(policy: Record<string, unknown>, t: (key: string, vars?: Record<string, string | number>) => string): string {
  const parts = [];
  if (policy.block_on_missing_files) parts.push(t("spec.policy.missingFiles"));
  if (policy.block_on_missing_interaction_answers) parts.push(t("spec.policy.missingAnswers"));
  if (policy.warn_on_placeholder_media) parts.push(t("spec.policy.placeholders"));
  if (policy.allow_forced_export) parts.push(t("spec.policy.forceExport"));
  return parts.join(", ");
}

function mediaCandidateSourceLabel(source: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  switch (source) {
    case "generated": return t("media.source.generated");
    case "fallback": return t("media.source.fallback");
    case "teacher": return t("media.source.teacher");
    default: return t("media.source.generated");
  }
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
