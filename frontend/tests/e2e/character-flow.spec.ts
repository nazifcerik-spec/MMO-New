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
  await expect(page.getByTestId("ability-list")).toContainText("Shield Slam");

  await page.goto(`/game/characters/${characterId}/talents`);
  await expect(page.getByTestId("tree-warrior_defense")).toBeVisible();
  await page.getByTestId("node-warrior_defense_n1").getByRole("button").click();
  await page.getByRole("button", { name: "Learn talents" }).click();
  await expect(page.getByTestId("node-warrior_defense_n1")).toContainText("Rank 1/5");

  await page.goto(`/game/characters/${characterId}`);
  await page.getByTestId("open-afk").click();
  await page.getByTestId("preset-safe_farmer").click();
  await expect(page.getByTestId("preset-safe_farmer")).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Show advanced settings" }).click();
  await page.getByLabel("Combat mode").selectOption("PASSIVE_ONLY");
  await page.getByTestId("afk-save").click();
  await expect(page.getByTestId("preset-safe_farmer")).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("afk-run-preview").click();
  await expect(page.getByTestId("preview-win-rate")).toHaveText(/\d+%/);
});

test("active tactics priority editor: template, reorder, simulate, save", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Tac${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByTestId("open-afk").click();
  await page.getByRole("button", { name: "Show advanced settings" }).click();
  const editor = page.getByTestId("tactics-editor");
  await expect(editor).toBeVisible();
  await page.getByRole("button", { name: "+ rule" }).click();
  await page.getByRole("button", { name: "+ rule" }).click();
  await expect(editor.getByTestId(/^tactic-rule-/)).toHaveCount(2);
  await page.getByLabel("Rule 2: use").selectOption("tag:single_target");
  await page.getByRole("button", { name: "Move rule 2 up" }).click();
  await expect(page.getByLabel("Rule 1: use")).toHaveValue("tag:single_target");
  await page.getByTestId("tactics-preview").click();
  await expect(page.getByTestId("tactics-preview-result")).toBeVisible();
  await expect(page.getByTestId("tactic-uses-0")).toContainText(/\d+/);
  await page.getByTestId("tactics-save").click();
  await page.reload();
  await page.getByRole("button", { name: "Show advanced settings" }).click();
  await expect(page.getByLabel("Rule 1: use")).toHaveValue("tag:single_target");
});

test("zone browser shows eligibility, details and a real-encounter preview", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Zon${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-paladin").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByTestId("open-zones").click();
  await expect(page.getByTestId("zone-locked-mistfen_marsh")).toContainText("Level 50");
  await page.getByTestId("zone-whispering_meadows").click();
  await expect(page.getByTestId("boss-old_greymane")).toContainText("Old Greymane");
  await page.getByTestId("zone-preview").click();
  await expect(page.getByTestId("zone-win-rate")).toHaveText(/\d+%/);
});

test("AFK session: start, countdown, stop early, claim summary", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Afk${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByTestId("afk-start").click();
  await expect(page.getByTestId("afk-countdown")).toHaveText(/^[0-2]:\d\d:\d\d$/);
  await expect(page.getByTestId("afk-claim")).toBeDisabled();
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("afk-stop").click();
  await expect(page.getByTestId("afk-claim")).toBeEnabled();
  await page.getByTestId("afk-claim").click();
  await expect(page.getByTestId("afk-claim-summary")).toBeVisible();
  await expect(page.getByTestId("signal-pity_progress")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByTestId("afk-start")).toBeVisible();
});

test("inventory: staff-granted item is equipped server-side and stats update", async ({ page, baseURL }) => {
  const admin = await adminApi(baseURL!);
  test.skip(!admin, "staff credentials not provided");
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Inv${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/game\/characters\/\d+$/);
  const characterId = Number(page.url().split("/").pop());
  const grant = await admin!.ctx.post(`/api/v1/admin/characters/${characterId}/items`, {
    data: { template_code: "worn_training_sword", reason: "e2e" },
    headers: { "X-CSRF-Token": admin!.csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(grant.ok(), await grant.text()).toBeTruthy();
  await page.getByTestId("open-inventory").click();
  const before = await page.getByTestId("stat-attack_power").innerText();
  await page.getByTestId("bag-item-worn_training_sword").click();
  await expect(page.getByTestId("item-tooltip")).toContainText("Worn Training Sword");
  await expect(page.getByTestId("tooltip-delta")).toContainText("+");
  await page.getByTestId("equip").click();
  await expect(page.getByTestId("slot-main_hand")).toContainText("Worn Training Sword");
  await expect(page.getByTestId("stat-attack_power")).not.toHaveText(before);
  await page.getByRole("button", { name: "Remove item from main_hand" }).click();
  await expect(page.getByTestId("stat-attack_power")).toHaveText(before);
});

test("professions: activate and revoke a Specialist License", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Prf${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-dwarf").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByTestId("open-professions").click();
  await expect(page.getByTestId("profession-mining")).toContainText("+8% speed"); // dwarf racial via effect registry
  await page.getByTestId("license-mining").click();
  await expect(page.getByTestId("license-summary")).toContainText("1/3");
  await expect(page.getByTestId("prof-level-mining")).toContainText("Lv 1/500");
  page.once("dialog", (d) => d.accept());
  await page.getByTestId("license-mining").click();
  await expect(page.getByTestId("license-summary")).toContainText("0/3");
});

test("crafting: staff-granted ore is reserved into a queued craft job", async ({ page, baseURL }) => {
  const admin = await adminApi(baseURL!);
  test.skip(!admin, "staff credentials not provided");
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Crf${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/game\/characters\/\d+$/);
  const characterId = Number(page.url().split("/").pop());
  const grant = await admin!.ctx.post(`/api/v1/admin/characters/${characterId}/items`, {
    data: { template_code: "copper_ore", quantity: 6, reason: "e2e" },
    headers: { "X-CSRF-Token": admin!.csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(grant.ok(), await grant.text()).toBeTruthy();
  await page.getByTestId("open-professions").click();
  await page.getByTestId("craft-profession").selectOption("blacksmithing");
  const row = page.getByTestId("recipe-smelt_iron_ingot");
  await expect(row).toContainText("Copper Ore 6/3");
  await page.getByTestId("craft-smelt_iron_ingot").click();
  await expect(page.getByTestId("craft-queue")).toContainText("smelt_iron_ingot ×1");
  await expect(row).toContainText("Copper Ore 3/3");
});

test("market: list a staff-granted item, see it in My listings and cancel (escrow returns it)", async ({ page, baseURL }) => {
  const admin = await adminApi(baseURL!);
  test.skip(!admin, "staff credentials not provided");
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Mkt${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/game\/characters\/\d+$/);
  const characterId = Number(page.url().split("/").pop());
  for (const [code, qty] of [["iron_ingot", 3]] as const) {
    const grant = await admin!.ctx.post(`/api/v1/admin/characters/${characterId}/items`, {
      data: { template_code: code, quantity: qty, reason: "e2e" },
      headers: { "X-CSRF-Token": admin!.csrf, "Idempotency-Key": crypto.randomUUID() },
    });
    expect(grant.ok(), await grant.text()).toBeTruthy();
  }
  const gold = await admin!.ctx.post(`/api/v1/admin/characters/${characterId}/gold`, {
    data: { amount: 100, reason: "e2e" },
    headers: { "X-CSRF-Token": admin!.csrf, "Idempotency-Key": crypto.randomUUID() },
  });
  expect(gold.ok(), await gold.text()).toBeTruthy();
  await page.getByTestId("open-inventory").click();
  await page.getByTestId("bag-item-iron_ingot").click();
  await page.getByTestId("list-item").click();
  await page.goto(`/game/characters/${characterId}/market`);
  await page.getByTestId("tab-mine").click();
  const row = page.locator('[data-testid^="listing-"]').first();
  await expect(row).toContainText("Iron Ingot");
  await row.locator('[data-testid^="cancel-"]').click();
  await expect(row).toContainText("Cancelled");
});

test("party: create a party and post to party chat", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `Pty${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
  await page.getByLabel("Character name").fill(name);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Name is available.")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-human").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByTestId("option-warrior").click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/game$/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await page.getByTestId("open-party").click();
  await page.getByTestId("create-party").click();
  await expect(page.getByTestId("party-members")).toContainText(name);
  await page.getByLabel("Message").fill("ready for the meadows");
  await page.getByTestId("send-chat").click();
  await expect(page.getByTestId("party-chat")).toContainText("ready for the meadows");
});
