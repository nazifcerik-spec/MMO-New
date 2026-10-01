import { expect, type Page } from "@playwright/test";

export function uniqueEmail(prefix = "p"): string {
  return `${prefix}${Date.now()}${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function register(page: Page, email = uniqueEmail(), password = "e2e-password-123") {
  await page.goto("/login");
  await page.getByRole("tab", { name: /create account/i }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /create account/i }).last().click();
  await expect(page).toHaveURL(/\/game$/);
  return { email, password };
}

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /^log in$/i }).last().click();
  await expect(page).toHaveURL(/\/game$/);
}

/** Register, create a human warrior and land on its character page; returns the character id. */
export async function newCharacter(page: Page, prefix = "Hero"): Promise<number> {
  await register(page);
  await page.getByRole("link", { name: /create character/i }).click();
  const name = `${prefix}${Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8)}`;
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
  return Number(page.url().split("/").pop());
}
