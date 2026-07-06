import { type ChangeEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Clipboard,
  FileUp,
  Image,
  Layers3,
  Loader2,
  MonitorPlay,
  Pencil,
  Play,
  Plus,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import {
  exportUrl,
  forceExportProject,
  generateAgentPackage,
  generateBlueprint,
  generateMedia,
  getComponentRegistry,
  listProjectArtifacts,
  previewUrl,
  renderProject,
  runPipeline,
  saveBlueprint,
  saveProfile,
  uploadProject,
  validateAgentOutput
} from "./api";
import type {
  AgentPackage,
  AgentValidation,
  ArtifactEntry,
  ArtifactTree,
  ComponentConfig,
  ComponentRegistry,
  ContentBlock,
  GenerationMode,
  LessonBlueprint,
  LessonProfile,
  LessonSlide,
  ProjectState,
  SlideComponent
} from "./types";

const languages = ["English", "Arabic", "Russian", "Thai", "Korean", "Japanese", "Vietnamese", "Indonesian"];

const modes: Array<{ value: GenerationMode; title: string; detail: string }> = [
  { value: "faithful", title: "忠实原结构", detail: "保留原页序，轻量增强互动" },
  { value: "guided_redesign", title: "参考原结构", detail: "重排为更完整的课堂活动链条" },
  { value: "reimagined", title: "完全重构", detail: "把原材料作为知识来源重新设计" }
];

const steps = [
  { id: "upload", title: "上传解析", icon: FileUp },
  { id: "profile", title: "课程确认", icon: Settings2 },
  { id: "mode", title: "模式语言", icon: Sparkles },
  { id: "outline", title: "大纲编辑", icon: Layers3 },
  { id: "preview", title: "预览导出", icon: MonitorPlay }
] as const;

type StepId = (typeof steps)[number]["id"];
type PipelineStepStatus = "pending" | "running" | "done" | "error";

const providerStatuses = [
  { label: "LLM Provider", name: "Backend configured", status: "Mock", mode: "Mock" },
  { label: "Image Provider", name: "Placeholder SVG", status: "Mock", mode: "Mock" },
  { label: "TTS Provider", name: "Placeholder tone", status: "Mock", mode: "Mock" },
  { label: "Video Provider", name: "Not connected", status: "Not configured", mode: "Mock" },
  { label: "OCR Provider", name: "Parser fallback", status: "Mock", mode: "Local" }
] as const;

const pipelineStepLabels = ["Spec Lock", "Blueprint", "Media", "Render", "Quality", "Export"] as const;

const emptyProfile: LessonProfile = {
  lesson_title: "",
  subject: "International Chinese",
  learner_level: "Beginner",
  target_students: "International Chinese learners",
  scaffolding_language: "English",
  lesson_type: "New lesson",
  generation_mode: "guided_redesign",
  estimated_duration: "45 minutes"
};

function initialPipelineSteps(): Record<string, PipelineStepStatus> {
  return Object.fromEntries(pipelineStepLabels.map((label) => [label, "pending"])) as Record<string, PipelineStepStatus>;
}

function markPipelineStep(label: string, status: PipelineStepStatus = "running") {
  return (current: Record<string, PipelineStepStatus>) => ({ ...current, [label]: status });
}

function readableError(err: unknown): string {
  const message = err instanceof Error ? err.message : "操作失败，请稍后重试。";
  if (message.toLowerCase().includes("failed to fetch")) {
    return "无法连接后端服务。请确认后端已经启动，然后重试。";
  }
  if (message.includes("Project needs")) {
    return "课件项目信息还不完整。请先上传材料并保存课程信息。";
  }
  return message || "操作失败，请稍后重试。";
}

export function App() {
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
  const [agentPackage, setAgentPackage] = useState<AgentPackage | null>(null);
  const [agentValidation, setAgentValidation] = useState<AgentValidation | null>(null);
  const [agentCopied, setAgentCopied] = useState(false);

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
      .catch((err) => setError(readableError(err)));
  }, []);

  async function refreshArtifacts(projectId: string) {
    try {
      setArtifactTree(await listProjectArtifacts(projectId));
    } catch {
      setArtifactTree(null);
    }
  }

  function updateProject(next: ProjectState) {
    setProject(next);
    if (next.lesson_profile) setProfile(next.lesson_profile);
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
      setError(readableError(err));
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
    setPreviewError("");
    setPreviewLoading(false);
    await run("正在解析课件", () => uploadProject(file), "profile");
  }

  async function handleSaveProfile(nextStep?: StepId) {
    if (!project) return;
    await run(
      "正在保存课程信息",
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
    setBusy("正在一键生成课件");
    setError("");
    setPipelineSteps(markPipelineStep("Spec Lock"));
    try {
      const saved = await saveProfile(project.project_id, profile);
      setConfirmedProfileProjectId(saved.project_id);
      updateProject(saved);
      setPipelineSteps(markPipelineStep("Spec Lock", "done"));
      setPipelineSteps(markPipelineStep("Blueprint"));
      const next = await runPipeline(project.project_id);
      const nextSteps = initialPipelineSteps();
      for (const label of pipelineStepLabels) {
        nextSteps[label] = "done";
      }
      if (next.quality_report?.state === "blocked") {
        nextSteps.Export = "error";
      }
      setPipelineSteps(nextSteps);
      updateProject(next);
      setActiveStep("preview");
    } catch (err) {
      setError(readableError(err));
      setPipelineSteps((current) => {
        const next = { ...current };
        const running = pipelineStepLabels.find((label) => next[label] === "running");
        if (running) next[running] = "error";
        return next;
      });
    } finally {
      setBusy("");
    }
  }

  async function handleForceExport() {
    if (!project) return;
    setBusy("正在强制导出课件");
    setError("");
    try {
      const blob = await forceExportProject(project.project_id);
      downloadBlob(blob, `HanClassStudio_Output_${project.project_id}.zip`);
      setProject({ ...project, export_url: project.export_url ?? `/api/projects/${project.project_id}/export` });
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy("");
    }
  }

  async function handleGenerateAgentPackage() {
    if (!project) return;
    setBusy("正在生成 Agent 任务");
    setError("");
    try {
      const next = await generateAgentPackage(project.project_id);
      setAgentPackage(next);
      setAgentValidation(null);
      await refreshArtifacts(project.project_id);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setBusy("");
    }
  }

  async function handleValidateAgentOutput() {
    if (!project) return;
    setBusy("正在校验 Agent 输出");
    setError("");
    try {
      const next = await validateAgentOutput(project.project_id);
      setAgentValidation(next);
      await refreshArtifacts(project.project_id);
    } catch (err) {
      setError(readableError(err));
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
      setError(readableError(err));
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
      <aside className="sidebar" aria-label="HanClassStudio workflow">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            H
          </div>
          <div>
            <strong>HanClassStudio</strong>
            <span>v0.1 local demo</span>
          </div>
        </div>
        <nav className="step-list" aria-label="开发流程">
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
                <span>{step.title}</span>
                {index <= progressIndex && <CheckCircle2 size={16} aria-hidden="true" />}
              </button>
            );
          })}
        </nav>
        <ProviderStatusPanel onOpenSettings={() => setSettingsOpen(true)} />
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">AI 多语言支架式互动课件生成器</p>
            <h1>{profile.lesson_title || "新建中文课件"}</h1>
          </div>
          <div className="status-strip">
            <span>{project?.project_id ? `Project ${project.project_id}` : "No project"}</span>
            <span>{project?.status ?? "ready"}</span>
            <span>{project?.route ? `Route ${project.route}` : "Route pending"}</span>
            <span>{profileConfirmed ? "Profile confirmed" : "Profile pending"}</span>
            <span>{qualityState ? `Quality ${qualityState}` : "Quality pending"}</span>
            <span>{issueCount === 0 ? "QC clear" : `${issueCount} QC issues`}</span>
          </div>
          <div className="top-actions">
            <button type="button" className="secondary" onClick={() => setSettingsOpen(true)}>
              <Settings2 size={18} aria-hidden="true" />
              Model Settings
            </button>
            <button
              type="button"
              className="primary"
              disabled={!canRunPipeline}
              onClick={handleRunFullPipeline}
              title={profileConfirmed ? "Run the full generation pipeline" : "请先保存课程信息"}
            >
              <Sparkles size={18} aria-hidden="true" />
              一键生成课件
            </button>
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
            <PanelHeader icon={<FileUp size={22} />} title="上传课件材料" action="PPTX / PDF" />
            <label className="upload-zone">
              <FileUp size={34} aria-hidden="true" />
              <span>选择 PPTX 或 PDF 文件</span>
              <input type="file" accept=".pptx,.pdf" onChange={handleUpload} />
            </label>
            {project?.source_material && (
              <SourcePreview project={project} />
            )}
          </section>
        )}

        {activeStep === "profile" && (
          <section className="panel">
            <PanelHeader icon={<Settings2 size={22} />} title="课程信息确认" action="Lesson Profile" />
            <ProfileForm profile={profile} onChange={setProfile} />
            <div className="action-row">
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy}
                onClick={() => handleSaveProfile("mode")}
              >
                <Save size={18} aria-hidden="true" />
                保存课程信息
              </button>
            </div>
          </section>
        )}

        {activeStep === "mode" && (
          <section className="panel">
            <PanelHeader icon={<Sparkles size={22} />} title="生成模式与辅助语言" action="Template-guided AI" />
            <fieldset className="field-group">
              <legend>生成模式</legend>
              <div className="segmented-grid">
                {modes.map((mode) => (
                  <button
                    key={mode.value}
                    type="button"
                    className={profile.generation_mode === mode.value ? "selected" : ""}
                    onClick={() => setProfile({ ...profile, generation_mode: mode.value })}
                  >
                    <strong>{mode.title}</strong>
                    <span>{mode.detail}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <label className="field">
              <span>辅助语言</span>
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
                    "正在生成课程大纲",
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
                生成大纲
              </button>
            </div>
          </section>
        )}

        {activeStep === "outline" && (
          <section className="panel">
            <PanelHeader icon={<Pencil size={22} />} title="可视化编辑大纲" action={`${blueprint?.slides.length ?? 0} slides`} />
            {blueprint ? (
              <BlueprintEditor blueprint={blueprint} componentRegistry={componentRegistry} componentOptions={componentOptions} onChange={setBlueprint} />
            ) : (
              <EmptyState text="生成大纲后会显示逐页课件结构。" />
            )}
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={!project || !blueprint || !!busy}
                onClick={() => project && blueprint && run("正在保存大纲", () => saveBlueprint(project.project_id, blueprint))}
              >
                <Save size={18} aria-hidden="true" />
                保存大纲
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !blueprint || !!busy}
                onClick={() =>
                  project &&
                  blueprint &&
                  run(
                    "正在生成媒体资源",
                    async () => {
                      await saveBlueprint(project.project_id, blueprint);
                      return generateMedia(project.project_id);
                    },
                    "preview"
                  )
                }
              >
                <Image size={18} aria-hidden="true" />
                生成媒体
              </button>
            </div>
          </section>
        )}

        {activeStep === "preview" && (
          <section className="panel preview-panel">
            <PanelHeader icon={<MonitorPlay size={22} />} title="最终预览与导出" action={project?.preview_url ? "Rendered" : "Ready"} />
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy}
                onClick={() => project && run("正在生成媒体", () => generateMedia(project.project_id))}
              >
                <Image size={18} aria-hidden="true" />
                重新生成媒体
              </button>
              <button
                type="button"
                className="primary"
                disabled={!project || !!busy}
                onClick={() => {
                  setPreviewError("");
                  setPreviewLoading(true);
                  project && run("正在重新渲染课件", () => renderProject(project.project_id));
                }}
              >
                <MonitorPlay size={18} aria-hidden="true" />
                重新渲染
              </button>
              <a
                className={project?.export_url && !qualityBlocked ? "download-link" : "download-link disabled"}
                href={project?.export_url && !qualityBlocked ? exportUrl(project.project_id) : undefined}
                aria-disabled={!project?.export_url || qualityBlocked}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                {qualityBlocked ? "质量阻断" : project?.export_url ? "下载 ZIP" : "等待导出"}
              </a>
              <button
                type="button"
                className="secondary"
                disabled={!project || !!busy || !qualityBlocked}
                onClick={handleForceExport}
              >
                <ArrowDownToLine size={18} aria-hidden="true" />
                强制导出
              </button>
            </div>
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
                <span>导出包已生成：</span>
                <a href={exportUrl(project.project_id)}>HanClassStudio_Output_*.zip</a>
              </div>
            )}
            {previewUrl(project?.preview_url) ? (
              <div className="preview-frame-wrap">
                {previewLoading && (
                  <div className="preview-state">
                    <Loader2 size={18} aria-hidden="true" />
                    正在加载课件预览...
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
                    setPreviewError("课件预览加载失败。请重新渲染 HTML 后再试。");
                  }}
                />
              </div>
            ) : (
              <EmptyState text="渲染后会显示离线 HTML 课件预览。" />
            )}
          </section>
        )}
      </main>
      {settingsOpen && <ModelSettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

function ProviderStatusPanel({ onOpenSettings }: { onOpenSettings: () => void }) {
  return (
    <section className="provider-status" aria-label="当前模型服务状态">
      <div className="provider-status-header">
        <div>
          <strong>模型服务状态</strong>
          <span>当前环境状态</span>
        </div>
        <button type="button" onClick={onOpenSettings} aria-label="打开模型设置">
          <Settings2 size={17} aria-hidden="true" />
        </button>
      </div>
      <div className="provider-list">
        {providerStatuses.map((provider) => (
          <article className="provider-row" key={provider.label}>
            <div>
              <strong>{provider.label}</strong>
              <span>{provider.name}</span>
            </div>
            <div className="provider-meta">
              <span>{provider.status}</span>
              <span>{provider.mode}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function PipelineStatus({ steps }: { steps: Record<string, PipelineStepStatus> }) {
  const hasActivity = pipelineStepLabels.some((label) => steps[label] !== "pending");
  if (!hasActivity) return null;
  return (
    <section className="pipeline-status" aria-label="一键生成课件运行状态">
      {pipelineStepLabels.map((label) => (
        <div className={`pipeline-step ${steps[label]}`} key={label}>
          <span aria-hidden="true">{steps[label] === "done" ? <CheckCircle2 size={15} /> : steps[label] === "running" ? <Loader2 size={15} /> : steps[label] === "error" ? <X size={15} /> : null}</span>
          <strong>{label}</strong>
        </div>
      ))}
    </section>
  );
}

function ModelSettingsModal({ onClose }: { onClose: () => void }) {
  const fields = [
    ["LLM endpoint", "Configured in backend console"],
    ["LLM model name", "Backend-managed model"],
    ["Image generation endpoint", "Future image provider endpoint"],
    ["TTS endpoint", "Future speech provider endpoint"],
    ["OCR engine", "Future OCR provider"],
    ["Video generation endpoint", "Future video provider endpoint"]
  ] as const;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="modelSettingsTitle">
        <header>
          <div>
            <p className="eyebrow">Environment configuration</p>
            <h2 id="modelSettingsTitle">Model Settings</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="关闭模型设置">
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <p className="settings-note">
          当前版本由后端环境变量或后端控制台配置模型服务。前端设置将在后续版本开放，这里只预留产品入口。
        </p>
        <div className="settings-placeholder-grid">
          {fields.map(([label, placeholder]) => (
            <label className="field" key={label}>
              <span>{label}</span>
              <input disabled placeholder={placeholder} />
            </label>
          ))}
        </div>
        <div className="action-row">
          <button type="button" className="primary" onClick={onClose}>
            知道了
          </button>
        </div>
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

function ProfileForm({ profile, onChange }: { profile: LessonProfile; onChange: (profile: LessonProfile) => void }) {
  function set<K extends keyof LessonProfile>(key: K, value: LessonProfile[K]) {
    onChange({ ...profile, [key]: value });
  }
  return (
    <div className="form-grid">
      <label className="field">
        <span>课程标题</span>
        <input value={profile.lesson_title} onChange={(event) => set("lesson_title", event.target.value)} />
      </label>
      <label className="field">
        <span>学习者水平</span>
        <input value={profile.learner_level} onChange={(event) => set("learner_level", event.target.value)} />
      </label>
      <label className="field">
        <span>教学对象</span>
        <input value={profile.target_students} onChange={(event) => set("target_students", event.target.value)} />
      </label>
      <label className="field">
        <span>课型</span>
        <input value={profile.lesson_type} onChange={(event) => set("lesson_type", event.target.value)} />
      </label>
      <label className="field">
        <span>预计时长</span>
        <input value={profile.estimated_duration} onChange={(event) => set("estimated_duration", event.target.value)} />
      </label>
      <label className="field">
        <span>学科</span>
        <input value={profile.subject} onChange={(event) => set("subject", event.target.value)} />
      </label>
    </div>
  );
}

function SourcePreview({ project }: { project: ProjectState }) {
  const source = project.source_material;
  if (!source) return null;
  return (
    <div className="source-list">
      {source.pages.map((page) => (
        <article className="source-item" key={page.page_number}>
          <span>{page.page_number}</span>
          <div>
            <h3>{page.title}</h3>
            <p>{page.text_blocks.map((block) => block.text).join(" · ").slice(0, 180)}</p>
          </div>
          <small>{page.images.length} images</small>
        </article>
      ))}
    </div>
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
                <strong>{slide.title || `第 ${slide.id} 页`}</strong>
                <small>{slide.slide_type || "Slide"} · {slide.layout_variant || "layout"}</small>
              </span>
              {isExpanded ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
            </button>
            {isExpanded && (
              <div className="outline-fields">
                <label className="field">
                  <span>页面标题</span>
                  <input value={slide.title} onChange={(event) => updateSlide(index, { title: event.target.value })} />
                </label>
                <div className="compact-grid">
                  <label className="field">
                    <span>页面类型</span>
                    <input value={slide.slide_type} onChange={(event) => updateSlide(index, { slide_type: event.target.value })} />
                  </label>
                  <label className="field">
                    <span>布局变体</span>
                    <input value={slide.layout_variant} onChange={(event) => updateSlide(index, { layout_variant: event.target.value })} />
                  </label>
                </div>

                <section className="editor-section">
                  <div className="editor-section-header">
                    <h3>Content blocks</h3>
                    <button type="button" className="secondary small-button" onClick={() => addContentBlock(index)}>
                      <Plus size={16} aria-hidden="true" />
                      添加内容
                    </button>
                  </div>
                  {blocks.map((block, blockIndex) => (
                    <div className="content-block-editor" key={block.id || blockIndex}>
                      <div className="compact-grid">
                        <label className="field">
                          <span>Block type</span>
                          <input value={block.block_type} onChange={(event) => updateContentBlock(index, blockIndex, { block_type: event.target.value })} />
                        </label>
                        <button type="button" className="icon-text danger" onClick={() => removeContentBlock(index, blockIndex)}>
                          <Trash2 size={16} aria-hidden="true" />
                          删除内容
                        </button>
                      </div>
                      <label className="field">
                        <span>中文内容</span>
                        <textarea value={block.text} onChange={(event) => updateContentBlock(index, blockIndex, { text: event.target.value })} />
                      </label>
                      <label className="field">
                        <span>Scaffolding / bilingual explanation</span>
                        <textarea
                          value={block.scaffolding_text}
                          onChange={(event) => updateContentBlock(index, blockIndex, { scaffolding_text: event.target.value })}
                        />
                      </label>
                    </div>
                  ))}
                </section>

                <section className="editor-section">
                  <h3>Media requirements</h3>
                  <label className="field">
                    <span>Media prompt</span>
                    <textarea
                      value={slide.media_requirements.image_prompt ?? ""}
                      onChange={(event) => updateMedia(index, "image_prompt", event.target.value)}
                    />
                  </label>
                  <div className="compact-grid">
                    <label className="field">
                      <span>Audio text</span>
                      <input value={slide.media_requirements.audio_text ?? ""} onChange={(event) => updateMedia(index, "audio_text", event.target.value)} />
                    </label>
                    <label className="field">
                      <span>Video scene prompt</span>
                      <input
                        value={slide.media_requirements.video_scene_prompt ?? ""}
                        onChange={(event) => updateMedia(index, "video_scene_prompt", event.target.value)}
                      />
                    </label>
                  </div>
                </section>

                <section className="editor-section">
                  <div className="editor-section-header">
                    <h3>Components</h3>
                    <select
                      aria-label={`给第 ${slide.id} 页添加组件`}
                      defaultValue=""
                      onChange={(event) => {
                        if (!event.target.value) return;
                        addComponent(index, event.target.value);
                        event.target.value = "";
                      }}
                    >
                      <option value="" disabled>
                        {componentOptions.length ? "添加组件" : "加载组件中"}
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
                              <span>Component type</span>
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
                              <span>Component title</span>
                              <input value={component.title} onChange={(event) => updateComponent(index, componentIndex, { title: event.target.value })} />
                            </label>
                          </div>
                          <button type="button" className="icon-text danger" onClick={() => removeComponent(index, componentIndex)}>
                            <Trash2 size={16} aria-hidden="true" />
                            删除组件
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted-text">这一页暂未添加互动组件。</p>
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
  if (!specLock) return <EmptyState text="生成大纲或一键生成后会显示 Spec Lock 摘要。" />;
  const lesson = objectValue(specLock.lesson);
  const templates = objectValue(specLock.templates);
  const components = objectValue(specLock.components);
  const quality = objectValue(specLock.quality);
  const allowed = arrayValue(components.allowed).join(", ") || "无";
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>Spec Lock Summary</h3>
        <span>{stringValue(specLock.schema)}</span>
      </div>
      <div className="spec-grid">
        <SpecItem label="Route" value={stringValue(specLock.route)} />
        <SpecItem label="Generation mode" value={stringValue(specLock.generation_mode)} />
        <SpecItem label="Scaffolding" value={stringValue(lesson.scaffolding_language)} />
        <SpecItem label="Runtime template" value={stringValue(templates.runtime)} />
        <SpecItem label="Allowed components" value={allowed} />
        <SpecItem label="Quality policy" value={qualityPolicySummary(quality)} />
      </div>
    </section>
  );
}

function SpecItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="spec-item">
      <span>{label}</span>
      <strong>{value || "pending"}</strong>
    </div>
  );
}

function ArtifactInspector({ tree }: { tree: ArtifactTree | null }) {
  if (!tree) return <EmptyState text="Artifact Inspector 会在项目创建后显示。" />;
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>Artifact Inspector</h3>
        <span>Project {tree.project_id}</span>
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
  return (
    <section className="dev-panel">
      <div className="dev-panel-header">
        <h3>Agent Handoff</h3>
        <span>{agentPackage ? "Ready for Claude Code / Codex" : "Generate task package"}</span>
      </div>
      <div className="agent-actions">
        <button type="button" className="secondary" disabled={!project || busy} onClick={onGenerate}>
          <FileUp size={16} aria-hidden="true" />
          生成 Agent 任务
        </button>
        <button type="button" className="secondary" disabled={!agentPackage || busy} onClick={onCopy}>
          <Clipboard size={16} aria-hidden="true" />
          {copied ? "已复制" : "复制任务文本"}
        </button>
        <button type="button" className="primary" disabled={!project || busy} onClick={onValidate}>
          <CheckCircle2 size={16} aria-hidden="true" />
          Validate Agent Output
        </button>
      </div>
      {agentPackage && (
        <div className="agent-copy">
          <div>
            <span>Task</span>
            <code>{agentPackage.task_path}</code>
          </div>
          <textarea readOnly value={`${agentPackage.task_text}\n\n---\n\n${agentPackage.rules_text}`} />
        </div>
      )}
      {validation && (
        <div className={`agent-validation ${validation.state}`}>
          <strong>Validation: {validation.state}</strong>
          <ValidationList title="Blocking" items={validation.blocking} empty="无阻断项" />
          <ValidationList title="Warnings" items={validation.warnings} empty="无警告" />
          <ValidationList title="Passed" items={validation.passed} empty="暂无通过项" />
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
  const report = project?.quality_report;
  if (!report) return <EmptyState text="质量检查会在渲染后生成。" />;
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
      : ["标题、媒体引用和互动配置会在渲染后检查。"];
  const groups = [
    ["Blocking", blocking, "需要先修复，否则普通导出会被阻止。"],
    ["Warnings", warnings, "建议检查，但不一定阻止导出。"],
    ["Passed checks", passed, "当前已经通过或完成的检查。"]
  ] as const;
  return (
    <>
      <div className={`quality-state ${report.state}`}>
        <strong>Quality: {report.state}</strong>
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
              <p>无</p>
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
