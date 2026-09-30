import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/i18n/language-switcher";
import { LogoutButton } from "@/features/auth/logout-button";
import type { Me } from "@/lib/api/auth";
import { serverApi } from "@/lib/api/server";

export async function SiteHeader() {
  const t = await getTranslations();
  const me = await serverApi<Me>("/auth/me").catch(() => null);
  return (
    <header className="border-b border-border bg-panel">
      <nav aria-label="Primary" className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/" className="font-mono font-bold text-accent">
          {t("common.appName")}
        </Link>
        <ul className="flex flex-wrap items-center gap-3 text-sm">
          <li>
            <Link href="/game" className="hover:underline">
              {t("nav.game")}
            </Link>
          </li>
          {me?.is_staff ? (
            <li>
              <Link href="/admin" className="hover:underline">
                {t("nav.admin")}
              </Link>
            </li>
          ) : null}
          <li>
            {me ? (
              <LogoutButton />
            ) : (
              <Link href="/login" className="hover:underline">
                {t("nav.login")}
              </Link>
            )}
          </li>
        </ul>
        <div className="ml-auto flex items-center gap-3">
          {me ? (
            <span className="hidden text-xs text-muted sm:inline" data-testid="whoami">
              {t("auth.loggedInAs", { email: me.email })}
            </span>
          ) : null}
          <LanguageSwitcher />
        </div>
      </nav>
    </header>
  );
}
