import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { newCharacter } from "./helpers";

// WCAG 2.1 A/AA automated checks (keyboard/focus/ARIA/contrast) on the core player screens.
test("core screens have no serious or critical axe violations", async ({ page }) => {
  const id = await newCharacter(page, "Ally");
  for (const path of ["", "/afk", "/inventory", "/professions", "/market", "/party", "/goals", "/settings"]) {
    await page.goto(`/game/characters/${id}${path}`);
    await expect(page.getByTestId("identity-bar")).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${path || "/"}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
  }
});
