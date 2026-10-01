import { expect, test } from "@playwright/test";

import { newCharacter } from "./helpers";

test("game shell: identity bar, next goals and navigation (desktop side nav / mobile drawer)", async ({ page }, info) => {
  const id = await newCharacter(page, "Shl");
  await expect(page.getByTestId("identity-bar")).toContainText("Lv 1");
  await expect(page.getByTestId("next-goals").locator("visible=true").first()).toBeVisible();
  if (info.project.name === "mobile") {
    await expect(page.getByTestId("nav-inventory")).toBeHidden();
    await page.getByTestId("mnav-inventory").click();
    await expect(page).toHaveURL(new RegExp(`/game/characters/${id}/inventory$`));
    await expect(page.getByTestId("mnav-inventory")).toHaveAttribute("aria-current", "page");
    await page.getByTestId("mnav-more").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.getByTestId("mnav-more").click();
    await page.getByTestId("dnav-market").click();
    await expect(page).toHaveURL(new RegExp(`/game/characters/${id}/market$`));
  } else {
    await page.getByTestId("nav-adventure").click();
    await expect(page).toHaveURL(new RegExp(`/game/characters/${id}/zones$`));
    await expect(page.getByTestId("nav-adventure")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("activity-log")).toBeVisible();
  }
});

test("AFK screen combines session start with stance/target/potion/loot/tactics settings and a readable log", async ({ page }) => {
  const id = await newCharacter(page, "Afk");
  await page.goto(`/game/characters/${id}/afk`);
  await expect(page.getByTestId("afk-start")).toBeVisible();
  await page.getByRole("button", { name: "Show advanced settings" }).click();
  for (const label of [/stance/i, /target/i, /potion/i]) await expect(page.getByLabel(label).first()).toBeVisible();
  await page.getByRole("button", { name: "Simulate 10 fights" }).click();
  await expect(page.getByTestId("combat-log")).toBeVisible();
  await page.getByText("Show fight details").click();
  await expect(page.getByTestId("combat-log")).toContainText(/You (hit|use|defeat)/);
});

test("keyboard: skip link moves focus to the main content", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
});

test("PWA: manifest, icons and service worker", async ({ page, request }) => {
  const m = await request.get("/manifest.webmanifest");
  expect(m.ok()).toBeTruthy();
  const manifest = await m.json();
  expect(manifest.display).toBe("standalone");
  expect(manifest.icons.map((i: { sizes: string }) => i.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
  expect((await request.get("/icons/icon-512.png")).headers()["content-type"]).toContain("image/png");
  const sw = await request.get("/sw.js");
  expect(sw.ok()).toBeTruthy();
  expect(await sw.text()).toContain('req.method !== "GET"');
  await page.goto("/");
  const registered = await page.evaluate(async () => {
    for (let i = 0; i < 20; i++) {
      if (await navigator.serviceWorker.getRegistration()) return true;
      await new Promise((r) => setTimeout(r, 250));
    }
    return false;
  });
  expect(registered).toBe(true);
});

test("offline mode is read-only: banner shown and actions refused locally", async ({ page, context }) => {
  const id = await newCharacter(page, "Off");
  await page.goto(`/game/characters/${id}/goals`);
  await expect(page.getByTestId("accept-first_steps")).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByTestId("offline-banner")).toBeVisible();
  await page.getByTestId("accept-first_steps").click();
  await expect(page.getByText(/You are offline/)).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByTestId("offline-banner")).toBeHidden();
});

for (const locale of ["zh-CN", "tr", "es"]) {
  test(`CJK/long-string layout: no horizontal overflow in game screens (${locale})`, async ({ page, context }) => {
    const id = await newCharacter(page, "Cjk");
    await context.addCookies([{ name: "locale", value: locale, url: page.url() }]);
    for (const path of ["", "/inventory", "/market", "/goals", "/party", "/professions", "/afk", "/settings"]) {
      await page.goto(`/game/characters/${id}${path}`);
      await expect(page.getByTestId("identity-bar")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path || "/"} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
    }
  });
}
