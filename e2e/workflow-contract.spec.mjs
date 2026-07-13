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
