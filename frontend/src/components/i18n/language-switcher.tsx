"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useId, useTransition } from "react";

import { apiFetch } from "@/lib/api/client";
import { LOCALE_COOKIE, LOCALE_LABELS, LOCALES, isLocale, type Locale } from "@/lib/i18n/config";

/** Persists the locale in a first-party cookie (read by both Next.js and the API) and refreshes server components. */
export function LanguageSwitcher() {
  const t = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();

  function change(next: Locale) {
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    // Best effort: also let the server set it (and later persist to user settings when logged in).
    apiFetch("/i18n/preference", { method: "PUT", body: { locale: next } }).catch(() => undefined);
    startTransition(() => router.refresh());
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={id} className="text-muted">
        {t("language")}
      </label>
      <select
        id={id}
        data-testid="language-switcher"
        value={locale}
        disabled={pending}
        onChange={(e) => isLocale(e.target.value) && change(e.target.value)}
        className="rounded border border-border bg-panel px-2 py-1"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l} lang={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </select>
    </div>
  );
}
