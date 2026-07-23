import { test, expect } from "@playwright/test";


test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("hcs_onboarding_seen", "1"));
});


test("Provider Hub does not refresh on entry and renders a checksum failure without false success", async ({ page }) => {
  let refreshPosts = 0;
  const catalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/hub")).json();
  const localProvider = catalog.providers.find((provider) => provider.id === "hcs.local-image-basic");
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/providers/hub/refresh")) refreshPosts += 1;
  });
  await page.route("**/api/providers/hub/packages/hcs.local-image-basic/install", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task: {
          task_id: "checksum-e2e", package_id: "hcs.local-image-basic", state: "queued", phase: "preflight",
          progress: 0, current_file_progress: 0, downloaded_bytes: 0, total_bytes: 512,
          message: "queued", started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
          cancellable: true, cancel_requested: false, error: null, recoverable_actions: [], log_ref: "e2e",
        },
        provider: { ...localProvider, status: "installing", available_actions: ["view_details", "open_project", "cancel_install"] },
      }),
    });
  });
  await page.route("**/api/providers/hub/install-tasks/checksum-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "checksum-e2e", package_id: "hcs.local-image-basic", state: "failed", phase: "failed",
        progress: 35, current_file_progress: 100, downloaded_bytes: 512, total_bytes: 512,
        message: "checksum mismatch", started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        finished_at: new Date().toISOString(), cancellable: false, cancel_requested: false,
        error: { code: "checksum_mismatch", message: "checksum mismatch" }, recoverable_actions: ["repair"], log_ref: "e2e",
      }),
    });
  });

  await page.goto("/");
  await expect.poll(() => refreshPosts).toBe(0);
  await page.getByRole("button", { name: "教学能力中心", exact: true }).first().click();
  const hub = page.locator("dialog.provider-hub-dialog[open]");
  await expect(hub).toBeVisible();
  await expect(hub.getByRole("heading", { level: 2, name: "教学能力中心" })).toBeVisible();
  await expect(hub.getByRole("heading", { level: 3, name: "推荐能力" })).toBeVisible();
  await expect(hub.locator(".provider-hub-card").filter({ hasText: "本地基础生图" }).first()).toBeVisible();
  await expect.poll(() => refreshPosts).toBe(0);

  const localCard = hub.locator(".provider-hub-card").filter({ hasText: "本地基础生图" }).first();
  await localCard.getByRole("button", { name: "安装", exact: true }).click();
  await expect(localCard.getByText("文件校验失败，未保留安装结果。", { exact: true })).toBeVisible();
  await expect(localCard.getByText("当前可用", { exact: true })).toHaveCount(0);
});


test("install start applies authoritative cancel action, cancels, and blocks rapid duplicates", async ({ page }) => {
  const catalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/hub")).json();
  const localProvider = catalog.providers.find((provider) => provider.id === "hcs.local-image-basic");
  let startPosts = 0;
  let cancelled = false;
  const startedAt = new Date().toISOString();
  const task = (state, phase, cancelRequested = false) => ({
    task_id: "cancel-e2e", package_id: "hcs.local-image-basic", state, phase,
    progress: state === "cancelled" ? 10 : 5, current_file_progress: 0, downloaded_bytes: 0, total_bytes: 512,
    message: state, started_at: startedAt, updated_at: new Date().toISOString(),
    finished_at: state === "cancelled" ? new Date().toISOString() : null,
    cancellable: state !== "cancelled", cancel_requested: cancelRequested,
    error: state === "cancelled" ? { code: "cancelled", message: "cancelled" } : null,
    recoverable_actions: [], log_ref: "e2e",
  });

  await page.route("**/api/providers/hub/packages/hcs.local-image-basic/install", async (route) => {
    startPosts += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task: task("queued", "preflight"),
        provider: { ...localProvider, status: "installing", available_actions: ["view_details", "open_project", "cancel_install"] },
      }),
    });
  });
  await page.route("**/api/providers/hub/install-tasks/cancel-e2e", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(cancelled ? task("cancelled", "cancelled", true) : task("running", "downloading")) });
  });
  await page.route("**/api/providers/hub/install-tasks/cancel-e2e/cancel", async (route) => {
    cancelled = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task: task("running", "downloading", true),
        provider: { ...localProvider, status: "installing", available_actions: ["view_details", "open_project", "cancel_install"] },
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "教学能力中心", exact: true }).first().click();
  const hub = page.locator("dialog.provider-hub-dialog[open]");
  const localCard = hub.locator(".provider-hub-card").filter({ hasText: "本地基础生图" }).first();
  const install = localCard.getByRole("button", { name: "安装", exact: true });
  await install.evaluate((button) => { button.click(); button.click(); });
  await expect.poll(() => startPosts).toBe(1);
  await expect(localCard.getByRole("button", { name: "安装", exact: true })).toHaveCount(0);
  const cancel = localCard.getByRole("button", { name: "取消安装", exact: true });
  await expect(cancel).toBeVisible();
  await cancel.click();
  await expect.poll(() => cancelled).toBe(true);
  await expect(localCard.getByRole("button", { name: "安装", exact: true })).toBeVisible();
  await expect(localCard.getByRole("button", { name: "取消安装", exact: true })).toHaveCount(0);
});


test("Provider Hub refresh summary, source details, real fixture install, and narrow layout work end to end", async ({ page }) => {
  let refreshPosts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/providers/hub/refresh")) refreshPosts += 1;
  });
  await page.route("**/api/providers/hub/refresh", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "refresh-e2e", state: "queued", started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        summary: { added: 0, updated: 0, unchanged: 0, failed_sources: 0, sources: [] }, error: null,
      }),
    });
  });
  await page.route("**/api/providers/hub/refresh/refresh-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "refresh-e2e", state: "partial", started_at: new Date().toISOString(), updated_at: new Date().toISOString(), finished_at: new Date().toISOString(),
        summary: {
          added: 2, updated: 1, unchanged: 8, failed_sources: 1,
          sources: [
            { source_id: "builtin_catalog", status: "unchanged", message: "应用内置 Provider 目录可用", retained_previous_snapshot: false },
            { source_id: "official_registry", status: "failed", message: "官方注册表暂时不可用，已保留上一次结果", retained_previous_snapshot: true },
          ],
        },
        error: { code: "network_error", message: "partial" },
      }),
    });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: "教学能力中心", exact: true }).first();
  await trigger.click();
  const hub = page.locator("dialog.provider-hub-dialog[open]");
  await expect.poll(() => hub.evaluate((element) => ({ scroll: element.scrollWidth, client: element.clientWidth }))).toEqual({ scroll: 390, client: 390 });

  const localCard = hub.locator(".provider-hub-card").filter({ hasText: "本地基础生图" }).first();
  await localCard.getByText("高级信息", { exact: true }).click();
  await expect(localCard).toContainText("Runtime · Fixture Runtime");
  await expect(localCard).toContainText("Model Package");
  await expect(localCard).toContainText("Workflow Pack");
  const source = localCard.getByRole("link", { name: /项目来源/ });
  await expect(source).toHaveAttribute("target", "_blank");
  await expect(source).toHaveAttribute("rel", "noopener noreferrer");

  await hub.getByRole("button", { name: "刷新能力列表", exact: true }).click();
  await expect.poll(() => refreshPosts).toBe(1);
  await expect(hub.getByText("刷新未完全完成", { exact: true })).toBeVisible();
  await expect(hub).toContainText("新增 2 · 更新 1 · 未变化 8 · 失败来源 1");
  await expect(hub).toContainText("已保留上一次结果");

  await page.unroute("**/api/providers/hub/refresh");
  await page.unroute("**/api/providers/hub/refresh/refresh-e2e");
  await localCard.getByRole("button", { name: "安装", exact: true }).click();
  await expect(localCard.getByText("安装完成", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(localCard.getByText("当前可用", { exact: true })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(hub).toBeHidden();
  await expect(trigger).toBeFocused();
});


test("ComfyUI Runtime installs, starts, stays model-incomplete, stops, and uninstalls", async ({ page }) => {
  const initialCatalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/hub")).json();
  const initial = initialCatalog.providers.find((provider) => provider.id === "hcs.comfyui-runtime");
  let status = "not_installed";
  let installed = false;
  let activeTask = null;
  const actions = () => {
    if (!installed) return ["install_runtime", "view_runtime_logs", "open_runtime_directory"];
    if (status === "runtime_ready") return ["stop_runtime", "force_stop_runtime", "check_runtime", "view_runtime_logs", "open_runtime_directory"];
    return ["start_runtime", "check_runtime", "repair_runtime", "uninstall_runtime", "view_runtime_logs", "open_runtime_directory"];
  };
  const provider = () => ({
    ...initial,
    status,
    installed,
    configured: installed,
    ready: false,
    runtime_ready: status === "runtime_ready",
    generation_ready: false,
    available_actions: actions(),
    runtime_details: {
      ...initial.runtime_details,
      status,
      installed,
      runtime_ready: status === "runtime_ready",
      generation_ready: false,
      available_actions: actions(),
      actual_port: status === "runtime_ready" ? 8188 : null,
    },
  });
  const task = (id, operation, state, phase, progress) => ({
    task_id: id, package_id: "hcs.comfyui-runtime", operation, state, phase, progress,
    current_file_progress: progress, downloaded_bytes: 11611291, total_bytes: 11611291,
    message: phase, started_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    finished_at: state === "completed" ? new Date().toISOString() : null,
    cancellable: state !== "completed", cancel_requested: false, error: null,
    recoverable_actions: [], log_ref: "e2e-comfyui",
  });

  await page.route("**/api/providers/hub", async (route) => {
    if (!route.request().url().endsWith("/api/providers/hub")) return route.continue();
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ ...initialCatalog, providers: initialCatalog.providers.map((item) => item.id === initial.id ? provider() : item) }),
    });
  });
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/install", async (route) => {
    activeTask = task("comfy-install-e2e", "install", "queued", "preflight", 0);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ task: activeTask, provider: { ...provider(), status: "installing", available_actions: ["cancel_install", "view_runtime_logs"] } }) });
  });
  await page.route("**/api/providers/hub/install-tasks/comfy-install-e2e", async (route) => {
    installed = true; status = "stopped";
    activeTask = task("comfy-install-e2e", "install", "completed", "completed", 100);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(activeTask) });
  });
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/start", async (route) => {
    status = "runtime_ready";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(provider()) });
  });
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/stop", async (route) => {
    status = "stopped";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(provider()) });
  });
  const uninstallIdentity = "a".repeat(64);
  const uninstallToken = "b".repeat(64);
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/prepare-uninstall", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          operation: "uninstall",
          runtime_id: "comfyui",
          version: "0.28.0",
          installation_identity: uninstallIdentity,
          tree_identity: "c".repeat(64),
          modified: false,
          replaces_runtime_files: false,
          preserves_models: true,
          preserves_runtime_data: true,
          preserves_logs: true,
        },
        confirmation_token: uninstallToken,
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      }),
    });
  });
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/uninstall", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      confirmation_token: uninstallToken,
      expected_runtime_identity: uninstallIdentity,
      preserve_models: true,
    });
    activeTask = task("comfy-uninstall-e2e", "uninstall", "queued", "preflight", 0);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ task: activeTask, provider: { ...provider(), status: "installing", available_actions: ["cancel_install", "view_runtime_logs"] } }) });
  });
  await page.route("**/api/providers/hub/install-tasks/comfy-uninstall-e2e", async (route) => {
    installed = false; status = "not_installed";
    activeTask = task("comfy-uninstall-e2e", "uninstall", "completed", "completed", 100);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(activeTask) });
  });
  page.on("dialog", (dialog) => void dialog.accept());

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "教学能力中心", exact: true }).first().click();
  const hub = page.locator("dialog.provider-hub-dialog[open]");
  const card = hub.locator(".provider-hub-card").filter({ hasText: "ComfyUI 本地运行环境" }).first();
  await expect(card).toContainText("本阶段没有图片生成功能");
  await expect(card.getByRole("button", { name: /生成图片/ })).toHaveCount(0);
  await card.getByRole("button", { name: "安装运行环境", exact: true }).click();
  await expect(card.getByText("已安装，当前停止", { exact: true })).toBeVisible();
  await expect(card).toContainText("运行环境可用，但尚未安装图片模型");
  await card.getByRole("button", { name: "启动", exact: true }).click();
  await expect(card.getByText("运行环境可用", { exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: /生成图片/ })).toHaveCount(0);
  await card.getByRole("button", { name: "停止", exact: true }).click();
  await expect(card.getByText("已安装，当前停止", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "卸载", exact: true }).click();
  await expect(card.getByText("未安装", { exact: true })).toBeVisible();
  await expect.poll(() => hub.evaluate((element) => ({ scroll: element.scrollWidth, client: element.clientWidth }))).toEqual({ scroll: 390, client: 390 });
});


test("ComfyUI archive security fixture never renders Runtime ready", async ({ page }) => {
  const catalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/hub")).json();
  const provider = catalog.providers.find((item) => item.id === "hcs.comfyui-runtime");
  const installableProvider = {
    ...provider,
    status: "not_installed",
    installed: false,
    configured: false,
    ready: false,
    runtime_ready: false,
    generation_ready: false,
    compatible: "compatible",
    available_actions: ["install_runtime", "view_runtime_logs", "open_runtime_directory"],
    runtime_details: {
      ...provider.runtime_details,
      status: "not_installed",
      installed: false,
      runtime_ready: false,
      generation_ready: false,
      compatible: true,
      available_actions: ["install_runtime", "view_runtime_logs", "open_runtime_directory"],
    },
  };
  const now = new Date().toISOString();
  await page.route("**/api/providers/hub", async (route) => {
    if (!route.request().url().endsWith("/api/providers/hub")) return route.continue();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...catalog,
        providers: catalog.providers.map((item) => item.id === provider.id ? installableProvider : item),
      }),
    });
  });
  await page.route("**/api/providers/hub/packages/hcs.comfyui-runtime/install", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        task: { task_id: "unsafe-comfy-e2e", package_id: provider.id, operation: "install", state: "queued", phase: "preflight", progress: 0, current_file_progress: 0, downloaded_bytes: 0, total_bytes: 11611291, message: "queued", started_at: now, updated_at: now, finished_at: null, cancellable: true, cancel_requested: false, error: null, recoverable_actions: [], log_ref: "e2e" },
        provider: { ...installableProvider, status: "installing", available_actions: ["cancel_install", "view_runtime_logs"] },
      }),
    });
  });
  await page.route("**/api/providers/hub/install-tasks/unsafe-comfy-e2e", async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ task_id: "unsafe-comfy-e2e", package_id: provider.id, operation: "install", state: "failed", phase: "failed", progress: 32, current_file_progress: 100, downloaded_bytes: 11611291, total_bytes: 11611291, message: "unsafe", started_at: now, updated_at: now, finished_at: now, cancellable: false, cancel_requested: false, error: { code: "unsafe_archive", message: "unsafe archive" }, recoverable_actions: ["repair_runtime"], log_ref: "e2e" }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "教学能力中心", exact: true }).first().click();
  const card = page.locator("dialog.provider-hub-dialog[open] .provider-hub-card").filter({ hasText: "ComfyUI 本地运行环境" }).first();
  await card.getByRole("button", { name: "安装运行环境", exact: true }).click();
  await expect(card.getByText("archive 未通过安全检查，未发布 Runtime。", { exact: true })).toBeVisible();
  await expect(card.getByText("运行环境可用", { exact: true })).toHaveCount(0);
  await expect(card.getByRole("button", { name: /生成图片/ })).toHaveCount(0);
});


test("online Provider configuration is explicit and credentials never render", async ({ page }) => {
  const secret = "provider-hub-browser-secret";
  let configurationPuts = 0;
  let submittedModel = "";
  let testPosts = 0;
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().includes("/api/providers/hub/online/openai_images/configuration")) configurationPuts += 1;
    if (request.method() === "POST" && request.url().endsWith("/api/providers/hub/online/openai_images/test")) testPosts += 1;
  });

  await page.goto("/");
  await page.getByRole("button", { name: "教学能力中心", exact: true }).first().click();
  const hub = page.locator("dialog.provider-hub-dialog[open]");
  const online = hub.locator(".provider-hub-card").filter({ hasText: "在线高质量生图" }).first();
  await online.getByRole("button", { name: "配置", exact: true }).click();
  const form = hub.locator(".provider-hub-config");
  await expect(form).toBeVisible();
  await expect(form.getByLabel("自定义服务地址（Endpoint）", { exact: true })).toBeHidden();
  await form.getByText("高级设置", { exact: true }).click();
  await expect(form.getByLabel("自定义模型名称", { exact: true })).toHaveValue("gpt-image-2");
  await expect(form.getByLabel("自定义模型名称", { exact: true })).not.toHaveValue("placeholder-svg");
  await expect.poll(() => configurationPuts).toBe(0);
  await page.route("**/api/providers/hub/online/openai_images/configuration", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    submittedModel = route.request().postDataJSON().model;
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "request_validation_failed",
          message: "The submitted request is invalid.",
          fields: [{ path: "api_key", code: "value_error", message: "The submitted value is invalid." }],
        },
      }),
    });
  });
  await form.getByLabel("API Key", { exact: true }).fill(secret);
  await form.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect.poll(() => configurationPuts).toBe(1);
  await expect.poll(() => submittedModel).toBe("gpt-image-2");
  await expect(hub.getByRole("alert")).toHaveText("提交的信息格式不正确，请检查标记的字段。 有一项内容格式不正确。");
  await expect(hub.getByRole("alert")).not.toContainText(secret);
  await page.unroute("**/api/providers/hub/online/openai_images/configuration");
  await form.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect.poll(() => configurationPuts).toBe(2);
  await expect(form.getByLabel("API Key", { exact: true })).toHaveValue("");
  await expect(page.locator("body")).not.toContainText(secret);

  await page.route("**/api/providers/hub/online/openai_images/test", async (route) => {
    const catalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/hub")).json();
    const item = catalog.providers.find((provider) => provider.id === "hcs.online-image-high-quality");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...item, status: "ready", ready: true }) });
  });
  await form.getByRole("button", { name: "测试连接", exact: true }).click();
  await expect.poll(() => testPosts).toBe(1);
  await expect(page.locator("body")).not.toContainText(secret);
  await form.getByRole("button", { name: "删除配置", exact: true }).click();
  await expect(form.getByPlaceholder("已保存；留空可保留原值")).toHaveCount(0);
});
