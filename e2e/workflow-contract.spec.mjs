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
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().endsWith("/api/settings/providers")) providerPuts += 1;
  });

  await page.goto("/");
  const onboarding = page.locator("dialog.onboarding-dialog[open]");
  if (await onboarding.count()) await onboarding.getByRole("button", { name: "跳过", exact: true }).click();
  const trigger = page.getByRole("button", { name: "模型设置", exact: true });
  await trigger.click();
  const dialog = page.locator("dialog.settings-dialog[open]");
  await dialog.getByRole("button", { name: "OCR 文字识别", exact: true }).click();
  const providerSelect = dialog.locator("select").nth(1);
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
  await expect(page.locator(".notice.error")).toContainText("后端");
  const failedRequestCount = providerPuts;
  await languageField.fill(secondValue);
  await expect.poll(() => providerPuts).toBeGreaterThan(failedRequestCount);
  await page.unroute("**/api/settings/providers");
  await expect(page.locator(".notice.error")).toHaveCount(0);
});
