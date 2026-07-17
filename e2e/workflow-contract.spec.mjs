import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixture = path.join(repositoryRoot, "output", "HanClassStudio_Diagnostic_20260708_191704_917652.pptx");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("hcs_onboarding_seen", "true");
  });
});

test("upload state survives refresh and gates remain authoritative before quality", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').first().setInputFiles(fixture);

  await expect(page).toHaveURL(/project_id=[^&]+&stage=profile/, { timeout: 30_000 });
  const projectId = new URL(page.url()).searchParams.get("project_id");
  expect(projectId).toMatch(/^[a-f0-9]{12}$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(new RegExp(`project_id=${projectId}&stage=profile`));
  await expect(page.getByRole("heading", { level: 2, name: "课程信息确认" })).toBeVisible();

  await page.goto(`/?project_id=${projectId}&stage=quality`);
  await expect(page.locator(".gate-summary")).toBeVisible();
  await expect(page.locator(".gate-card.not_run")).toHaveCount(4);
  await expect(page.locator(".quality-state.not_run").first()).toBeVisible();

  await page.goto(`/?project_id=${projectId}&stage=delivery`);
  await expect(page.locator(".download-link.disabled")).toBeVisible();
  await expect(page.locator("button.danger-button").first()).toBeDisabled();
});

test("responsive workflow and settings dialog remain keyboard-safe", async ({ page }) => {
  let providerPuts = 0;
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().endsWith("/api/settings/providers")) providerPuts += 1;
  });

  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  if (await onboarding.count()) await onboarding.getByRole("button", { name: "跳过", exact: true }).click();
  await expect(page.getByRole("button", { name: "模型设置", exact: true })).toBeVisible();
  await expect.poll(() => providerPuts).toBe(0);
  await page.locator('input[type="file"]').first().setInputFiles(fixture);
  await expect(page).toHaveURL(/project_id=[^&]+&stage=profile/, { timeout: 30_000 });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    pipelineWidth: document.querySelector(".pipeline-status")?.scrollWidth ?? 0,
    pipelineClientWidth: document.querySelector(".pipeline-status")?.clientWidth ?? 0,
  }))).toEqual({ documentWidth: 390, viewportWidth: 390, pipelineWidth: 360, pipelineClientWidth: 360 });

  const settingsTrigger = page.getByRole("button", { name: "模型设置", exact: true });
  await settingsTrigger.click();
  const dialog = page.locator("dialog.settings-dialog[open]");
  await expect(dialog).toHaveAttribute("aria-describedby", "modelSettingsDescription");
  await expect.poll(() => page.evaluate(() => document.querySelector("dialog[open]")?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect.poll(() => page.evaluate(() => document.querySelector("dialog[open]")?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => page.evaluate(() => document.querySelector("dialog[open]")?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(settingsTrigger).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe("");
});

test("provider save reports a failed edit and retries the next edit", async ({ page }) => {
  let providerPuts = 0;
  let aborted = false;
  const providerPutFailures = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().endsWith("/api/settings/providers")) providerPuts += 1;
  });
  page.on("requestfailed", (request) => {
    if (request.method() === "PUT" && request.url().endsWith("/api/settings/providers")) {
      providerPutFailures.push(request.failure()?.errorText ?? "unknown");
    }
  });

  // This persistence test intentionally supplies a backend-shaped capability
  // response so it remains independent of whether the CI image has the local
  // Tesseract binary installed. It does not change the product contract: the
  // UI still renders the availability returned by the capability endpoint.
  await page.route("**/api/settings/providers/capabilities", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: body.map((descriptor) =>
        descriptor.provider_id === "tesseract"
          ? { ...descriptor, implemented: true, configurable: true, available: true }
          : descriptor
      ),
    });
  });

  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  if (await onboarding.count()) await onboarding.getByRole("button", { name: "跳过", exact: true }).click();
  const trigger = page.getByRole("button", { name: "模型设置", exact: true });
  await trigger.click();
  const dialog = page.locator("dialog.settings-dialog[open]");
  await dialog.getByRole("button", { name: "OCR 文字识别", exact: true }).click();
  const providerSelect = dialog.getByRole("combobox", { name: "选择服务商", exact: true });
  await expect(providerSelect).toHaveCount(1);
  await page.route("**/api/settings/providers", async (route) => {
    if (route.request().method() === "PUT" && !aborted) {
      aborted = true;
      await route.abort("failed");
    } else {
      await route.continue();
    }
  });
  await providerSelect.selectOption("tesseract");
  const languageField = dialog.locator("input").first();
  await expect(languageField).toBeVisible();
  const firstValue = `browser-retry-${Date.now()}`;
  const secondValue = `${firstValue}-again`;
  await languageField.fill(firstValue);
  await expect.poll(() => providerPuts).toBeGreaterThan(0);
  await expect.poll(() => aborted).toBe(true);
  const providerSaveError = dialog
    .locator(".notice.error")
    .filter({ hasText: "后端" });
  await expect(providerSaveError).toHaveCount(1);
  await expect(providerSaveError).toBeVisible();
  await expect.poll(() => providerPutFailures).toEqual(["net::ERR_FAILED"]);
  const capabilityRefreshPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith("/api/settings/providers/capabilities") &&
      response.ok()
  );
  const retryResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      response.url().endsWith("/api/settings/providers") &&
      response.ok()
  );
  await languageField.fill(secondValue);
  await retryResponsePromise;
  await page.unroute("**/api/settings/providers");
  await capabilityRefreshPromise;
  await page.unroute("**/api/settings/providers/capabilities");
  await expect(providerSaveError).toHaveCount(0);
  expect(providerPutFailures).toEqual(["net::ERR_FAILED"]);
});

test("trusted provider registry requires explicit confirmation and keeps dialog focus", async ({ page }) => {
  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  if (await onboarding.count()) await onboarding.getByRole("button", { name: "跳过", exact: true }).click();

  const trigger = page.getByRole("button", { name: "模型设置", exact: true });
  await trigger.click();
  const settings = page.locator("dialog.settings-dialog[open]");
  const registry = settings.locator(".provider-registry");
  await expect(registry).toBeVisible();
  await expect(registry.locator(".provider-registry-card")).toHaveCount(2);
  await expect(registry).toContainText("HanClassStudio OCR Sandbox");
  await expect(registry).toContainText("HanClassStudio first-party");

  const prepare = registry.getByRole("button", { name: "生成沙盒演练计划" }).first();
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await expect(confirmDialog).toHaveAttribute("aria-describedby", "registryInstallDescription");
  await expect.poll(() => confirmDialog.evaluate((dialog) => dialog.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(confirmDialog).toBeHidden();
  await expect(settings).toBeVisible();
  await expect(prepare).toBeFocused();

  const installResponse = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/install/confirm") && response.ok(),
  );
  await prepare.click();
  await page.getByRole("button", { name: "开始沙盒演练", exact: true }).click();
  await installResponse;
  await expect(registry.getByText("沙盒生命周期已验证", { exact: true }).first()).toBeVisible();
  await expect(registry).toContainText("不会下载或执行第三方项目");
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("provider catalog refresh is explicit and official source links come from the backend", async ({ page }) => {
  let refreshPosts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/providers/registry/refresh")) refreshPosts += 1;
  });

  await page.goto("/");
  await expect.poll(() => refreshPosts).toBe(0);
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  if (await onboarding.count()) await onboarding.getByRole("button", { name: "跳过", exact: true }).click();
  const trigger = page.getByRole("button", { name: "模型设置", exact: true });
  await trigger.click();
  const settings = page.locator("dialog.settings-dialog[open]");
  const registry = settings.locator(".provider-registry");
  const projectLink = registry.getByRole("link", { name: "xueyang-dev/HanClassStudio" }).first();
  await expect(projectLink).toHaveAttribute("href", /github\.com\/xueyang-dev\/HanClassStudio/);
  await expect(projectLink).toHaveAttribute("target", "_blank");
  await expect(projectLink).toHaveAttribute("rel", "noopener noreferrer");
  await expect(registry).toContainText("权利归各自权利人所有");

  const catalog = await (await page.request.get("http://127.0.0.1:8012/api/providers/registry")).json();
  await page.route("**/api/providers/registry/refresh", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ catalog, changed_provider_ids: [] }) });
  });
  await registry.getByRole("button", { name: "检查目录更新", exact: true }).click();
  await expect.poll(() => refreshPosts).toBe(1);
  await expect(registry.getByText("目录已更新，发现 0 项变化", { exact: true })).toBeVisible();

  await page.unroute("**/api/providers/registry/refresh");
  await page.route("**/api/providers/registry/refresh", async (route) => {
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "provider_registry_fetch_failed", message: "The official Provider Registry could not be reached", blockers: [] } }),
    });
  });
  await registry.getByRole("button", { name: "检查目录更新", exact: true }).click();
  await expect.poll(() => refreshPosts).toBe(2);
  await expect(registry.getByRole("alert")).toContainText("已保留上次可信目录");

  const savedSettings = await (await page.request.get("http://127.0.0.1:8012/api/settings/providers")).json();
  await page.route("**/api/settings/providers", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(savedSettings) });
      return;
    }
    await route.continue();
  });
  await settings.getByRole("button", { name: "LLM 语言模型", exact: true }).click();
  await settings.getByRole("button", { name: "在线 API", exact: true }).click();
  const apiLink = settings.getByRole("link", { name: "申请 API / 获取密钥", exact: true });
  await expect(apiLink).toHaveAttribute("href", "https://platform.openai.com/api-keys");
  await expect(apiLink).toHaveAttribute("rel", "noopener noreferrer");
});

test("first-use provider selection exposes a capability-scoped sandbox without claiming a real provider", async ({ page }) => {
  let blockCapabilities = new Set(["ocr"]);
  await page.addInitScript(() => {
    window.localStorage.removeItem("hcs_onboarding_seen");
  });
  await page.route("**/api/settings/providers/capabilities", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const filtered = body.map((descriptor) => blockCapabilities.has(descriptor.capability)
      ? { ...descriptor, available: false, configured: false }
      : descriptor);
    await route.fulfill({ response, json: filtered });
  });

  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  await expect(onboarding).toBeVisible();
  await onboarding.getByRole("button", { name: "选择服务商", exact: true }).click();
  await expect(onboarding.getByRole("heading", { level: 2, name: "选择服务商", exact: true })).toBeVisible();

  const registry = onboarding.locator(".provider-registry");
  await expect(registry).toHaveCount(1);
  await expect(registry.locator(".provider-registry-card")).toHaveCount(1);
  await expect(registry).toContainText("HanClassStudio OCR Sandbox");
  await expect(registry).not.toContainText("HanClassStudio LLM Sandbox");

  const prepare = registry.getByRole("button", { name: "生成沙盒演练计划", exact: true });
  await expect(prepare).toHaveCount(1);
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await expect(confirmDialog).toContainText("版本");
  await expect(confirmDialog).toContainText("不会下载、安装或执行任何第三方项目");
  await confirmDialog.getByRole("button", { name: "开始沙盒演练", exact: true }).click();

  await expect(registry.getByText("沙盒生命周期已验证", { exact: true })).toBeVisible();
  await expect(onboarding.getByRole("combobox", { name: "选择服务商", exact: true })).toHaveCount(0);
  await expect(onboarding.getByText("新的服务商已经可用，请在上方下拉菜单中选择。", { exact: true })).toHaveCount(0);
});

test("first-use registry keeps an installed provider blocked until configuration", async ({ page }) => {
  let blockCapabilities = new Set(["llm"]);
  await page.addInitScript(() => {
    window.localStorage.removeItem("hcs_onboarding_seen");
  });
  await page.route("**/api/settings/providers/capabilities", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const filtered = body.map((descriptor) => blockCapabilities.has(descriptor.capability)
      ? { ...descriptor, available: false, configured: false }
      : descriptor);
    await route.fulfill({ response, json: filtered });
  });

  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  await onboarding.getByRole("button", { name: "选择服务商", exact: true }).click();
  const llmTab = onboarding.getByRole("button", { name: "LLM 语言模型", exact: true });
  await llmTab.click();

  const registry = onboarding.locator(".provider-registry");
  await expect(registry.locator(".provider-registry-card")).toHaveCount(1);
  await expect(registry).toContainText("HanClassStudio LLM Sandbox");
  const prepare = registry.getByRole("button", { name: "生成沙盒演练计划", exact: true });
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await confirmDialog.getByRole("button", { name: "开始沙盒演练", exact: true }).click();

  await expect(registry).toContainText("已安装，待配置");
  await expect(registry.getByRole("button", { name: "配置并启用", exact: true })).toHaveCount(1);
  const secretField = registry.locator("input[type='password']");
  await expect(secretField).toHaveCount(1);
  await secretField.fill("onboarding-test-secret");
  await registry.getByRole("button", { name: "配置并启用", exact: true }).click();
  await expect(registry.getByText("沙盒生命周期已验证", { exact: true })).toBeVisible();
  await expect(onboarding.getByRole("combobox", { name: "选择服务商", exact: true })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("onboarding-test-secret");
});

test("first-use capability registry remains readable on a 390px viewport", async ({ page }) => {
  const blockCapabilities = new Set(["ocr"]);
  await page.addInitScript(() => {
    window.localStorage.removeItem("hcs_onboarding_seen");
  });
  await page.route("**/api/settings/providers/capabilities", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: body.map((descriptor) => blockCapabilities.has(descriptor.capability)
        ? { ...descriptor, available: false, configured: false }
        : descriptor),
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  await onboarding.getByRole("button", { name: "选择服务商", exact: true }).click();
  const registry = onboarding.locator(".provider-registry");
  await expect(registry).toBeVisible();
  await expect(registry.locator(".provider-registry-card")).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }))).toEqual({ documentWidth: 390, viewportWidth: 390 });
  const cardOverflow = await registry.locator(".provider-registry-card").evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  expect(cardOverflow.scrollWidth).toBeLessThanOrEqual(cardOverflow.clientWidth);

  const prepare = registry.getByRole("button", { name: "生成沙盒演练计划", exact: true });
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await expect.poll(() => confirmDialog.evaluate((dialog) => dialog.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(confirmDialog).toBeHidden();
  await expect(prepare).toBeFocused();
});
