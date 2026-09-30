import { expect, test } from "@playwright/test";

test("home renders and reaches backend health", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-state", "ok");
});

test.describe("route shells", () => {
  for (const path of ["/login"]) {
    test(`renders ${path}`, async ({ page }) => {
      const res = await page.goto(path);
      expect(res?.status()).toBeLessThan(400);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    });
  }
});
