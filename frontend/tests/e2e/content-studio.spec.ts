import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test.describe("Content Studio", () => {
  test.beforeEach(async ({ page, isMobile }) => {
    const email = process.env.E2E_ADMIN_EMAIL;
    const password = process.env.E2E_ADMIN_PASSWORD;
    test.skip(!email || !password, "staff credentials not provided");
    test.skip(isMobile, "desktop tool");
    await login(page, email!, password!);
  });

  test("modules → create quest draft → validate → dependencies → publish → history", async ({ page }) => {
    await page.goto("/admin/content");
    await expect(page.getByTestId("content-modules")).toContainText("Quests");
    await page.getByTestId("type-quest").click();
    await expect(page).toHaveURL(/\/admin\/content\/quest$/);
    const code = `e2e_quest_${Date.now()}`;
    await page.getByText("Create new").click();
    await page.getByLabel("Code", { exact: true }).fill(code);
    await page.getByLabel("Data (JSON)").fill(JSON.stringify({ quest_type: "kill", prerequisites: ["first_steps"], objectives: [{ kind: "kill", count: 5 }] }));
    await page.getByTestId("create-entity").click();
    await expect(page).toHaveURL(new RegExp(`/admin/content/quest/${code}$`));
    await page.getByTestId("validate").click();
    await expect(page.getByText("No validation issues.")).toBeVisible();
    await page.getByTestId("editor-tab-references").click();
    await expect(page.getByTestId("references")).toContainText("quest:first_steps");
    await page.getByTestId("editor-tab-workflow").click();
    await expect(page.getByTestId("workflow-stage")).toContainText("request a review");
    await page.getByTestId("publish").click();
    await expect(page.getByTestId("workflow-stage")).toContainText("Live for players");
    await page.getByTestId("editor-tab-history").click();
    await expect(page.getByTestId("history")).toContainText("r1");
    // first_steps is now referenced by the new quest: archiving asks for confirmation (dismiss keeps it live)
    await page.goto("/admin/content/quest/first_steps");
    await page.getByTestId("editor-tab-references").click();
    await expect(page.getByTestId("references")).toContainText(code);
  });

  test("localization dashboard shows per-locale completion and an import dry run", async ({ page }) => {
    await page.goto("/admin/localization");
    await expect(page.getByTestId("l10n-completion")).toContainText("zh-CN");
    await page.getByTestId("ns-filter").selectOption("quest");
    await page.getByLabel("Import JSON").fill(JSON.stringify([{ key: "quest.first_steps.name", locale: "tr", value: "İlk Adımlar", status: "draft" }]));
    await page.getByTestId("import-dry").click();
    await expect(page.getByTestId("import-report")).toContainText("[dry run]");
  });
});
