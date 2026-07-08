from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agent import generate_agent_package, validate_agent_output
from .agents import infer_profile
from .components import load_component_registry
from .models import (
    AgentPackage,
    AgentValidation,
    AssetManifest,
    ArtifactTree,
    EditablePptxExportResponse,
    LessonBlueprint,
    LessonProfile,
    ProjectState,
    ProviderSettings,
    SourceMaterial,
)
from .parser import parse_source
from .pipeline import generate_lesson_blueprint, generate_project_media
from .pipeline import render_and_check, run_full_pipeline, write_blueprint_artifacts, write_spec_artifacts
from .pptx_exporter import export_editable_pptx
from .storage import (
    PROJECTS_DIR,
    RUNTIME_DIR,
    create_project_id,
    ensure_project,
    ensure_runtime,
    get_artifact_tree,
    latest_export_path,
    get_project_state,
    read_model,
    read_provider_settings,
    write_json,
    write_model,
    write_provider_settings,
    zip_output,
)


ensure_runtime()

app = FastAPI(title="HanClassStudio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/runtime", StaticFiles(directory=RUNTIME_DIR), name="runtime")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
                <option value="openai_compatible">OpenAI-compatible</option>
                <option value="ollama">Ollama</option>
                <option value="lm_studio">LM Studio</option>
                <option value="custom">Custom</option>
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
                <option value="placeholder">占位 SVG</option>
                <option value="comfyui">ComfyUI</option>
                <option value="openai_images">OpenAI Images</option>
                <option value="stable_diffusion">Stable Diffusion API</option>
                <option value="custom">Custom</option>
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
                <option value="placeholder">占位音频</option>
                <option value="openai_tts">OpenAI TTS</option>
                <option value="edge_tts">Edge TTS</option>
                <option value="local_tts">Local TTS</option>
                <option value="custom">Custom</option>
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

    function fillSettings(settings) {
      fields.llmProvider.value = settings.llm.provider || "openai_compatible";
      fields.llmBaseUrl.value = settings.llm.base_url || "";
      fields.llmApiKey.value = settings.llm.api_key || "";
      fields.llmModel.value = settings.llm.model || "";
      fields.imageProvider.value = settings.image.provider || "placeholder";
      fields.imageEndpointUrl.value = settings.image.endpoint_url || "";
      fields.imageApiKey.value = settings.image.api_key || "";
      fields.imageModel.value = settings.image.model || "";
      fields.audioProvider.value = settings.audio.provider || "placeholder";
      fields.audioEndpointUrl.value = settings.audio.endpoint_url || "";
      fields.audioApiKey.value = settings.audio.api_key || "";
      fields.audioModel.value = settings.audio.model || "";
      fields.audioVoice.value = settings.audio.voice || "";
    }

    function readSettings() {
      return {
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
    }

    async function loadSettings() {
      try {
        const response = await fetch("/api/settings/providers");
        if (!response.ok) throw new Error("读取设置失败");
        fillSettings(await response.json());
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


@app.get("/api/settings/providers", response_model=ProviderSettings)
def get_provider_settings() -> ProviderSettings:
    return read_provider_settings()


@app.put("/api/settings/providers", response_model=ProviderSettings)
def save_provider_settings(settings: ProviderSettings) -> ProviderSettings:
    write_provider_settings(settings)
    return read_provider_settings()


@app.get("/api/component-registry")
def component_registry() -> dict:
    return load_component_registry()


@app.post("/api/projects/upload", response_model=ProjectState)
async def upload_project(file: UploadFile = File(...)) -> ProjectState:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pptx", ".pdf"}:
        raise HTTPException(status_code=400, detail="Only PPTX and PDF files are supported")

    project_id = create_project_id()
    root = ensure_project(project_id)
    upload_path = root / "uploads" / file.filename
    with upload_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    try:
        source = parse_source(upload_path, root, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile = infer_profile(source)
    write_model(project_id, "source_material.json", source)
    write_model(project_id, "lesson_profile.json", profile)
    return get_project_state(project_id)


@app.get("/api/projects/{project_id}", response_model=ProjectState)
def read_project(project_id: str) -> ProjectState:
    _assert_project(project_id)
    return get_project_state(project_id)


@app.get("/api/projects/{project_id}/artifacts", response_model=ArtifactTree)
def read_project_artifacts(project_id: str) -> ArtifactTree:
    _assert_project(project_id)
    return get_artifact_tree(project_id)


@app.post("/api/projects/{project_id}/agent/package", response_model=AgentPackage)
def create_agent_package(project_id: str) -> AgentPackage:
    _assert_project(project_id)
    return generate_agent_package(project_id)


@app.post("/api/projects/{project_id}/agent/validate", response_model=AgentValidation)
def validate_agent_project(project_id: str) -> AgentValidation:
    _assert_project(project_id)
    return validate_agent_output(project_id)


@app.put("/api/projects/{project_id}/profile", response_model=ProjectState)
def save_profile(project_id: str, profile: LessonProfile) -> ProjectState:
    _assert_project(project_id)
    write_model(project_id, "lesson_profile.json", profile)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/blueprint", response_model=ProjectState)
def generate_blueprint(project_id: str) -> ProjectState:
    _assert_project(project_id)
    source = read_model(project_id, "source_material.json", SourceMaterial)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    if not source or not profile:
        raise HTTPException(status_code=400, detail="Project needs source material and lesson profile")
    write_spec_artifacts(project_id, source, profile)
    blueprint, _ = generate_lesson_blueprint(source, profile, read_provider_settings())
    write_blueprint_artifacts(project_id, blueprint)
    return get_project_state(project_id)


@app.put("/api/projects/{project_id}/blueprint", response_model=ProjectState)
def save_blueprint(project_id: str, blueprint: LessonBlueprint) -> ProjectState:
    _assert_project(project_id)
    write_blueprint_artifacts(project_id, blueprint)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/media", response_model=ProjectState)
def generate_media(project_id: str) -> ProjectState:
    root = _assert_project(project_id)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    if not blueprint:
        raise HTTPException(status_code=400, detail="Generate a lesson blueprint first")
    manifest = generate_project_media(root, blueprint, read_provider_settings())
    write_model(project_id, "asset_manifest.json", manifest)
    write_json(project_id, "assets/data/attribution.json", {"schema": "hanclassstudio.attribution.v1", "items": []})
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/render", response_model=ProjectState)
def render_project(project_id: str) -> ProjectState:
    root = _assert_project(project_id)
    profile = read_model(project_id, "lesson_profile.json", LessonProfile)
    blueprint = read_model(project_id, "lesson_blueprint.json", LessonBlueprint)
    manifest = read_model(project_id, "asset_manifest.json", AssetManifest)
    if not profile or not blueprint:
        raise HTTPException(status_code=400, detail="Project needs profile and blueprint")
    if not manifest:
        manifest = generate_project_media(root, blueprint, read_provider_settings())
        write_model(project_id, "asset_manifest.json", manifest)
    report = render_and_check(project_id, root, profile, blueprint, manifest)
    if report.state != "blocked":
        zip_output(project_id)
    return get_project_state(project_id)


@app.post("/api/projects/{project_id}/pipeline", response_model=ProjectState)
def run_project_pipeline(project_id: str) -> ProjectState:
    root = _assert_project(project_id)
    try:
        return run_full_pipeline(project_id, root, read_provider_settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> FileResponse:
    _assert_project(project_id)
    state = get_project_state(project_id)
    if state.quality_report and state.quality_report.state == "blocked":
        raise HTTPException(status_code=409, detail="Quality gate is blocked; use forced export for demo output")
    export_path = latest_export_path(project_id) or zip_output(project_id)
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/zip",
    )


@app.post("/api/projects/{project_id}/export")
def force_export_project(project_id: str, force: bool = Query(default=False)) -> FileResponse:
    _assert_project(project_id)
    state = get_project_state(project_id)
    if state.quality_report and state.quality_report.state == "blocked" and not force:
        raise HTTPException(status_code=409, detail="Quality gate is blocked; pass force=true to export anyway")
    export_path = zip_output(project_id, force=force)
    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/zip",
    )


@app.post("/api/projects/{project_id}/export/pptx-editable", response_model=EditablePptxExportResponse)
def export_project_editable_pptx(project_id: str, force: bool = Query(default=False), export_mode: str = Query(default="debug")) -> EditablePptxExportResponse:
    _assert_project(project_id)
    try:
        export_path = export_editable_pptx(project_id, force=force, export_mode=export_mode)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


def _assert_project(project_id: str) -> Path:
    root = PROJECTS_DIR / project_id
    if not root.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    return root
