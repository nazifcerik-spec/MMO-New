import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.describe("Item Studio", () => {
  test.beforeEach(async ({ page, isMobile }) => {
    const email = process.env.E2E_ADMIN_EMAIL;
    const password = process.env.E2E_ADMIN_PASSWORD;
    test.skip(!email || !password, "staff credentials not provided");
    test.skip(isMobile, "desktop/tablet tool");
    await login(page, email!, password!);
  });

  test("search, clone, edit with schema form, save, validate, preview and history", async ({ page }) => {
    await page.goto("/admin/items");
    await page.getByTestId("studio-search").fill("militia");
    await expect(page.getByTestId("row-militia_axe")).toBeVisible();
    await page.getByTestId("row-militia_axe").click();
    await expect(page.getByTestId("quick-inspector")).toContainText("militia_axe");
    const copy = `e2e_axe_${Date.now()}`;
    page.once("dialog", (d) => d.accept(copy));
    await page.getByRole("button", { name: "Clone" }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/items/${copy}$`));
    await expect(page.getByTestId("editor-status")).toContainText("Draft");

    await page.getByLabel("Vendor value (copper)").fill("123");
    await page.getByTestId("tab-stats").click();
    await page.getByTestId("add-effect").click();
    await page.getByTestId("effects-editor").getByLabel("Stat").selectOption("STR");
    await page.getByTestId("effects-editor").getByLabel("Amount").fill("4");
    await page.keyboard.press("Control+s");
    await expect(page.getByTestId("toast")).toContainText("Saved.");
    await expect(page.getByTestId("editor-valid")).toBeVisible();

    await page.getByTestId("tab-requirements").click();
    await expect(page.getByTestId("budget-meter")).toContainText("distributable stats");
    await page.getByTestId("tab-localization").click();
    await page.getByTestId("loc-tr").click();
    await page.getByTestId("text-name").fill("E2E Balta");
    await page.getByTestId("save-texts").click();
    await expect(page.getByTestId("loc-tr")).toContainText("draft");

    await page.getByTestId("tab-preview").click();
    await page.getByTestId("preview-profile").selectOption("warrior_600");
    await page.getByTestId("run-preview").click();
    await expect(page.getByTestId("preview-result")).toContainText("attack_power");
    await expect(page.getByTestId("tooltip-previews")).toContainText("E2E Balta");

    page.once("dialog", (d) => d.accept());
    await page.getByTestId("editor-publish").click();
    await expect(page.getByTestId("editor-status")).toContainText("r1");
    await page.getByTestId("tab-history").click();
    await expect(page.getByTestId("history-table")).toContainText("r1");
  });

  test("generator wizard: dry run, then atomic draft creation", async ({ page }) => {
    await page.goto("/admin/items/generator");
    const theme = `e${Date.now().toString(36)}`;
    await page.getByTestId("gen-theme").fill(theme);
    await page.getByTestId("gen-count").fill("4");
    await page.getByTestId("gen-dry-run").click();
    await expect(page.getByTestId("gen-summary")).toContainText("errors"); // empty affix pool -> fine/rare rows invalid
    await expect(page.getByTestId("gen-commit")).toBeDisabled();
    for (const affix of ["of_strength", "brutal", "keen"]) await page.getByRole("button", { name: affix, exact: true }).click();
    await page.getByTestId("gen-dry-run").click();
    await expect(page.getByTestId("gen-summary")).toContainText("4 items · 0 errors");
    page.once("dialog", (d) => d.accept());
    await page.getByTestId("gen-commit").click();
    await expect(page.getByTestId("toast")).toContainText("4 drafts created");
    await page.goto("/admin/items");
    await page.getByTestId("studio-search").fill(theme);
    await expect(page.getByTestId("studio-total")).toHaveText("4 items");
  });
});
