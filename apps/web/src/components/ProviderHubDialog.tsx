import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, CheckCircle2, Cloud, Download, ExternalLink, HardDrive, Loader2, RefreshCw, ShieldCheck, X } from "lucide-react";

import {
  cancelProviderHubInstall,
  checkProviderHubHealth,
  deleteOnlineProviderConfig,
  fetchOnlineProviderConfig,
  fetchProviderHub,
  fetchProviderHubInstall,
  fetchProviderHubLatestInstall,
  fetchProviderHubRefresh,
  fetchProviderRuntimeDirectoryAction,
  fetchProviderRuntimeLogs,
  repairProviderRuntime,
  saveOnlineProviderConfig,
  setOnlineProviderEnabled,
  startProviderHubInstall,
  startProviderHubRefresh,
  startProviderRuntime,
  stopProviderRuntime,
  testOnlineProviderConnection,
  uninstallProviderRuntime,
} from "../api";
import { localizedApiError } from "../api-errors";
import { useI18n } from "../i18n";
import { applyProviderHubInstallStart, filterProviderHubItems, hasProviderHubAction, safeExternalProviderUrl, type ProviderHubFilter } from "../state";
import type { ProviderHubCatalog, ProviderHubInstallTask, ProviderHubItem, ProviderRefreshTask, PublicOnlineProviderConfig } from "../types";


const FILTERS: ProviderHubFilter[] = ["all", "online", "offline", "image", "video", "free", "api", "verified", "unverified", "compatible"];
const TERMINAL_TASKS = new Set(["completed", "failed", "cancelled", "partial"]);
const ADVANCED_PROVIDER_COPY: Record<string, { name: string; description: string }> = {
  "provider.llm.deterministic": { name: "offlineBlueprint", description: "offlineBlueprintDescription" },
  "provider.llm.openai_compatible": { name: "compatibleChat", description: "compatibleChatDescription" },
  "provider.llm.ollama": { name: "ollama", description: "ollamaDescription" },
  "provider.llm.lm_studio": { name: "lmStudio", description: "lmStudioDescription" },
  "provider.llm.custom": { name: "customOnline", description: "customOnlineDescription" },
  "provider.llm.codex_chatgpt": { name: "codexLesson", description: "codexLessonDescription" },
  "provider.image.placeholder": { name: "offlineIllustration", description: "offlineIllustrationDescription" },
  "provider.image.experimental_openai_images": { name: "experimentalImages", description: "experimentalImagesDescription" },
  "provider.image.codex_image": { name: "codexImages", description: "codexImagesDescription" },
  "provider.tts.placeholder": { name: "offlineAudio", description: "offlineAudioDescription" },
  "provider.tts.openai_tts": { name: "onlineSpeech", description: "onlineSpeechDescription" },
  "provider.ocr.paddle_ocr": { name: "paddleOcr", description: "paddleOcrDescription" },
  "provider.ocr.tesseract": { name: "tesseract", description: "tesseractDescription" },
  "provider.video.runway": { name: "runway", description: "runwayDescription" },
  "provider.ocr.hcs_mock_ocr": { name: "ocrSandbox", description: "ocrSandboxDescription" },
  "provider.llm.hcs_mock_llm": { name: "llmSandbox", description: "llmSandboxDescription" },
};

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatBytes(value: number): string {
  if (!value) return "0 KB";
  const units = ["KB", "MB", "GB"];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(1)} ${units[unit]}`;
}

function targetHost(value: string): string {
  try {
    return new URL(value).hostname;
  } catch {
    return "";
  }
}

function errorText(error: unknown, t: (key: string) => string, fallback: string): string {
  return localizedApiError(error, t, fallback);
}

export function ProviderHubDialog({ onClose, onOpenSettings }: { onClose: () => void; onOpenSettings: () => void }) {
  const { lang, t } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const mountedRef = useRef(true);
  const pendingMutationRef = useRef(new Set<string>());
  const [hubState, setHubState] = useState<{ catalog: ProviderHubCatalog | null; installTasks: Record<string, ProviderHubInstallTask> }>({ catalog: null, installTasks: {} });
  const { catalog, installTasks } = hubState;
  const [filter, setFilter] = useState<ProviderHubFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshTask, setRefreshTask] = useState<ProviderRefreshTask | null>(null);
  const [pendingMutationIds, setPendingMutationIds] = useState<Set<string>>(new Set());
  const [configOpen, setConfigOpen] = useState(false);
  const [onlineConfig, setOnlineConfig] = useState<PublicOnlineProviderConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState("https://api.openai.com/v1");
  const [model, setModel] = useState("gpt-image-2");
  const [configBusy, setConfigBusy] = useState(false);
  const [runtimeLogs, setRuntimeLogs] = useState<Record<string, { install: string[]; runtime: string[] }>>({});
  const [runtimeNotices, setRuntimeNotices] = useState<Record<string, string>>({});

  async function reload(): Promise<void> {
    const next = await fetchProviderHub();
    const recovered = await Promise.all(next.providers
      .filter((item) => item.status === "installing")
      .map(async (item) => {
        try {
          return [item.id, await fetchProviderHubLatestInstall(item.id)] as const;
        } catch {
          return null;
        }
      }));
    if (mountedRef.current) setHubState((current) => ({
      catalog: next,
      installTasks: {
        ...current.installTasks,
        ...Object.fromEntries(recovered.filter((item): item is readonly [string, ProviderHubInstallTask] => item !== null)),
      },
    }));
  }

  function beginMutation(packageId: string): boolean {
    if (pendingMutationRef.current.has(packageId)) return false;
    pendingMutationRef.current.add(packageId);
    setPendingMutationIds((current) => new Set(current).add(packageId));
    return true;
  }

  function endMutation(packageId: string): void {
    pendingMutationRef.current.delete(packageId);
    setPendingMutationIds((current) => {
      const next = new Set(current);
      next.delete(packageId);
      return next;
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    void reload().catch((nextError) => setError(errorText(nextError, t, t("provider.hub.error")))).finally(() => setLoading(false));
    return () => {
      mountedRef.current = false;
      if (dialog?.open) dialog.close();
      restoreFocusRef.current?.focus();
    };
  }, []);

  const providers = useMemo(() => filterProviderHubItems(catalog?.providers ?? [], filter), [catalog, filter]);
  const recommended = providers.filter((item) => item.recommended);
  const managed = providers.filter((item) => !item.recommended && (item.installed || item.configured || item.ready || item.status === "failed" || item.status === "update_available"));
  const available = providers.filter((item) => !item.recommended && !managed.includes(item));

  async function refresh(): Promise<void> {
    if (refreshTask && !TERMINAL_TASKS.has(refreshTask.state)) return;
    setError("");
    try {
      let task = await startProviderHubRefresh();
      setRefreshTask(task);
      const deadline = Date.now() + 60_000;
      while (!TERMINAL_TASKS.has(task.state)) {
        if (Date.now() >= deadline) throw new Error(t("provider.hub.refreshTimeout"));
        await wait(180);
        task = await fetchProviderHubRefresh(task.task_id);
        if (!mountedRef.current) return;
        setRefreshTask(task);
      }
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.refreshFailed")));
    }
  }

  async function mutateRuntime(item: ProviderHubItem, operation: "install" | "repair" | "uninstall"): Promise<void> {
    if (operation === "repair" && !window.confirm(t("provider.hub.runtimeRepairConfirm"))) return;
    if (operation === "uninstall" && !window.confirm(t("provider.hub.runtimeUninstallConfirm"))) return;
    if (!beginMutation(item.id)) return;
    setError("");
    try {
      const started = operation === "repair"
        ? await repairProviderRuntime(item.id)
        : operation === "uninstall"
          ? await uninstallProviderRuntime(item.id)
          : await startProviderHubInstall(item.id);
      let task = started.task;
      setHubState((current) => applyProviderHubInstallStart(current.catalog, current.installTasks, started));
      endMutation(item.id);
      const deadline = Date.now() + (item.id === "hcs.comfyui-runtime" ? 60 * 60_000 : 60_000);
      while (!TERMINAL_TASKS.has(task.state)) {
        if (Date.now() >= deadline) throw new Error(t("provider.hub.installTimeout"));
        await wait(120);
        task = await fetchProviderHubInstall(task.task_id);
        if (!mountedRef.current) return;
        setHubState((current) => ({ ...current, installTasks: { ...current.installTasks, [item.id]: task } }));
      }
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.installFailed")));
      try {
        await reload();
        endMutation(item.id);
      } catch {
        // Keep the old install/repair action disabled until an authoritative
        // snapshot can resolve an ambiguous start response.
      }
    }
  }

  async function install(item: ProviderHubItem): Promise<void> {
    return mutateRuntime(item, "install");
  }

  async function runtimeLifecycle(item: ProviderHubItem, action: "start" | "stop" | "force-stop"): Promise<void> {
    if (!beginMutation(item.id)) return;
    setError("");
    try {
      if (action === "start") await startProviderRuntime(item.id);
      else await stopProviderRuntime(item.id, action === "force-stop");
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t(`provider.hub.runtime${action === "start" ? "Start" : "Stop"}Failed`)));
      await reload().catch(() => undefined);
    } finally {
      endMutation(item.id);
    }
  }

  async function showRuntimeLogs(item: ProviderHubItem): Promise<void> {
    setError("");
    try {
      const next = await fetchProviderRuntimeLogs(item.id);
      setRuntimeLogs((current) => ({ ...current, [item.id]: { install: next.install, runtime: next.runtime } }));
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.runtimeLogsFailed")));
    }
  }

  async function requestRuntimeDirectory(item: ProviderHubItem): Promise<void> {
    setError("");
    try {
      await fetchProviderRuntimeDirectoryAction(item.id);
      setRuntimeNotices((current) => ({ ...current, [item.id]: t("provider.hub.runtimeDirectoryNotice") }));
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.runtimeDirectoryFailed")));
    }
  }

  async function cancel(item: ProviderHubItem): Promise<void> {
    const task = installTasks[item.id];
    if (!task) return;
    try {
      const next = await cancelProviderHubInstall(task.task_id);
      setHubState((current) => applyProviderHubInstallStart(current.catalog, current.installTasks, next));
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.cancelFailed")));
    }
  }

  async function health(item: ProviderHubItem): Promise<void> {
    setError("");
    try {
      await checkProviderHubHealth(item.id);
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.healthFailed")));
      await reload().catch(() => undefined);
    }
  }

  async function openOnlineConfig(): Promise<void> {
    setConfigOpen(true);
    setConfigBusy(true);
    setError("");
    try {
      const current = await fetchOnlineProviderConfig("openai_images");
      setOnlineConfig(current);
      setEndpoint(current.endpoint);
      setModel(current.model);
      setApiKey("");
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.configFailed")));
    } finally {
      setConfigBusy(false);
    }
  }

  async function saveConfig(event: FormEvent): Promise<void> {
    event.preventDefault();
    setConfigBusy(true);
    setError("");
    try {
      const next = await saveOnlineProviderConfig("openai_images", { api_key: apiKey || undefined, endpoint, model });
      setOnlineConfig(next);
      setApiKey("");
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.configFailed")));
    } finally {
      setConfigBusy(false);
    }
  }

  async function testConnection(): Promise<void> {
    setConfigBusy(true);
    setError("");
    try {
      await testOnlineProviderConnection("openai_images");
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.testFailed")));
      await reload().catch(() => undefined);
    } finally {
      setConfigBusy(false);
    }
  }

  async function removeConfig(): Promise<void> {
    setConfigBusy(true);
    try {
      const next = await deleteOnlineProviderConfig("openai_images");
      setOnlineConfig(next);
      setApiKey("");
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.deleteFailed")));
    } finally {
      setConfigBusy(false);
    }
  }

  async function toggleOnline(item: ProviderHubItem, enabled: boolean): Promise<void> {
    try {
      await setOnlineProviderEnabled(item.provider_id, enabled);
      await reload();
    } catch (nextError) {
      setError(errorText(nextError, t, t("provider.hub.configFailed")));
    }
  }

  function renderCard(item: ProviderHubItem) {
    const task = installTasks[item.id];
    const projectUrl = safeExternalProviderUrl(item.source_links.project_url ?? item.source_links.official_website_url);
    const apiUrl = safeExternalProviderUrl(item.source_links.api_application_url);
    const licenseUrl = safeExternalProviderUrl(item.license.url ?? item.source_links.license_url);
    const taskErrorKey = task?.error ? `provider.hub.errorCode.${task.error.code}` : "";
    const localizedTaskError = task?.error ? t(taskErrorKey) : "";
    const sourceLinks = [
      { label: t("provider.hub.source.website"), url: safeExternalProviderUrl(item.source_links.official_website_url) },
      { label: t("provider.hub.source.project"), url: projectUrl },
      { label: t("provider.hub.source.apiDocs"), url: safeExternalProviderUrl(item.source_links.api_docs_url) },
      { label: t("provider.hub.source.pricing"), url: safeExternalProviderUrl(item.source_links.pricing_url) },
      { label: t("provider.hub.source.terms"), url: safeExternalProviderUrl(item.source_links.terms_url) },
      { label: t("provider.hub.source.privacy"), url: safeExternalProviderUrl(item.source_links.privacy_url) },
      { label: t("provider.hub.source.model"), url: safeExternalProviderUrl(item.source_links.model_url) },
    ].filter((entry): entry is { label: string; url: string } => Boolean(entry.url));
    const copy = lang === "zh" ? ADVANCED_PROVIDER_COPY[item.id] : undefined;
    const displayName = copy ? t(`provider.hub.advancedProvider.${copy.name}`) : item.name;
    const displayDescription = copy ? t(`provider.hub.advancedProvider.${copy.description}`) : item.description;
    const logs = runtimeLogs[item.id];
    const runtimeNotice = runtimeNotices[item.id];
    return (
      <article className={`provider-hub-card status-${item.status}`} key={item.id}>
        <header>
          <div className="provider-hub-card-icon" aria-hidden="true">{item.runs_locally ? <HardDrive size={20} /> : <Cloud size={20} />}</div>
          <div>
            <h4>{displayName}</h4>
            <p>{displayDescription}</p>
          </div>
          <span className={`provider-hub-status status-${item.status}`}>{t(`provider.hub.status.${item.status}`)}</span>
        </header>
        <div className="provider-hub-badges" aria-label={t("provider.hub.summaryFacts")}>
          <span>{t(`provider.hub.trust.${item.trust_level}`)}</span>
          <span>{item.runs_locally ? t("provider.hub.local") : t("provider.hub.online")}</span>
          <span>{item.requires_api_key ? t("provider.hub.apiRequired") : t("provider.hub.noApiRequired")}</span>
          <span>{item.uploads_data ? t("provider.hub.uploadsData") : t("provider.hub.dataLocal")}</span>
          <span>{t(`provider.hub.compatibility.${item.compatible}`)}</span>
        </div>
        {task && (
          <section className={`provider-hub-task task-${task.state}`} aria-live="polite" aria-label={t("provider.hub.installProgress")}>
            <div><strong>{t(`provider.hub.phase.${task.phase}`)}</strong><span>{task.progress}%</span></div>
            <progress max={100} value={task.progress}>{task.progress}%</progress>
            {task.total_bytes > 0 && <p>{formatBytes(task.downloaded_bytes)} / {formatBytes(task.total_bytes)}</p>}
            {task.total_bytes > 0 && <details className="provider-hub-task-technical"><summary>{t("provider.hub.technicalProgress")}</summary><span>{task.downloaded_bytes} B / {task.total_bytes} B</span></details>}
            {task.error && <p className="provider-hub-error-detail">{localizedTaskError === taskErrorKey ? task.error.message : localizedTaskError}</p>}
          </section>
        )}
        {item.runtime_details && (
          <section className="provider-hub-runtime-summary" aria-label={t("provider.hub.runtimeSummary")}>
            <p><strong>{t("provider.hub.runtimeBoundary")}</strong> {item.runtime_details.no_model_message}</p>
            <p>{t("provider.hub.runtimeDownload", { size: formatBytes(item.runtime_details.estimated_download_bytes) })}</p>
            <p>{t("provider.hub.runtimePlatform", { support: item.runtime_details.platform_support })}</p>
            {item.runtime_details.modified && <p className="provider-hub-warning"><AlertTriangle size={16} aria-hidden="true" />{t("provider.hub.runtimeModified")}</p>}
            <p className="provider-hub-phase2c">{t("provider.hub.runtimeNextStep")}</p>
          </section>
        )}
        {runtimeNotice && <p className="provider-hub-runtime-notice" role="status">{runtimeNotice}</p>}
        {logs && (
          <details className="provider-hub-runtime-logs" open>
            <summary>{t("provider.hub.runtimeLogs")}</summary>
            <pre>{[...logs.install, ...logs.runtime].join("\n") || t("provider.hub.runtimeLogsEmpty")}</pre>
          </details>
        )}
        {!item.license.clear && <p className="provider-hub-warning"><AlertTriangle size={16} aria-hidden="true" />{t("provider.hub.licenseUnknown")}</p>}
        <div className="action-row provider-hub-actions">
          {hasProviderHubAction(item, "install") && <button type="button" className="primary" disabled={pendingMutationIds.has(item.id) || Boolean(task && !TERMINAL_TASKS.has(task.state))} onClick={() => void install(item)}><Download size={16} />{t("provider.hub.install")}</button>}
          {hasProviderHubAction(item, "repair") && <button type="button" className="primary" disabled={pendingMutationIds.has(item.id) || Boolean(task && !TERMINAL_TASKS.has(task.state))} onClick={() => void install(item)}>{t("provider.hub.repair")}</button>}
          {hasProviderHubAction(item, "install_runtime") && <button type="button" className="primary" disabled={pendingMutationIds.has(item.id)} onClick={() => void mutateRuntime(item, "install")}><Download size={16} />{t("provider.hub.runtimeInstall")}</button>}
          {hasProviderHubAction(item, "start_runtime") && <button type="button" className="primary" disabled={pendingMutationIds.has(item.id)} onClick={() => void runtimeLifecycle(item, "start")}>{t("provider.hub.runtimeStart")}</button>}
          {hasProviderHubAction(item, "stop_runtime") && <button type="button" className="secondary" disabled={pendingMutationIds.has(item.id)} onClick={() => void runtimeLifecycle(item, "stop")}>{t("provider.hub.runtimeStop")}</button>}
          {hasProviderHubAction(item, "force_stop_runtime") && <button type="button" className="danger-button" disabled={pendingMutationIds.has(item.id)} onClick={() => void runtimeLifecycle(item, "force-stop")}>{t("provider.hub.runtimeForceStop")}</button>}
          {hasProviderHubAction(item, "repair_runtime") && <button type="button" className="secondary" disabled={pendingMutationIds.has(item.id)} onClick={() => void mutateRuntime(item, "repair")}>{t("provider.hub.runtimeRepair")}</button>}
          {hasProviderHubAction(item, "uninstall_runtime") && <button type="button" className="danger-button" disabled={pendingMutationIds.has(item.id)} onClick={() => void mutateRuntime(item, "uninstall")}>{t("provider.hub.runtimeUninstall")}</button>}
          {hasProviderHubAction(item, "cancel_install") && task && !TERMINAL_TASKS.has(task.state) && <button type="button" className="secondary" disabled={!task.cancellable || task.cancel_requested} onClick={() => void cancel(item)}>{t("provider.hub.cancel")}</button>}
          {hasProviderHubAction(item, "configure") && <button type="button" className="primary" onClick={() => item.id === "hcs.online-image-high-quality" ? void openOnlineConfig() : (onClose(), onOpenSettings())}>{t("provider.hub.configure")}</button>}
          {hasProviderHubAction(item, "test_connection") && item.id === "hcs.online-image-high-quality" && <button type="button" className="secondary" disabled={configBusy} onClick={() => void testConnection()}>{t("provider.hub.test")}</button>}
          {hasProviderHubAction(item, "check_health") && <button type="button" className="secondary" onClick={() => void health(item)}>{t("provider.hub.health")}</button>}
          {hasProviderHubAction(item, "check_runtime") && <button type="button" className="secondary" disabled={pendingMutationIds.has(item.id)} onClick={() => void health(item)}>{t("provider.hub.runtimeCheck")}</button>}
          {hasProviderHubAction(item, "view_runtime_logs") && <button type="button" className="secondary" onClick={() => void showRuntimeLogs(item)}>{t("provider.hub.runtimeViewLogs")}</button>}
          {hasProviderHubAction(item, "open_runtime_directory") && <button type="button" className="secondary" onClick={() => void requestRuntimeDirectory(item)}>{t("provider.hub.runtimeDirectory")}</button>}
          {hasProviderHubAction(item, "disable") && item.id === "hcs.online-image-high-quality" && <button type="button" className="secondary" onClick={() => void toggleOnline(item, false)}>{t("provider.hub.disable")}</button>}
          {hasProviderHubAction(item, "enable") && item.id === "hcs.online-image-high-quality" && <button type="button" className="secondary" onClick={() => void toggleOnline(item, true)}>{t("provider.hub.enable")}</button>}
          {projectUrl && hasProviderHubAction(item, "open_project") && <a className="secondary button-link" href={projectUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />{t("provider.hub.project")} · {targetHost(projectUrl)}</a>}
          {apiUrl && hasProviderHubAction(item, "open_api_application") && <a className="secondary button-link" href={apiUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />{t("provider.hub.applyApi")} · {targetHost(apiUrl)}</a>}
        </div>
        <details className="provider-hub-details">
          <summary>{t("provider.hub.advanced")}</summary>
          <dl>
            {copy && <div><dt>{t("provider.hub.originalProvider")}</dt><dd>{item.name}</dd></div>}
            {copy && <div><dt>{t("provider.hub.originalDescription")}</dt><dd>{item.description}</dd></div>}
            <div><dt>{t("provider.hub.type")}</dt><dd>{item.provider_type}</dd></div>
            <div><dt>{t("provider.hub.version")}</dt><dd>{item.version ?? "—"} · {item.update_channel}</dd></div>
            {item.publisher && <div><dt>{t("provider.hub.publisher")}</dt><dd>{item.publisher}</dd></div>}
            {item.runtime_details && <div><dt>{t("provider.hub.runtimeCommit")}</dt><dd>{item.runtime_details.source_commit}</dd></div>}
            <div><dt>{t("provider.hub.capabilities")}</dt><dd>{item.capabilities.join(", ")}</dd></div>
            <div><dt>{t("provider.hub.license")}</dt><dd>{licenseUrl ? <a href={licenseUrl} target="_blank" rel="noopener noreferrer">{item.license.name ?? t("provider.hub.licenseUnknownShort")} · {targetHost(licenseUrl)}</a> : item.license.name ?? t("provider.hub.licenseUnknownShort")}</dd></div>
            <div><dt>{t("provider.hub.registrySource")}</dt><dd>{item.registry_source}</dd></div>
            {item.last_health_check_at && <div><dt>{t("provider.hub.lastHealthCheck")}</dt><dd>{new Date(item.last_health_check_at).toLocaleString()}</dd></div>}
            <div><dt>{t("provider.hub.redistribution")}</dt><dd>{item.redistributed_by_hanclassstudio ? t("common.yes") : t("common.no")}</dd></div>
            <div><dt>{t("provider.hub.thirdPartyCode")}</dt><dd>{item.third_party_executable_code ? t("common.yes") : t("common.no")}</dd></div>
          </dl>
          {sourceLinks.length > 0 && <div className="provider-hub-source-links">{sourceLinks.map((source) => <a key={`${source.label}:${source.url}`} href={source.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />{source.label} · {targetHost(source.url)}</a>)}</div>}
          {item.capability_package && (
            <div className="provider-hub-domain-tree">
              <strong>{item.capability_package.name}</strong>
              {item.capability_package.runtime && <span>Runtime · {item.capability_package.runtime.name} {item.capability_package.runtime.version}</span>}
              {item.capability_package.model_packages.map((modelPackage) => <span key={modelPackage.id}>Model Package · {modelPackage.name} · {modelPackage.format}</span>)}
              {item.capability_package.workflow_packs.map((workflow) => <span key={workflow.id}>Workflow Pack · {workflow.name} {workflow.version}</span>)}
              <span>Health Check · {item.capability_package.healthcheck}</span>
            </div>
          )}
          {item.id === "hcs.comfyui-runtime" && <p className="provider-hub-runtime-notice">{t("provider.hub.runtimeAttribution")}</p>}
          {item.technical_error && <pre>{JSON.stringify(item.technical_error, null, 2)}</pre>}
        </details>
      </article>
    );
  }

  const refreshing = Boolean(refreshTask && !TERMINAL_TASKS.has(refreshTask.state));

  return (
    <dialog ref={dialogRef} className="provider-hub-dialog" aria-labelledby="providerHubTitle" aria-describedby="providerHubDescription" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <section className="provider-hub-shell">
        <header className="provider-hub-header">
          <div>
            <p className="eyebrow">{t("provider.hub.eyebrow")}</p>
            <h2 id="providerHubTitle">{t("provider.hub.title")}</h2>
            <p id="providerHubDescription">{t("provider.hub.description")}</p>
            {catalog?.last_refresh_at && <p className="provider-hub-last-refresh">{t("provider.registry.lastRefreshed", { time: new Date(catalog.last_refresh_at).toLocaleString() })}</p>}
          </div>
          <div className="provider-hub-header-actions">
            <button type="button" className="secondary" disabled={refreshing} onClick={() => void refresh()}>
              <RefreshCw size={16} className={refreshing ? "spin" : ""} />
              {refreshing ? t("provider.hub.refreshing") : t("provider.hub.refresh")}
            </button>
            <button type="button" className="icon-button" aria-label={t("provider.hub.close")} onClick={onClose}><X size={20} /></button>
          </div>
        </header>

        {error && <div className="notice error" role="alert">{error}</div>}
        {refreshTask && TERMINAL_TASKS.has(refreshTask.state) && (
          <section className={`provider-hub-refresh-summary ${refreshTask.state}`} role="status" aria-live="polite">
            <strong>{refreshTask.state === "partial" ? t("provider.hub.refreshPartial") : refreshTask.state === "completed" ? t("provider.hub.refreshComplete") : t("provider.hub.refreshFailed")}</strong>
            <span>{t("provider.hub.refreshCounts", { added: refreshTask.summary.added, updated: refreshTask.summary.updated, unchanged: refreshTask.summary.unchanged, failed: refreshTask.summary.failed_sources })}</span>
            <ul>{refreshTask.summary.sources.map((source) => <li key={source.source_id}><span>{source.source_id}</span> · {source.message}</li>)}</ul>
          </section>
        )}

        {catalog && (
          <section className="provider-hub-hardware" aria-labelledby="providerHardwareTitle">
            <ShieldCheck size={20} aria-hidden="true" />
            <div><strong id="providerHardwareTitle">{t("provider.hub.hardware")}</strong><span>{catalog.hardware.operating_system} · {catalog.hardware.architecture} · {t(`provider.hub.compatibility.${catalog.hardware.status}`)}</span></div>
            <p>{catalog.hardware.reasons.join(" ")} {t("provider.hub.noSpeedEstimate")}</p>
          </section>
        )}

        <div className="provider-hub-filters" role="group" aria-label={t("provider.hub.filters")}>
          {FILTERS.map((value) => <button type="button" key={value} className={filter === value ? "active" : ""} aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(`provider.hub.filter.${value}`)}</button>)}
        </div>

        {configOpen && (
          <form className="provider-hub-config" onSubmit={(event) => void saveConfig(event)} aria-labelledby="providerHubConfigTitle">
            <header><h3 id="providerHubConfigTitle">{t("provider.hub.onlineConfig")}</h3><button type="button" className="icon-button" aria-label={t("provider.hub.closeConfig")} onClick={() => setConfigOpen(false)}><X size={18} /></button></header>
            <label className="field"><span>{t("provider.hub.apiKey")}</span><input type="password" value={apiKey} placeholder={onlineConfig?.api_key_present ? t("provider.hub.secretStored") : ""} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" /></label>
            <p className="provider-hub-recommended-model">{t("provider.hub.recommendedModel", { model: "gpt-image-2" })}</p>
            <details className="provider-hub-config-advanced">
              <summary>{t("provider.hub.advancedSettings")}</summary>
              <div>
                <label className="field"><span>{t("provider.hub.endpointFriendly")}</span><input type="url" required value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label>
                <label className="field"><span>{t("provider.hub.customModel")}</span><input required value={model} onChange={(event) => setModel(event.target.value)} /></label>
              </div>
            </details>
            <p className="provider-hub-secret-notice">{t("provider.hub.secretStorageNotice")}</p>
            <div className="action-row">
              <button type="submit" className="primary" disabled={configBusy}>{configBusy ? t("provider.hub.saving") : t("provider.hub.save")}</button>
              {onlineConfig?.api_key_present && <button type="button" className="secondary" disabled={configBusy} onClick={() => void testConnection()}>{t("provider.hub.test")}</button>}
              {onlineConfig?.api_key_present && <button type="button" className="danger-button" disabled={configBusy} onClick={() => void removeConfig()}>{t("provider.hub.delete")}</button>}
            </div>
          </form>
        )}

        {loading ? <div className="provider-hub-loading"><Loader2 className="spin" /><span>{t("provider.hub.loading")}</span></div> : (
          <div className="provider-hub-content">
            <section aria-labelledby="providerRecommendedTitle"><h3 id="providerRecommendedTitle">{t("provider.hub.recommended")}</h3><div className="provider-hub-grid">{recommended.map(renderCard)}</div></section>
            {(managed.length > 0 || available.length > 0) && (
              <details className="provider-hub-advanced-services">
                <summary>{t("provider.hub.advancedServices", { count: managed.length + available.length })}</summary>
                <p>{t("provider.hub.advancedServicesDescription")}</p>
                {managed.length > 0 && <section aria-labelledby="providerManagedTitle"><h3 id="providerManagedTitle">{t("provider.hub.managedAdvanced")}</h3><div className="provider-hub-grid">{managed.map(renderCard)}</div></section>}
                {available.length > 0 && <section aria-labelledby="providerAvailableTitle"><h3 id="providerAvailableTitle">{t("provider.hub.availableAdvanced")}</h3><div className="provider-hub-grid">{available.map(renderCard)}</div></section>}
              </details>
            )}
            {providers.length === 0 && <p>{t("provider.hub.empty")}</p>}
          </div>
        )}
        <footer className="provider-hub-footer"><CheckCircle2 size={17} /><span>{t("provider.hub.safetyFooter")}</span></footer>
      </section>
    </dialog>
  );
}
