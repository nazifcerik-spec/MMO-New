import { expect, test } from "@playwright/test";

import { login, register } from "./helpers";

test("anonymous users are redirected from /game and /admin to /login", async ({ page }) => {
  await page.goto("/game");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login$/);
});

test("register, see empty character list, logout, login again", async ({ page }) => {
  const creds = await register(page);
  await expect(page.getByTestId("logout")).toBeVisible();
  await expect(page.getByRole("region", { name: "Your characters" })).toBeVisible();
  await page.getByTestId("logout").click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, creds.email, creds.password);
});

test("wrong password shows localized error", async ({ page }) => {
  const creds = await register(page);
  await page.getByTestId("logout").click();
  await page.getByLabel("Email").fill(creds.email);
  await page.getByLabel("Password").fill("definitely-wrong-1");
  await page.getByRole("button", { name: /^log in$/i }).last().click();
  await expect(page.getByTestId("auth-error")).toHaveText("Invalid email or password.");
});

test("character wizard validates name and renders content-driven options", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  await page.getByLabel("Character name").fill("Admin");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByTestId("name-error")).toHaveText("That name is reserved.");
  await page.getByLabel("Character name").fill(`Hero${String.fromCharCode(97 + Math.floor(Math.random() * 26))}zed`);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  // Race step renders the 8 published races as localized cards with effect summaries.
  await expect(page.getByRole("radio")).toHaveCount(8);
  await expect(page.getByTestId("option-dwarf")).toContainText("Stoneborn");
  await expect(page.getByTestId("option-dwarf")).toContainText("Vitality +5%");
  await page.getByTestId("option-dwarf").click();
  await expect(page.getByTestId("option-dwarf")).toHaveAttribute("aria-checked", "true");
});

test("player cannot enter admin; staff can", async ({ page, browser }) => {
  await register(page);
  await page.goto("/admin");
  await expect(page.getByTestId("admin-forbidden")).toBeVisible();

  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  test.skip(!email || !password, "staff credentials not provided");
  const ctx = await browser.newContext();
  const staff = await ctx.newPage();
  await login(staff, email!, password!);
  await staff.goto("/admin");
  await expect(staff.getByTestId("admin-roles")).toContainText("admin");
  await ctx.close();
});
