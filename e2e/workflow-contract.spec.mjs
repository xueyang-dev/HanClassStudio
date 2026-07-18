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
  const sourceLink = registry.getByRole("link", { name: "查看官方项目", exact: true }).first();
  const licenseLink = registry.getByRole("link", { name: "查看许可证", exact: true }).first();
  await expect(sourceLink).toHaveAttribute("href", /github\.com\/xueyang-dev\/HanClassStudio\/tree\/[0-9a-f]{40}\/providers/);
  await expect(sourceLink).toHaveAttribute("target", "_blank");
  await expect(sourceLink).toHaveAttribute("rel", /noopener/);
  await expect(licenseLink).toHaveAttribute("href", /github\.com\/xueyang-dev\/HanClassStudio\/blob\/[0-9a-f]{40}\/LICENSE/);
  await expect(licenseLink).toHaveAttribute("target", "_blank");
  await expect(licenseLink).toHaveAttribute("rel", /noopener/);

  const prepare = registry.getByRole("button", { name: "生成安装计划" }).first();
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
  await page.getByRole("button", { name: "确认安装", exact: true }).click();
  await installResponse;
  await expect(registry.locator(".provider-registry-state.available").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("first-use provider selection installs a capability-scoped local provider", async ({ page }) => {
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

  const prepare = registry.getByRole("button", { name: "生成安装计划", exact: true });
  await expect(prepare).toHaveCount(1);
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await expect(confirmDialog).toContainText("固定版本");
  await confirmDialog.getByRole("button", { name: "确认安装", exact: true }).click();
  blockCapabilities = new Set();

  await expect(registry.locator(".provider-registry-state.available")).toBeVisible();
  await expect(registry).toContainText("仅用于安全演示");
  await expect(onboarding.locator('option[value="hcs_mock_ocr"]')).toHaveCount(0);
  await expect(onboarding).not.toContainText("新的服务商已经可用，请在上方下拉菜单中选择。");
});

test("first-use registry keeps a configured sandbox blocked without a real executor", async ({ page }) => {
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
  const prepare = registry.getByRole("button", { name: "生成安装计划", exact: true });
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await confirmDialog.getByRole("button", { name: "确认安装", exact: true }).click();

  await expect(registry).toContainText("已安装，待配置");
  await expect(registry.getByRole("button", { name: "配置并启用", exact: true })).toHaveCount(1);
  const secretField = registry.locator("input[type='password']");
  await expect(secretField).toHaveCount(1);
  await secretField.fill("onboarding-test-secret");
  await registry.getByRole("button", { name: "配置并启用", exact: true }).click();
  await expect(registry.locator(".provider-registry-state.available")).toBeVisible();
  await expect(registry).toContainText("仅用于安全演示");
  await expect(onboarding.locator('option[value="hcs_mock_llm"]')).toHaveCount(0);
  await expect(onboarding).not.toContainText("新的服务商已经可用，请在上方下拉菜单中选择。");
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

  const prepare = registry.getByRole("button", { name: "生成安装计划", exact: true });
  await prepare.click();
  const confirmDialog = page.locator("dialog.confirm-dialog[open]");
  await expect(confirmDialog).toBeVisible();
  await expect.poll(() => confirmDialog.evaluate((dialog) => dialog.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(confirmDialog).toBeHidden();
  await expect(prepare).toBeFocused();
});
