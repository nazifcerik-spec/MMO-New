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
