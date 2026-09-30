import { expect, request, test } from "@playwright/test";

import { register } from "./helpers";

async function adminApi(baseURL: string) {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!email || !password) return null;
  const ctx = await request.newContext({ baseURL });
  const res = await ctx.post("/api/v1/auth/login", { data: { email, password } });
  expect(res.ok()).toBeTruthy();
  const csrf = (await ctx.storageState()).cookies.find((c) => c.name === "csrf_token")?.value ?? "";
  return { ctx, csrf };
}

test("create character, allocate stats, promote at Lv100", async ({ page, baseURL }) => {
  const admin = await adminApi(baseURL!);
  test.skip(!admin, "staff credentials not provided");
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Dur${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-dwarf").click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("radio")).toHaveCount(10);
  await expect(page.getByTestId("option-cleric")).toContainText("Solo Accord");
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByTestId("wizard-summary")).toContainText(`${name} — Dwarf Warrior`);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);

  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page.getByTestId("level-heading")).toContainText("[Novice] Level 1 / 1000");
  const characterId = Number(page.url().split("/").pop());

  // Server-authoritative XP grant (staff API) to reach Lv100.
  // Ask for plenty of XP; the server computes the resulting level.
  const grant = await admin!.ctx.post(`/api/v1/admin/characters/${characterId}/xp`, {
    data: { amount: 5_000_000, reason: "e2e" },
    headers: { "X-CSRF-Token": admin!.csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(grant.ok()).toBeTruthy();
  await page.reload();
  const level = (await (await page.request.get(`/api/v1/characters/${characterId}/progression`)).json()).level;
  expect(level).toBeGreaterThanOrEqual(100);

  const before = await page.getByTestId("unspent").innerText();
  await page.getByRole("button", { name: /^Increase Strength/ }).click();
  await page.getByRole("button", { name: "Allocate" }).click();
  await expect(page.getByTestId("unspent")).not.toHaveText(before);

  await page.getByTestId("open-class").click();
  await expect(page.getByTestId("class-tree")).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("branch-guardian").getByRole("button").click();
  await expect(page.getByTestId("class-title")).toContainText("Guardian");
});
