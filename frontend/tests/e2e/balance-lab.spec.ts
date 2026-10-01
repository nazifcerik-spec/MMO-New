import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("balance lab: simulate and run the support checker (desktop admin)", async ({ page, isMobile }) => {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  test.skip(!email || !password || isMobile, "staff credentials / desktop only");
  await login(page, email!, password!);
  await page.goto("/admin/balance");
  await page.getByLabel("Iterations").fill("2");
  await page.getByLabel("Duration (s)").fill("3600");
  await page.getByTestId("run-sim").click();
  await expect(page.getByTestId("sim-result")).toContainText("XP / hour", { timeout: 30_000 });
  await expect(page.getByTestId("telemetry")).toContainText("Onboarding funnel");
});
