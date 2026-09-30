import Link from "next/link";
import { getTranslations } from "next-intl/server";

export async function SiteHeader() {
  const t = await getTranslations();
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
          <li>
            <Link href="/admin" className="hover:underline">
              {t("nav.admin")}
            </Link>
          </li>
          <li>
            <Link href="/login" className="hover:underline">
              {t("nav.login")}
            </Link>
          </li>
        </ul>
      </nav>
    </header>
  );
}
