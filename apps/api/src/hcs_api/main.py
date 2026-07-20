from __future__ import annotations

import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import generate_agent_package, validate_agent_output
from .agents import infer_profile
from .asset_review import apply_review, render_review_page, replace_with_teacher_image
from .components import load_component_registry
from .codex_bridge import (
    CodexBridgeActionRequired,
    CodexBridgeError,
    CodexBridgeHeartbeat,
    CodexBridgeJob,
    authorize_token as authorize_codex_bridge_token,
    complete_blueprint as complete_codex_blueprint,
    complete_image as complete_codex_image,
    get_job as get_codex_bridge_job,
    heartbeat as codex_bridge_heartbeat,
    pending_or_completed_jobs as codex_bridge_jobs,
)
from .models import (
    AgentPackage,
    AgentValidation,
    AssetFile,
    AssetManifest,
    ArtifactTree,
    AudioProviderSettings,
    EditablePptxExportResponse,
    ImageProviderSettings,
    LLMProviderSettings,
    LessonBlueprint,
    LessonProfile,
    MediaReviewAction,
    OCRProviderSettings,
    ProjectState,
    PublicCapabilityConfig,
    PublicProviderSection,
    PublicProviderSettings,
    ProjectSummary,
    ProviderCapabilityDescriptor,
    ProviderSettings,
    SourceMaterial,
    StateFirstTeacherSummary,
    VideoProviderSettings,
)
from .parser import parse_source
from .source_understanding import OCRPolicy, get_engine_status
from .providers import ProviderError, provider_capability_catalog
from .provider_registry import (
    InstallConfirmRequest,
    ProviderConfigureRequest,
    ProviderInstallLog,
    ProviderRegistryError,
    RegistryCatalogResponse,
    RegistryRefreshResponse,
    InstallPrepareResponse,
    InstallResult,
    audit_events,
    confirm_install,
    configure_install,
    install_logs,
    prepare_install,
    refresh_registry,
    registry_status,
    retry_install,
    rollback_install,
    _redact_sensitive_text,
)
from .provider_hub import (
    OnlineProviderConfigRequest,
    ProviderHubCatalog,
    ProviderHubError,
    ProviderInstallStartResponse,
    ProviderInstallTask,
    ProviderRefreshTask,
    PublicOnlineProviderConfig,
    cancel_fixture_install,
    check_local_health,
    delete_online_config,
    detect_hardware,
    get_install_task,
    get_refresh_task,
    hub_catalog,
    save_online_config,
    set_online_disabled,
    start_fixture_install,
    start_refresh,
    test_online_connection,
)
from .pipeline import generate_lesson_blueprint, generate_project_media
from .pipeline import render_and_check, run_full_pipeline, write_blueprint_artifacts, write_spec_artifacts
from .pptx_exporter import export_editable_pptx
from .storage import (
    PROJECTS_DIR,
    RUNTIME_DIR,
    bump_project_revision,
    project_revision,
    clear_stale_state,
    create_project_id,
    ensure_project,
    ensure_runtime,
    get_artifact_tree,
    latest_export_path,
    invalidate_downstream,
    list_project_summaries,
    get_project_state,
    read_json,
    read_model,
    read_provider_settings,
    _render_artifact_reason,
    set_profile_state,
    write_json,
    write_model,
    write_provider_settings,
    zip_output,
)


ensure_runtime()

app = FastAPI(title="HanClassStudio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Only project artifacts are public runtime assets.  Configuration lives beside
# the projects under ``runtime/config`` and must never be exposed by the static
# file server.
app.mount("/runtime/projects", StaticFiles(directory=PROJECTS_DIR), name="runtime-projects")


_VALIDATION_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}
_SAFE_VALIDATION_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_SAFE_VALIDATION_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


def _safe_request_validation_fields(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep schema locations and error types without reflecting request input."""
    fields: list[dict[str, str]] = []
    for error in errors:
        code = str(error.get("type") or "validation_error")
        if not _SAFE_VALIDATION_CODE.fullmatch(code):
            code = "validation_error"
        location: list[str] = []
        for part in error.get("loc", ()):
            if part in _VALIDATION_LOCATION_PREFIXES and not location:
                continue
            if isinstance(part, int):
                location.append(str(part))
            elif isinstance(part, str) and _SAFE_VALIDATION_FIELD.fullmatch(part):
                location.append(part)
            else:
                location.append("field")
        if code == "extra_forbidden" and location:
            location[-1] = "unexpected_field"
        message = {
            "missing": "A required value is missing.",
            "string_too_long": "The value is too long.",
            "string_too_short": "The value is too short.",
            "extra_forbidden": "An unexpected field was submitted.",
        }.get(code, "The submitted value is invalid.")
        fields.append({
            "path": ".".join(location) or "request",
            "code": code,
            "message": message,
        })
    return fields


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
    # Never serialize ``error`` itself: Pydantic validation errors contain the
    # original request input, including rejected credentials and endpoints.
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_failed",
                "message": "The submitted request is invalid.",
                "fields": _safe_request_validation_fields(error.errors()),
            }
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={
            "code": "codex_bridge_unauthorized",
            "message": "A Codex bridge bearer token is required.",
        })
    return token.strip()


def _codex_bridge_http_error(error: CodexBridgeError) -> HTTPException:
    status_code = 401 if error.code == "codex_bridge_unauthorized" else 404 if error.code == "codex_bridge_job_not_found" else 400
    return HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message})


def _codex_action_required(error: CodexBridgeActionRequired) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "codex_agent_action_required",
        "capability": "codex_bridge",
        "job_ids": error.job_ids,
        "message": "A connected Codex agent must complete the queued provider jobs, then retry this action.",
    })


@app.post("/api/providers/codex-bridge/heartbeat")
def heartbeat_codex_bridge(
    payload: CodexBridgeHeartbeat,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        return codex_bridge_heartbeat(read_provider_settings(), _bearer_token(authorization), payload.capabilities)
    except CodexBridgeError as error:
        raise _codex_bridge_http_error(error) from error


@app.get("/api/providers/codex-bridge/jobs", response_model=list[CodexBridgeJob])
def list_codex_bridge_jobs(
    state: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> list[CodexBridgeJob]:
    token = _bearer_token(authorization)
    try:
        authorized = authorize_codex_bridge_token(read_provider_settings(), token)
    except CodexBridgeError as error:
        raise _codex_bridge_http_error(error) from error
    if state not in {None, "pending", "completed"}:
        raise HTTPException(status_code=400, detail={"code": "codex_bridge_state_invalid", "message": "Unsupported job state"})
    return [job for job in codex_bridge_jobs(state) if job.capability in authorized]


@app.post("/api/providers/codex-bridge/jobs/{job_id}/complete-blueprint", response_model=CodexBridgeJob)
def submit_codex_blueprint(
    job_id: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> CodexBridgeJob:
    token = _bearer_token(authorization)
    try:
        authorized = authorize_codex_bridge_token(read_provider_settings(), token)
        job = get_codex_bridge_job(job_id)
        if job.capability not in authorized:
            raise CodexBridgeError("codex_bridge_capability_denied", "Token cannot complete this job")
        return complete_codex_blueprint(job, payload)
    except CodexBridgeError as error:
        raise _codex_bridge_http_error(error) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail={
            "code": "codex_bridge_blueprint_invalid",
            "message": str(error),
        }) from error


@app.post("/api/providers/codex-bridge/jobs/{job_id}/complete-image", response_model=CodexBridgeJob)
async def submit_codex_image(
    job_id: str,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> CodexBridgeJob:
    token = _bearer_token(authorization)
    try:
        authorized = authorize_codex_bridge_token(read_provider_settings(), token)
        job = get_codex_bridge_job(job_id)
        if job.capability not in authorized:
            raise CodexBridgeError("codex_bridge_capability_denied", "Token cannot complete this job")
        return complete_codex_image(job, await file.read(), file.content_type or "")
    except CodexBridgeError as error:
        raise _codex_bridge_http_error(error) from error


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="zh-Hans">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HanClassStudio 后端控制台</title>
  <style>
    :root {
      --bg: #f5f8f4;
      --surface: #ffffff;
      --surface-soft: #edf6f2;
      --ink: #223236;
      --muted: #627774;
      --line: #d9e7e1;
      --teal: #087e8b;
      --teal-dark: #075f69;
      --coral: #e65550;
      --gold: #c98604;
      --shadow: 0 18px 44px rgba(22, 49, 54, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100dvh;
      font-family: Inter, "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    a { color: inherit; }
    .shell {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 34px 0 46px;
    }
    .top {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      margin-bottom: 22px;
    }
    .brand {
      display: flex;
      gap: 14px;
      align-items: center;
    }
    .mark {
      width: 52px;
      height: 52px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: var(--teal);
      color: #fff;
      font-weight: 900;
      font-size: 24px;
    }
    .eyebrow {
      margin: 0 0 6px;
      color: var(--teal-dark);
      font-size: 14px;
      font-weight: 800;
    }
    h1 {
      margin: 0;
      font-size: clamp(30px, 4vw, 48px);
      line-height: 1.12;
      letter-spacing: 0;
    }
    .status {
      min-height: 42px;
      display: inline-flex;
      align-items: center;
      gap: 9px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 13px;
      background: var(--surface);
      color: var(--teal-dark);
      font-weight: 800;
      box-shadow: 0 8px 18px rgba(22, 49, 54, 0.08);
      white-space: nowrap;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: #22a06b;
      box-shadow: 0 0 0 4px rgba(34, 160, 107, 0.16);
    }
    .hero {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: clamp(22px, 4vw, 34px);
      margin-bottom: 18px;
    }
    .hero p {
      max-width: 780px;
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.7;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }
    .button {
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border-radius: 8px;
      border: 1px solid var(--line);
      padding: 10px 14px;
      text-decoration: none;
      font-weight: 800;
      background: var(--surface);
    }
    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: #fff;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .card h2 {
      margin: 0 0 10px;
      font-size: 19px;
      letter-spacing: 0;
    }
    .card p,
    .card li {
      color: var(--muted);
      line-height: 1.65;
    }
    .card p,
    .card ul {
      margin: 0;
    }
    .card ul {
      padding-left: 20px;
    }
    .endpoint-list {
      display: grid;
      gap: 9px;
    }
    .settings-panel {
      margin-bottom: 18px;
    }
    .settings-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-top: 14px;
    }
    .provider-card {
      display: grid;
      gap: 12px;
      align-content: start;
      background: #fbfdfb;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .provider-card h3 {
      margin: 0;
      font-size: 17px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }
    input,
    select {
      width: 100%;
      min-height: 44px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      padding: 10px 12px;
      font: inherit;
    }
    .settings-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    .settings-message {
      min-height: 24px;
      color: var(--teal-dark);
      font-weight: 800;
    }
    .endpoint {
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 10px;
      align-items: start;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .endpoint:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .method {
      display: inline-flex;
      justify-content: center;
      border-radius: 8px;
      padding: 5px 8px;
      background: var(--surface-soft);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 900;
    }
    code {
      color: var(--ink);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 14px;
      overflow-wrap: anywhere;
    }
    .footer-note {
      margin-top: 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }
    @media (max-width: 860px) {
      .top { flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
      .settings-grid { grid-template-columns: 1fr; }
      .endpoint { grid-template-columns: 1fr; }
      .actions .button { width: 100%; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="top">
      <div class="brand">
        <div class="mark" aria-hidden="true">H</div>
        <div>
          <p class="eyebrow">HanClassStudio API · v0.1</p>
          <h1>后端控制台</h1>
        </div>
      </div>
      <div class="status"><span class="dot" aria-hidden="true"></span>服务运行中</div>
    </header>

    <section class="hero">
      <h2>面向国际中文教师的 AI 互动课件生成服务</h2>
      <p>
        这里负责上传解析、课程信息保存、课件大纲生成、占位媒体生成、HTML 渲染、
        质量检查和 ZIP 导出。前端工作台负责给教师提供可视化操作界面。
      </p>
      <div class="actions">
        <a class="button primary" href="http://127.0.0.1:5173/">打开前端工作台</a>
        <a class="button" href="/docs">查看 API 文档</a>
        <a class="button" href="/api/health">查看健康检查</a>
      </div>
    </section>

    <section class="grid" aria-label="服务概览">
      <article class="card">
        <h2>当前闭环</h2>
        <ul>
          <li>上传 PPTX / PDF</li>
          <li>生成课程信息与大纲</li>
          <li>生成占位图片和音频</li>
          <li>渲染离线 HTML 课件</li>
          <li>导出 ZIP 课件包</li>
        </ul>
      </article>
      <article class="card">
        <h2>数据文件</h2>
        <ul>
          <li><code>source_material.json</code></li>
          <li><code>lesson_profile.json</code></li>
          <li><code>lesson_blueprint.json</code></li>
          <li><code>asset_manifest.json</code></li>
          <li><code>quality_report.json</code></li>
        </ul>
      </article>
      <article class="card">
        <h2>本地路径</h2>
        <p>
          生成文件保存在 <code>runtime/projects/&lt;project_id&gt;</code>。
          导出的课件可以解压后直接打开 <code>lesson.html</code>。
        </p>
      </article>
    </section>

    <section class="card settings-panel">
      <h2>模型与 API 设置</h2>
      <p>
        在这里配置 LLM、文生图和文生音频模型。当前 v0.1 默认仍可使用占位生成；
        填好后，后续 Provider 接入会直接读取这份本地配置。
      </p>
      <form id="providerSettingsForm">
        <div class="settings-grid">
          <article class="provider-card">
            <h3>LLM API</h3>
            <label>
              Provider
              <select id="llmProvider">
                <option value="">加载 Provider 目录…</option>
              </select>
            </label>
            <label>
              Base URL
              <input id="llmBaseUrl" type="url" placeholder="https://api.openai.com/v1" />
            </label>
            <label>
              API Key
              <input id="llmApiKey" type="password" autocomplete="off" placeholder="sk-..." />
            </label>
            <label>
              Model
              <input id="llmModel" type="text" placeholder="gpt-4.1-mini" />
            </label>
          </article>

          <article class="provider-card">
            <h3>文生图模型</h3>
            <label>
              Provider
              <select id="imageProvider">
                <option value="">加载 Provider 目录…</option>
              </select>
            </label>
            <label>
              Endpoint URL
              <input id="imageEndpointUrl" type="url" placeholder="http://127.0.0.1:8188" />
            </label>
            <label>
              API Key
              <input id="imageApiKey" type="password" autocomplete="off" placeholder="可留空" />
            </label>
            <label>
              Model / Workflow
              <input id="imageModel" type="text" placeholder="placeholder-svg / flux / sd-xl" />
            </label>
          </article>

          <article class="provider-card">
            <h3>文生音频 / TTS</h3>
            <label>
              Provider
              <select id="audioProvider">
                <option value="">加载 Provider 目录…</option>
              </select>
            </label>
            <label>
              Endpoint URL
              <input id="audioEndpointUrl" type="url" placeholder="http://127.0.0.1:7860" />
            </label>
            <label>
              API Key
              <input id="audioApiKey" type="password" autocomplete="off" placeholder="可留空" />
            </label>
            <label>
              Model
              <input id="audioModel" type="text" placeholder="tts-1 / local-voice-model" />
            </label>
            <label>
              Voice
              <input id="audioVoice" type="text" placeholder="alloy / zh-CN-XiaoxiaoNeural" />
            </label>
          </article>
        </div>
        <div class="settings-actions">
          <button class="button primary" type="submit">保存模型设置</button>
          <span class="settings-message" id="settingsMessage" aria-live="polite"></span>
        </div>
      </form>
    </section>

    <section class="card">
      <h2>常用接口</h2>
      <div class="endpoint-list">
        <div class="endpoint"><span class="method">GET</span><code>/api/health</code></div>
        <div class="endpoint"><span class="method">GET</span><code>/api/settings/providers</code></div>
        <div class="endpoint"><span class="method">PUT</span><code>/api/settings/providers</code></div>
        <div class="endpoint"><span class="method">GET</span><code>/api/component-registry</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/upload</code></div>
        <div class="endpoint"><span class="method">GET</span><code>/api/projects/{project_id}</code></div>
        <div class="endpoint"><span class="method">GET</span><code>/api/projects/{project_id}/artifacts</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/agent/package</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/agent/validate</code></div>
        <div class="endpoint"><span class="method">PUT</span><code>/api/projects/{project_id}/profile</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/blueprint</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/media</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/render</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/pipeline</code></div>
        <div class="endpoint"><span class="method">GET</span><code>/api/projects/{project_id}/export</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/export?force=true</code></div>
        <div class="endpoint"><span class="method">POST</span><code>/api/projects/{project_id}/export/pptx-editable?force=false</code></div>
      </div>
    </section>

    <p class="footer-note">
      提示：如果前端工作台打不开，请确认前端开发服务器也已启动：
      <code>npm run dev:web</code>。后端启动命令是 <code>npm run dev:api</code>。
    </p>
  </main>
  <script>
    let loadedSettings = null;
    let providerCatalog = [];
    const fields = {
      llmProvider: document.getElementById("llmProvider"),
      llmBaseUrl: document.getElementById("llmBaseUrl"),
      llmApiKey: document.getElementById("llmApiKey"),
      llmModel: document.getElementById("llmModel"),
      imageProvider: document.getElementById("imageProvider"),
      imageEndpointUrl: document.getElementById("imageEndpointUrl"),
      imageApiKey: document.getElementById("imageApiKey"),
      imageModel: document.getElementById("imageModel"),
      audioProvider: document.getElementById("audioProvider"),
      audioEndpointUrl: document.getElementById("audioEndpointUrl"),
      audioApiKey: document.getElementById("audioApiKey"),
      audioModel: document.getElementById("audioModel"),
      audioVoice: document.getElementById("audioVoice"),
      message: document.getElementById("settingsMessage")
    };

    function setMessage(text, isError = false) {
      fields.message.textContent = text;
      fields.message.style.color = isError ? "var(--coral)" : "var(--teal-dark)";
    }

    function renderProviderOptions(settings) {
      const targets = { llmProvider: "llm", imageProvider: "image", audioProvider: "tts" };
      Object.entries(targets).forEach(([fieldId, capability]) => {
        const select = fields[fieldId];
        const current = settings && settings[capability === "tts" ? "audio" : capability] && settings[capability === "tts" ? "audio" : capability].provider;
        const options = providerCatalog.filter((item) => item.capability === capability && ((item.configurable && item.implemented && item.available) || item.provider_id === current));
        select.replaceChildren(...options.map((item) => {
          const option = document.createElement("option");
          option.value = item.provider_id;
          option.textContent = item.implemented && item.available ? item.display_name : `${item.display_name} (unavailable)`;
          option.disabled = !item.implemented || !item.available;
          return option;
        }));
      });
    }

    function fillSettings(settings) {
      loadedSettings = settings;
      fields.llmProvider.value = settings.llm.provider || "deterministic";
      fields.llmBaseUrl.value = settings.llm.base_url || "";
      fields.llmApiKey.value = "";
      fields.llmApiKey.placeholder = settings.llm.api_key_present ? "已配置（留空保持）" : "sk-...";
      fields.llmModel.value = settings.llm.model || "";
      fields.imageProvider.value = settings.image.provider || "placeholder";
      fields.imageEndpointUrl.value = settings.image.endpoint_url || "";
      fields.imageApiKey.value = "";
      fields.imageApiKey.placeholder = settings.image.api_key_present ? "已配置（留空保持）" : "可留空";
      fields.imageModel.value = settings.image.model || "";
      fields.audioProvider.value = settings.audio.provider || "placeholder";
      fields.audioEndpointUrl.value = settings.audio.endpoint_url || "";
      fields.audioApiKey.value = "";
      fields.audioApiKey.placeholder = settings.audio.api_key_present ? "已配置（留空保持）" : "可留空";
      fields.audioModel.value = settings.audio.model || "";
      fields.audioVoice.value = settings.audio.voice || "";
    }

    function readSettings() {
      const next = {
        ...(loadedSettings || {}),
        llm: {
          provider: fields.llmProvider.value,
          base_url: fields.llmBaseUrl.value.trim(),
          api_key: fields.llmApiKey.value,
          model: fields.llmModel.value.trim()
        },
        image: {
          provider: fields.imageProvider.value,
          endpoint_url: fields.imageEndpointUrl.value.trim(),
          api_key: fields.imageApiKey.value,
          model: fields.imageModel.value.trim()
        },
        audio: {
          provider: fields.audioProvider.value,
          endpoint_url: fields.audioEndpointUrl.value.trim(),
          api_key: fields.audioApiKey.value,
          model: fields.audioModel.value.trim(),
          voice: fields.audioVoice.value.trim()
        }
      };
      next.capabilities = {
        ...((loadedSettings && loadedSettings.capabilities) || {}),
        llm: { providerId: next.llm.provider, values: { base_url: next.llm.base_url, api_key: next.llm.api_key, model: next.llm.model } },
        image: { providerId: next.image.provider, values: { baseUrl: next.image.endpoint_url, apiKey: next.image.api_key, model: next.image.model } },
        tts: { providerId: next.audio.provider, values: { baseUrl: next.audio.endpoint_url, apiKey: next.audio.api_key, model: next.audio.model, voice: next.audio.voice } }
      };
      return next;
    }

    async function loadSettings() {
      try {
        const [settingsResponse, catalogResponse] = await Promise.all([
          fetch("/api/settings/providers"),
          fetch("/api/settings/providers/capabilities")
        ]);
        if (!settingsResponse.ok || !catalogResponse.ok) throw new Error("读取设置失败");
        providerCatalog = await catalogResponse.json();
        const settings = await settingsResponse.json();
        renderProviderOptions(settings);
        fillSettings(settings);
        setMessage("已加载本地模型设置");
      } catch (error) {
        setMessage(error.message || "读取设置失败", true);
      }
    }

    document.getElementById("providerSettingsForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      setMessage("正在保存...");
      try {
        const response = await fetch("/api/settings/providers", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(readSettings())
        });
        if (!response.ok) throw new Error("保存失败");
        fillSettings(await response.json());
        setMessage("模型设置已保存");
      } catch (error) {
        setMessage(error.message || "保存失败", true);
      }
    });

    loadSettings();
  </script>
</body>
</html>"""
    )


def _public_provider_settings(settings: ProviderSettings) -> PublicProviderSettings:
    """Remove credentials before provider settings leave the backend.

    The internal ProviderSettings model is still used by executors and for
    writes.  This boundary is deliberately explicit so adding a new internal
    field cannot accidentally expose it through a response model.
    """

    def section(value: object) -> PublicProviderSection:
        data = value.model_dump(mode="json")
        api_key = str(data.pop("api_key", "") or "")
        return PublicProviderSection(**data, api_key_present=bool(api_key.strip()))

    capabilities: dict[str, PublicCapabilityConfig] = {}
    flat_api_key_present = {
        "llm": bool(str(settings.llm.api_key or "").strip()),
        "image": bool(str(settings.image.api_key or "").strip()),
        "tts": bool(str(settings.audio.api_key or "").strip()),
        "ocr": bool(str(settings.ocr.api_key or "").strip()),
        "video": bool(str(settings.video.api_key or "").strip()),
    }
    raw_capabilities = settings.capabilities if isinstance(settings.capabilities, dict) else {}
    sensitive_keys = re.compile(r"(?i)^(?:api[_-]?key|access[_-]?token|authorization|bearer|password|secret|credential|token)$")
    for capability, raw in raw_capabilities.items():
        if not isinstance(raw, dict) or not raw.get("providerId"):
            continue
        values = raw.get("values") if isinstance(raw.get("values"), dict) else {}
        safe_values = {
            str(key): str(value)
            for key, value in values.items()
            if not sensitive_keys.search(str(key))
        }
        capabilities[str(capability)] = PublicCapabilityConfig(
            providerId=str(raw["providerId"]),
            values=safe_values,
            api_key_present=bool(
                any(sensitive_keys.search(str(key)) and str(value or "").strip() for key, value in values.items())
                or flat_api_key_present.get(str(capability), False)
            ),
        )

    return PublicProviderSettings(
        llm=section(settings.llm),
        image=section(settings.image),
        audio=section(settings.audio),
        ocr=section(settings.ocr),
        video=section(settings.video),
        capabilities=capabilities,
    )


@app.get("/api/settings/providers", response_model=PublicProviderSettings)
def get_provider_settings() -> PublicProviderSettings:
    return _public_provider_settings(read_provider_settings())


@app.get("/api/settings/providers/capabilities", response_model=list[ProviderCapabilityDescriptor])
def get_provider_capabilities() -> list[ProviderCapabilityDescriptor]:
    try:
        return provider_capability_catalog(read_provider_settings())
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error) from error


def _provider_registry_http_error(error: ProviderRegistryError, *, provider_id: str | None = None) -> HTTPException:
    if error.code == "provider_not_registered":
        status = 404
    elif error.code.startswith("provider_persistence_") or error.code == "provider_registry_unavailable":
        status = 503
    elif error.code == "provider_registry_fetch_failed":
        status = 502
    elif error.code.endswith("in_progress") or "transition" in error.code or error.code in {
        "provider_plan_invalid", "provider_plan_expired", "provider_confirmation_invalid", "provider_plan_stale",
        "provider_plan_consumed", "provider_not_ready", "provider_retry_unavailable", "provider_configuration_unavailable", "provider_rollback_unavailable",
    }:
        status = 409
    else:
        status = 400
    detail = {
        "code": error.code,
        "message": _redact_sensitive_text(error.message),
        "blockers": [
            {
                **item,
                "message": _redact_sensitive_text(str(item.get("message", ""))),
            }
            if isinstance(item, dict)
            else item
            for item in error.blockers
        ],
    }
    if provider_id:
        detail["provider_id"] = provider_id
    return HTTPException(status_code=status, detail=detail)


@app.get("/api/providers/registry", response_model=RegistryCatalogResponse)
def get_provider_registry() -> RegistryCatalogResponse:
    """Return trusted registry metadata and backend-owned installation facts."""
    try:
        return registry_status()
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error) from error


@app.post("/api/providers/registry/refresh", response_model=RegistryRefreshResponse)
def refresh_provider_registry() -> RegistryRefreshResponse:
    """Fetch the official Registry after an explicit user refresh action."""
    try:
        return refresh_registry()
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error) from error


@app.get("/api/providers/registry/audit")
def get_provider_audit(provider_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return [event.model_dump(mode="json") for event in audit_events(provider_id)]


@app.get("/api/providers/registry/{provider_id}")
def get_provider_registry_entry(provider_id: str) -> dict:
    try:
        catalog = registry_status()
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error
    for item in catalog.providers:
        if item.entry.provider_id == provider_id:
            return item.model_dump(mode="json")
    raise HTTPException(status_code=404, detail={"code": "provider_not_registered", "provider_id": provider_id})


@app.post("/api/providers/registry/{provider_id}/install/prepare", response_model=InstallPrepareResponse)
def prepare_provider_install(provider_id: str) -> InstallPrepareResponse:
    try:
        return prepare_install(provider_id)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


@app.post("/api/providers/registry/{provider_id}/install/confirm", response_model=InstallResult)
def confirm_provider_install(provider_id: str, payload: InstallConfirmRequest) -> InstallResult:
    try:
        return confirm_install(provider_id, payload)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


@app.post("/api/providers/registry/{provider_id}/configure", response_model=InstallResult)
def configure_provider_install(provider_id: str, payload: ProviderConfigureRequest) -> InstallResult:
    try:
        return configure_install(provider_id, payload)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


@app.post("/api/providers/registry/{provider_id}/install/retry", response_model=InstallPrepareResponse)
def retry_provider_install(provider_id: str) -> InstallPrepareResponse:
    try:
        return retry_install(provider_id)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


@app.post("/api/providers/registry/{provider_id}/rollback", response_model=InstallResult)
def rollback_provider_install(provider_id: str) -> InstallResult:
    try:
        return rollback_install(provider_id)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


@app.get("/api/providers/registry/{provider_id}/install/logs", response_model=list[ProviderInstallLog])
def get_provider_install_logs(provider_id: str) -> list[ProviderInstallLog]:
    try:
        return install_logs(provider_id)
    except ProviderRegistryError as error:
        raise _provider_registry_http_error(error, provider_id=provider_id) from error


def _provider_hub_http_error(error: ProviderHubError) -> HTTPException:
    status_by_code = {
        "task_not_found": 404,
        "task_conflict": 409,
        "network_error": 502,
        "authentication_error": 401,
        "rate_limited": 429,
        "cancelled": 409,
    }
    status = status_by_code.get(error.code, 400)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


@app.get("/api/providers/hub", response_model=ProviderHubCatalog)
def get_provider_hub() -> ProviderHubCatalog:
    """Return the local Hub snapshot; this endpoint never refreshes remote sources."""
    return hub_catalog()


@app.get("/api/providers/hub/hardware")
def get_provider_hardware() -> dict[str, Any]:
    return detect_hardware().model_dump(mode="json")


@app.post("/api/providers/hub/refresh", response_model=ProviderRefreshTask)
def start_provider_hub_refresh() -> ProviderRefreshTask:
    try:
        return start_refresh()
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.get("/api/providers/hub/refresh/{task_id}", response_model=ProviderRefreshTask)
def get_provider_hub_refresh(task_id: str) -> ProviderRefreshTask:
    try:
        return get_refresh_task(task_id)
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.post("/api/providers/hub/packages/{package_id}/install", response_model=ProviderInstallStartResponse)
def install_provider_package(package_id: str) -> ProviderInstallStartResponse:
    try:
        return start_fixture_install(package_id)
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.get("/api/providers/hub/install-tasks/{task_id}", response_model=ProviderInstallTask)
def get_provider_hub_install_task(task_id: str) -> ProviderInstallTask:
    try:
        return get_install_task(task_id)
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.post("/api/providers/hub/install-tasks/{task_id}/cancel", response_model=ProviderInstallTask)
def cancel_provider_hub_install(task_id: str) -> ProviderInstallTask:
    try:
        return cancel_fixture_install(task_id)
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.post("/api/providers/hub/packages/{package_id}/health")
def check_provider_package_health(package_id: str) -> dict[str, Any]:
    try:
        return check_local_health(package_id).model_dump(mode="json")
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.get("/api/providers/hub/online/{provider_id}/configuration", response_model=PublicOnlineProviderConfig)
def get_online_provider_configuration(provider_id: str) -> PublicOnlineProviderConfig:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    from .provider_hub import _online_config

    return _online_config()


@app.put("/api/providers/hub/online/{provider_id}/configuration", response_model=PublicOnlineProviderConfig)
def put_online_provider_configuration(provider_id: str, payload: OnlineProviderConfigRequest) -> PublicOnlineProviderConfig:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    try:
        return save_online_config(payload)
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.delete("/api/providers/hub/online/{provider_id}/configuration", response_model=PublicOnlineProviderConfig)
def remove_online_provider_configuration(provider_id: str) -> PublicOnlineProviderConfig:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    return delete_online_config()


@app.post("/api/providers/hub/online/{provider_id}/test")
def test_online_provider(provider_id: str) -> dict[str, Any]:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    try:
        return test_online_connection().model_dump(mode="json")
    except ProviderHubError as error:
        raise _provider_hub_http_error(error) from error


@app.post("/api/providers/hub/online/{provider_id}/disable")
def disable_online_provider(provider_id: str) -> dict[str, Any]:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    return set_online_disabled(True).model_dump(mode="json")


@app.post("/api/providers/hub/online/{provider_id}/enable")
def enable_online_provider(provider_id: str) -> dict[str, Any]:
    if provider_id != "openai_images":
        raise HTTPException(status_code=404, detail={"code": "provider_not_found", "message": "Provider was not found"})
    return set_online_disabled(False).model_dump(mode="json")


# Frontend provider ids that are cloud-hosted (vs. local runtimes). Used to derive
# deploy_mode when reconstructing the flat settings from the raw capability config.
_CLOUD_PROVIDER_IDS = {
    "openai_compatible", "custom", "openai_images", "experimental_openai_images", "openai_tts", "runway",
}
# OCR provider id -> concrete OCR engine name (None = cloud-only, no local engine yet).
_OCR_PROVIDER_TO_ENGINE = {
    "paddle_ocr": "paddle_ocr",
    "tesseract": "tesseract",
    "azure_doc": None,
}


def _apply_capabilities(settings: ProviderSettings) -> None:
    """Derive the flat image/audio/ocr/video fields from ``settings.capabilities``.

    ``capabilities`` is the raw frontend ``ProviderConfig`` (capability -> {providerId,
    values}) and is the single source of truth. When it is empty (e.g. edited from the
    dev console HTML form), the flat fields are left untouched.
    """
    caps = settings.capabilities or {}
    if not caps:
        return

    llm = caps.get("llm") or {}
    llm_v = llm.get("values", {})
    if llm.get("providerId"):
        settings.llm = LLMProviderSettings(
            provider=llm.get("providerId", ""),
            base_url=llm_v.get("base_url") or llm_v.get("baseUrl") or settings.llm.base_url,
            api_key=llm_v.get("api_key") or llm_v.get("apiKey") or settings.llm.api_key,
            model=llm_v.get("model") or settings.llm.model,
        )

    if "image" in caps:
        img = caps.get("image") or {}
        img_v = img.get("values", {})
        settings.image = ImageProviderSettings(  # type: ignore[name-defined]
            provider=img.get("providerId") or settings.image.provider,
            endpoint_url=img_v.get("endpoint") or img_v.get("baseUrl") or img_v.get("base_url") or settings.image.endpoint_url,
            api_key=img_v.get("apiKey") or img_v.get("api_key") or settings.image.api_key,
            model=img_v.get("model") or img_v.get("deployment") or settings.image.model,
        )

    if "tts" in caps:
        tts = caps.get("tts") or {}
        tts_v = tts.get("values", {})
        settings.audio = AudioProviderSettings(  # type: ignore[name-defined]
            provider=tts.get("providerId") or settings.audio.provider,
            endpoint_url=tts_v.get("endpoint") or tts_v.get("baseUrl") or tts_v.get("base_url") or settings.audio.endpoint_url,
            api_key=tts_v.get("apiKey") or tts_v.get("api_key") or settings.audio.api_key,
            model=tts_v.get("model") or settings.audio.model,
            voice=tts_v.get("voice") or tts_v.get("voiceId") or settings.audio.voice,
        )

    if "ocr" in caps:
        ocr = caps.get("ocr") or {}
        ocr_v = ocr.get("values", {})
        ocr_id = ocr.get("providerId") or settings.ocr.provider
        use_gpu_value = ocr_v.get("useGpu", ocr_v.get("use_gpu"))
        settings.ocr = OCRProviderSettings(
            provider=ocr_id,
            deploy_mode="cloud" if ocr_id in _CLOUD_PROVIDER_IDS else "local",
            api_key=ocr_v.get("apiKey") or ocr_v.get("api_key") or settings.ocr.api_key,
            endpoint_url=ocr_v.get("endpoint") or ocr_v.get("endpoint_url") or settings.ocr.endpoint_url,
            model=ocr_v.get("model") or settings.ocr.model,
            langs=ocr_v.get("langs") or settings.ocr.langs,
            use_gpu=(str(use_gpu_value).lower() == "true") if use_gpu_value is not None else settings.ocr.use_gpu,
        )

    if "video" in caps:
        vid = caps.get("video") or {}
        vid_v = vid.get("values", {})
        vid_id = vid.get("providerId") or settings.video.provider
        settings.video = VideoProviderSettings(
            provider=vid_id,
            deploy_mode="cloud" if vid_id in _CLOUD_PROVIDER_IDS else "local",
            api_key=vid_v.get("apiKey") or vid_v.get("api_key") or settings.video.api_key,
            endpoint_url=vid_v.get("endpoint") or vid_v.get("endpoint_url") or settings.video.endpoint_url,
            model=vid_v.get("model") or settings.video.model,
        )


def _resolve_ocr_engine(force_engine: str | None, settings: ProviderSettings) -> str | None:
    """Pick the OCR engine: an explicit request wins; otherwise fall back to the
    provider the user configured in settings (local engines only)."""
    if force_engine:
        return force_engine
    provider = (settings.ocr.provider or "").strip()
    return _OCR_PROVIDER_TO_ENGINE.get(provider)


@app.put("/api/settings/providers", response_model=PublicProviderSettings)
def save_provider_settings(payload: dict) -> PublicProviderSettings:
    """Merge only submitted settings so one surface cannot erase another."""
    current = read_provider_settings().model_dump(mode="json")
    for section in ("llm", "image", "audio", "ocr", "video"):
        if isinstance(payload.get(section), dict):
            incoming = payload[section]
            merged = {**current.get(section, {}), **incoming}
            if not str(incoming.get("api_key", "")).strip() and str(current.get(section, {}).get("api_key", "")).strip():
                merged["api_key"] = current[section]["api_key"]
            current[section] = merged
    if "capabilities" in payload:
        current["capabilities"] = payload["capabilities"] or {}
    settings = ProviderSettings.model_validate(current)
    _apply_capabilities(settings)
    write_provider_settings(settings)
    return _public_provider_settings(read_provider_settings())


@app.get("/api/component-registry")
def component_registry() -> dict:
    return load_component_registry()


@app.post("/api/projects/upload", response_model=ProjectState)
async def upload_project(file: UploadFile = File(...), engine: str | None = Query(default=None)) -> ProjectState:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pptx", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Only PPTX, PDF and PNG/JPEG files are supported")

    project_id = create_project_id()
    root = ensure_project(project_id)
    upload_path = root / "uploads" / file.filename
    with upload_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    try:
        source = parse_source(
            upload_path, root, file.filename, force_engine=_resolve_ocr_engine(engine, read_provider_settings())
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile = infer_profile(source)
    write_model(project_id, "source_material.json", source)
    write_model(project_id, "lesson_profile.json", profile)
    set_profile_state(project_id, "inferred")
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/ocr", response_model=ProjectState)
def rerun_ocr(project_id: str, engine: str | None = Query(default=None), expected_revision: int | None = Query(default=None)) -> ProjectState:
    """Re-run the OCR / Source Document Understanding layer on the already
    uploaded file (e.g. after a teacher spots a misread, or to force a specific
    engine). Rewrites ``source_material.json`` and the inferred ``lesson_profile``
    and returns the refreshed project state.
    """
    _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    root = ensure_project(project_id)
    uploads = root / "uploads"
    candidates = (
        [p for p in uploads.iterdir() if p.suffix.lower() in {".pptx", ".pdf", ".png", ".jpg", ".jpeg"}]
        if uploads.exists()
        else []
    )
    if not candidates:
        raise HTTPException(status_code=400, detail="No uploaded source file found for this project")
    upload_path = candidates[0]
    try:
        source = parse_source(
            upload_path, root, upload_path.name, force_engine=_resolve_ocr_engine(engine, read_provider_settings())
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = infer_profile(source)
    write_model(project_id, "source_material.json", source)
    write_model(project_id, "lesson_profile.json", profile)
    set_profile_state(project_id, "inferred")
    invalidate_downstream(project_id, "ocr", "OCR was rerun; downstream design and outputs are stale.")
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.get("/api/ocr/status")
def ocr_status() -> dict:
    """Report which OCR engines are available in this deployment and the active
    layered policy. Lets the frontend show teachers what will actually run."""
    return {
        "engines": [s.__dict__ for s in get_engine_status()],
        "policy": asdict(OCRPolicy()),
        "configured_engine": _resolve_ocr_engine(None, read_provider_settings()),
        "recommended_pipeline": [
            "native text layer (PDF/PPTX)",
            "PP-OCRv6 text detection + recognition for scanned pages",
            "Tesseract CPU baseline fallback",
            "PaddleOCR-VL disabled until its backend and provenance merge are validated",
        ],
    }


@app.get("/api/projects", response_model=list[ProjectSummary])
def list_projects(limit: int = Query(default=20, ge=1, le=100)) -> list[ProjectSummary]:
    return list_project_summaries(limit)


@app.get("/api/projects/{project_id}", response_model=ProjectState)
def read_project(project_id: str) -> ProjectState:
    _assert_project(project_id)
    return get_project_state(project_id)


@app.get("/api/projects/{project_id}/artifacts", response_model=ArtifactTree)
def read_project_artifacts(project_id: str) -> ArtifactTree:
    _assert_project(project_id)
    return get_artifact_tree(project_id)


@app.get("/api/projects/{project_id}/design/summary", response_model=StateFirstTeacherSummary)
def read_design_summary(project_id: str) -> StateFirstTeacherSummary:
    _assert_project(project_id)
    allowed_paths = {
        "learning_state_plan": "learning/learning_state_plan.json",
        "evidence_plan": "learning/evidence_plan.json",
        "activity_plan": "learning/activity_plan.json",
        "evidence_alignment": "quality/evidence_alignment_report.json",
    }
    payloads = {key: read_json(project_id, path) for key, path in allowed_paths.items()}
    if not any(value is not None for value in payloads.values()):
        raise HTTPException(status_code=404, detail={
            "code": "state_first_unavailable",
            "message": "Run the teaching design stage before opening its summary.",
        })
    alignment = payloads["evidence_alignment"] if isinstance(payloads["evidence_alignment"], dict) else {}
    blockers = alignment.get("blocking", []) if isinstance(alignment.get("blocking", []), list) else []
    warnings = alignment.get("warnings", []) if isinstance(alignment.get("warnings", []), list) else []
    return StateFirstTeacherSummary(
        project_id=project_id,
        project_revision=get_project_state(project_id).project_revision,
        learning_state_plan=payloads["learning_state_plan"] if isinstance(payloads["learning_state_plan"], dict) else None,
        evidence_plan=payloads["evidence_plan"] if isinstance(payloads["evidence_plan"], dict) else None,
        activity_plan=payloads["activity_plan"] if isinstance(payloads["activity_plan"], dict) else None,
        evidence_alignment=payloads["evidence_alignment"] if isinstance(payloads["evidence_alignment"], dict) else None,
        blockers=[str(item) for item in blockers],
        warnings=[str(item) for item in warnings],
        available_actions=["review_alignment", "generate_blueprint"] if blockers else ["generate_blueprint", "review_alignment"],
    )


@app.post("/api/projects/{project_id}/agent/package", response_model=AgentPackage)
def create_agent_package(project_id: str) -> AgentPackage:
    _assert_project(project_id)
    return generate_agent_package(project_id)


@app.post("/api/projects/{project_id}/agent/validate", response_model=AgentValidation)
def validate_agent_project(project_id: str) -> AgentValidation:
    _assert_project(project_id)
    return validate_agent_output(project_id)


@app.put("/api/projects/{project_id}/profile", response_model=ProjectState)
def save_profile(project_id: str, profile: LessonProfile, expected_revision: int | None = Query(default=None)) -> ProjectState:
    _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    write_model(project_id, "lesson_profile.json", profile)
    set_profile_state(project_id, "confirmed")
    clear_stale_state(project_id, stages={"profile"})
    invalidate_downstream(project_id, "profile", "Confirmed learner profile changed; downstream artifacts need regeneration.")
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/blueprint", response_model=ProjectState)
def generate_blueprint(project_id: str, expected_revision: int | None = Query(default=None)) -> ProjectState:
    _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile"}, action="generate blueprint")
    source = read_model(project_id, "source_material.json", SourceMaterial)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    if not source or not profile:
        raise HTTPException(status_code=400, detail="Project needs source material and lesson profile")
    _assert_llm_provider_supported(read_provider_settings())
    write_spec_artifacts(project_id, source, profile)
    try:
        blueprint, _ = generate_lesson_blueprint(source, profile, read_provider_settings(), project_id=project_id)
    except CodexBridgeActionRequired as exc:
        raise _codex_action_required(exc) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_execution_failed",
                "capability": "llm",
                "provider_id": read_provider_settings().llm.provider,
                "message": str(exc),
            },
        ) from exc
    write_blueprint_artifacts(project_id, blueprint)
    clear_stale_state(project_id, stages={"profile", "design", "presentation"})
    invalidate_downstream(project_id, "blueprint", "Blueprint changed; media, render, quality, and export are stale.")
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.put("/api/projects/{project_id}/blueprint", response_model=ProjectState)
def save_blueprint(project_id: str, blueprint: LessonBlueprint, expected_revision: int | None = Query(default=None)) -> ProjectState:
    _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile"}, action="save blueprint")
    write_blueprint_artifacts(project_id, blueprint)
    clear_stale_state(project_id, stages={"profile", "design", "presentation"})
    invalidate_downstream(project_id, "blueprint", "Blueprint changed; media, render, quality, and export are stale.")
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/media", response_model=ProjectState)
def generate_media(project_id: str, force_regenerate: bool = Query(False), expected_revision: int | None = Query(default=None)) -> ProjectState:
    root = _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile", "design", "presentation"}, action="generate media")
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    if not blueprint:
        raise HTTPException(status_code=400, detail="Generate a lesson blueprint first")
    _assert_media_provider_ready(read_provider_settings())
    invalidate_downstream(project_id, "media", "Media was regenerated; render, quality, and export are stale.")
    settings = read_provider_settings()
    try:
        manifest = generate_project_media(
            root, blueprint, settings, force_regenerate=force_regenerate, strict_provider=True,
        )
    except CodexBridgeActionRequired as exc:
        raise _codex_action_required(exc) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_execution_failed",
                "capability": "image" if settings.image.provider != "placeholder" else "tts",
                "provider_id": settings.image.provider if settings.image.provider != "placeholder" else settings.audio.provider,
                "message": str(exc),
            },
        ) from exc
    write_model(project_id, "asset_manifest.json", manifest)
    write_json(project_id, "assets/data/attribution.json", {"schema": "hanclassstudio.attribution.v1", "items": []})
    clear_stale_state(project_id, stages={"profile", "design", "presentation", "media"})
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.get("/api/projects/{project_id}/media", response_model=AssetManifest)
def read_media_manifest(project_id: str) -> AssetManifest:
    _assert_project(project_id)
    return read_model(project_id, "asset_manifest.json", AssetManifest) or AssetManifest()


@app.get("/api/projects/{project_id}/media/review", response_class=HTMLResponse)
def media_review_page(project_id: str) -> HTMLResponse:
    _assert_project(project_id)
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest) or AssetManifest()
    return HTMLResponse(render_review_page(project_id, manifest))


@app.put("/api/projects/{project_id}/media/{asset_id}/review", response_model=AssetFile)
def review_media(project_id: str, asset_id: str, action: MediaReviewAction, expected_revision: int | None = Query(default=None)) -> AssetFile:
    root = _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile", "design", "presentation"}, action="review media")
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest)
    if not manifest:
        raise HTTPException(status_code=404, detail="Asset manifest not found")
    try:
        asset = apply_review(root, manifest, asset_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_model(project_id, "asset_manifest.json", manifest)
    invalidate_downstream(project_id, "media", "A teacher-reviewed media asset changed; render, quality, and export are stale.")
    clear_stale_state(project_id, stages={"presentation", "media"})
    bump_project_revision(project_id)
    return asset


@app.post("/api/projects/{project_id}/media/{asset_id}/replacement", response_model=AssetFile)
async def replace_media(
    project_id: str, asset_id: str, file: UploadFile = File(...), notes: str = Form(""), expected_revision: int | None = Query(default=None),
) -> AssetFile:
    root = _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile", "design", "presentation"}, action="replace media")
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest)
    if not manifest:
        raise HTTPException(status_code=404, detail="Asset manifest not found")
    try:
        asset = replace_with_teacher_image(
            root, manifest, asset_id, await file.read(), file.content_type or "", notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_model(project_id, "asset_manifest.json", manifest)
    invalidate_downstream(project_id, "media", "A teacher replacement changed media; render, quality, and export are stale.")
    clear_stale_state(project_id, stages={"presentation", "media"})
    bump_project_revision(project_id)
    return asset


@app.post("/api/projects/{project_id}/render", response_model=ProjectState)
def render_project(project_id: str, expected_revision: int | None = Query(default=None)) -> ProjectState:
    root = _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    _assert_upstream_current(project_id, blocked_stages={"profile", "design", "presentation"}, action="render")
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest)
    if not profile or not blueprint:
        raise HTTPException(status_code=400, detail="Project needs profile and blueprint")
    current_stale = set(get_project_state(project_id).stale_state.stale_stages)
    if "media" in current_stale and manifest is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "upstream_stale",
                "action": "render",
                "stale_stages": ["media"],
                "blocking_reasons": ["Media artifact is stale; regenerate media before rendering."],
                "message": "Render is blocked until stale media is regenerated.",
            },
        )
    invalidate_downstream(project_id, "render", "Render was requested; the previous quality and export state is stale.")
    if not manifest:
        settings = read_provider_settings()
        _assert_media_provider_ready(settings)
        try:
            manifest = generate_project_media(root, blueprint, settings, strict_provider=True)
        except CodexBridgeActionRequired as exc:
            raise _codex_action_required(exc) from exc
        except ProviderError as exc:
            capability = "image" if settings.image.provider != "placeholder" else "tts"
            provider_id = settings.image.provider if capability == "image" else settings.audio.provider
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "provider_execution_failed",
                    "capability": capability,
                    "provider_id": provider_id,
                    "message": str(exc),
                },
            ) from exc
        write_model(project_id, "asset_manifest.json", manifest)
    clear_stale_state(project_id, stages={"profile", "design", "presentation", "media"})
    report = render_and_check(project_id, root, profile, blueprint, manifest)
    export_created = False
    # A fresh render replaces the render and quality dependencies.  The
    # delivery marker can be cleared only when all four authoritative gate
    # reports exist; otherwise a handoff render must remain visibly stale until
    # the missing gates are run.
    gate_paths = (
        "quality/evidence_alignment_report.json",
        "quality/presentation_readiness_report.json",
        "presentation/binding_quality_report.json",
        "quality/quality_report.json",
    )
    clear_stale_state(project_id, stages={"render", "quality"})
    if all(read_json(project_id, path) is not None for path in gate_paths):
        clear_stale_state(project_id, stages={"delivery"})
    # Rendering is not itself proof that the complete four-layer export
    # contract passed.  Only the authoritative ProjectState may authorize a
    # current ZIP; missing gate reports remain ``not_run``.
    if get_project_state(project_id).gate_summary.export_allowed:
        zip_output(project_id)
        export_created = True
    clear_stale_state(project_id, stages={"render", "quality", "delivery"} if export_created else {"render", "quality"})
    bump_project_revision(project_id)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/pipeline", response_model=ProjectState)
def run_project_pipeline(project_id: str, expected_revision: int | None = Query(default=None)) -> ProjectState:
    root = _assert_project(project_id)
    _assert_expected_revision(project_id, expected_revision)
    try:
        _assert_llm_provider_supported(read_provider_settings())
        _assert_media_provider_ready(read_provider_settings())
        state = run_full_pipeline(project_id, root, read_provider_settings())
        gate_paths = (
            "quality/evidence_alignment_report.json",
            "quality/presentation_readiness_report.json",
            "presentation/binding_quality_report.json",
            "quality/quality_report.json",
        )
        has_blocked_gate = any(
            isinstance(report, dict) and report.get("state") in {"blocked", "failed"}
            for report in (read_json(project_id, path) for path in gate_paths)
        )
        if not has_blocked_gate:
            clear_stale_state(
                project_id,
                stages={"profile", "design", "presentation", "media", "render", "quality", "delivery"},
            )
        bump_project_revision(project_id)
        return get_project_state(project_id)
    except CodexBridgeActionRequired as exc:
        raise _codex_action_required(exc) from exc
    except ProviderError as exc:
        settings = read_provider_settings()
        capability = "llm" if settings.llm.provider != "deterministic" else "image"
        provider_id = settings.llm.provider if capability == "llm" else settings.image.provider
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_execution_failed",
                "capability": capability,
                "provider_id": provider_id,
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> FileResponse:
    _assert_project(project_id)
    state = get_project_state(project_id)
    if (technical_reason := _technical_export_reason(project_id, state)) is not None:
        raise HTTPException(status_code=409, detail=_export_technical_detail(state, technical_reason))
    if not state.gate_summary.export_allowed:
        raise HTTPException(status_code=409, detail=_export_gate_detail(state, forced=False))
    export_path = latest_export_path(project_id)
    if export_path is None:
        try:
            export_path = zip_output(project_id)
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=_export_technical_detail(state, str(exc))) from exc
        bump_project_revision(project_id)
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/zip",
    )


@app.post("/api/projects/{project_id}/export")
def force_export_project(project_id: str, force: bool = Query(default=False)) -> FileResponse:
    _assert_project(project_id)
    state = get_project_state(project_id)
    if (technical_reason := _technical_export_reason(project_id, state)) is not None:
        raise HTTPException(status_code=409, detail=_export_technical_detail(state, technical_reason))
    if not force and not state.gate_summary.export_allowed:
        raise HTTPException(status_code=409, detail=_export_gate_detail(state, forced=False))
    if force and not state.gate_summary.force_export_allowed:
        raise HTTPException(status_code=409, detail=_export_gate_detail(state, forced=True))
    try:
        export_path = zip_output(project_id, force=force)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=_export_technical_detail(state, str(exc))) from exc
    bump_project_revision(project_id)
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/zip",
    )


@app.post("/api/projects/{project_id}/export/pptx-editable", response_model=EditablePptxExportResponse)
def export_project_editable_pptx(project_id: str, force: bool = Query(default=False), export_mode: str = Query(default="debug")) -> EditablePptxExportResponse:
    _assert_project(project_id)
    current_state = get_project_state(project_id)
    if (technical_reason := _technical_export_reason(project_id, current_state)) is not None:
        raise HTTPException(status_code=409, detail=_export_technical_detail(current_state, technical_reason))
    if not force and not current_state.gate_summary.export_allowed:
        raise HTTPException(status_code=409, detail=_export_gate_detail(current_state, forced=False))
    if force and not current_state.gate_summary.force_export_allowed:
        raise HTTPException(status_code=409, detail=_export_gate_detail(current_state, forced=True))
    try:
        export_path = export_editable_pptx(project_id, force=force, export_mode=export_mode)
    except PermissionError as exc:
        state = get_project_state(project_id)
        raise HTTPException(status_code=409, detail=_export_gate_detail(state, forced=force, message=str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    bump_project_revision(project_id)
    state = get_project_state(project_id)
    # Read classroom quality report for classroom mode
    classroom_report = None
    from .storage import read_model as _read
    from .models import ClassroomQualityReport as _CQR
    try:
        cr = _read(project_id, "quality/classroom_quality_report.json", _CQR)
        classroom_state = cr.state if cr else None
    except Exception:
        classroom_state = None
    return EditablePptxExportResponse(
        filename=export_path.name,
        download_url=f"/runtime/projects/{project_id}/exports/{export_path.name}",
        quality_state=state.quality_state,
        classroom_quality_state=classroom_state,
    )


def _export_gate_detail(state: ProjectState, *, forced: bool, message: str | None = None) -> dict:
    """Return one structured blocker shape for every export surface."""
    summary = state.gate_summary
    reasons = list(summary.blocking_reasons)
    for gate_name in ("evidence_alignment", "presentation_readiness", "presentation_binding", "quality_report"):
        gate = getattr(summary, gate_name)
        if gate.state in {"not_run", "running", "failed", "stale"}:
            reasons.append(f"{gate_name} gate is {gate.state}")
    if not reasons:
        reasons.append("Export prerequisites are not satisfied")
    return {
        "code": "export_gate_blocked",
        "message": message or ("Forced export is unavailable" if forced else "Export is blocked by the project gates"),
        "blocking_reasons": reasons,
        "warnings": summary.warnings,
        "gate_summary": summary.model_dump(mode="json"),
        "force_export_allowed": summary.force_export_allowed,
    }


def _export_technical_detail(state: ProjectState, message: str) -> dict:
    """Return a non-bypassable export blocker for missing/corrupt prerequisites."""
    summary = state.gate_summary
    reasons = list(summary.blocking_reasons)
    if message not in reasons:
        reasons.append(message)
    return {
        "code": "export_technical_blocked",
        "message": message,
        "blocking_reasons": reasons,
        "warnings": summary.warnings,
        "gate_summary": summary.model_dump(mode="json"),
        "force_export_allowed": False,
    }


def _technical_export_reason(project_id: str, state: ProjectState) -> str | None:
    """Return a blocker that a force flag is never allowed to bypass."""
    if not state.artifacts.get("lesson_blueprint"):
        return "Blueprint artifact is missing; export cannot proceed"
    lesson_path = PROJECTS_DIR / project_id / "courseware" / "lesson.html"
    if (reason := _render_artifact_reason(lesson_path)) is not None:
        return f"{reason}; export cannot proceed"
    return None


def _assert_project(project_id: str) -> Path:
    root = PROJECTS_DIR / project_id
    if not root.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return root


def _assert_expected_revision(project_id: str, expected_revision: int | None) -> None:
    """Reject stale client writes while keeping legacy callers compatible."""
    if expected_revision is None:
        return
    actual_revision = project_revision(project_id)
    if expected_revision != actual_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_revision_conflict",
                "project_id": project_id,
                "expected_revision": expected_revision,
                "actual_revision": actual_revision,
                "message": "Project changed elsewhere; refresh before saving again.",
            },
        )


def _assert_upstream_current(project_id: str, *, blocked_stages: set[str], action: str) -> None:
    state = get_project_state(project_id)
    stale_stages = sorted(set(state.stale_state.stale_stages).intersection(blocked_stages))
    if not stale_stages:
        return
    reasons = list(state.stale_state.reasons)
    if not reasons:
        reasons = [f"{stage} is stale" for stage in stale_stages]
    raise HTTPException(
        status_code=409,
        detail={
            "code": "upstream_stale",
            "action": action,
            "stale_stages": stale_stages,
            "blocking_reasons": reasons,
            "message": f"Cannot {action} until upstream stale stages are regenerated.",
        },
    )


def _assert_media_provider_ready(settings: ProviderSettings) -> None:
    selected = {"image": settings.image.provider, "tts": settings.audio.provider}
    catalog = provider_capability_catalog(settings)
    for capability, provider_id in selected.items():
        if not provider_id or provider_id == "placeholder":
            continue
        descriptor = next(
            (item for item in catalog if item.capability == capability and item.provider_id == provider_id),
            None,
        )
        if descriptor is None or not descriptor.implemented or not descriptor.available or not descriptor.configured:
            reason = descriptor.unavailable_reason if descriptor else "Provider is not in the backend capability catalog."
            if descriptor and descriptor.implemented and not descriptor.configured:
                reason = "Provider credentials or required configuration are missing."
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "provider_capability_unavailable",
                    "capability": capability,
                    "provider_id": provider_id,
                    "message": reason,
                },
            )


def _assert_llm_provider_supported(settings: ProviderSettings) -> None:
    provider_id = settings.llm.provider
    descriptor = next(
        (item for item in provider_capability_catalog(settings) if item.capability == "llm" and item.provider_id == provider_id),
        None,
    )
    if descriptor is None or not descriptor.implemented or not descriptor.available or not descriptor.configured:
        reason = descriptor.unavailable_reason if descriptor else "LLM provider is not in the backend capability catalog."
        if descriptor and descriptor.implemented and not descriptor.configured:
            reason = "Provider credentials or required configuration are missing."
        raise HTTPException(
            status_code=409,
            detail={
                "code": "provider_capability_unavailable",
                "capability": "llm",
                "provider_id": provider_id,
                "message": reason,
            },
        )


def _binding_gate_blocked(project_id: str) -> bool:
    report = read_json(project_id, "presentation/binding_quality_report.json") or {}
    return isinstance(report, dict) and report.get("state") == "blocked"


def _alignment_gate_blocked(project_id: str) -> bool:
    report = read_json(project_id, "quality/evidence_alignment_report.json") or {}
    return isinstance(report, dict) and report.get("state") == "blocked"


def _presentation_readiness_blocked(project_id: str) -> bool:
    report = read_json(project_id, "quality/presentation_readiness_report.json") or {}
    return isinstance(report, dict) and report.get("state") == "blocked"
