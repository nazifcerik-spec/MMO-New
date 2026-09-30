import { expect, test } from "@playwright/test";

const HOME_TITLE: Record<string, string> = {
  en: "Oldschool AFK Text MMO",
  tr: "Oldschool AFK Metin MMO",
  "zh-CN": "复古挂机文字MMO",
  es: "MMO de Texto AFK Clásico",
};

test("language switch persists across reloads", async ({ page }) => {
  await page.goto("/");
  for (const locale of ["tr", "zh-CN", "es", "en"]) {
    await page.getByTestId("language-switcher").selectOption(locale);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(HOME_TITLE[locale]);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(HOME_TITLE[locale]);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
  }
});

test("Accept-Language is honoured without a cookie", async ({ browser }) => {
  const ctx = await browser.newContext({ locale: "es-ES" });
  const page = await ctx.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(HOME_TITLE.es);
  await ctx.close();
});

for (const locale of ["zh-CN", "tr", "es"]) {
  test(`no horizontal overflow in ${locale}`, async ({ page, context }) => {
    await context.addCookies([{ name: "locale", value: locale, url: page.url() === "about:blank" ? "http://localhost:3000" : page.url() }]);
    for (const path of ["/", "/login", "/game", "/admin"]) {
      await page.goto(path);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
    }
  });
}
