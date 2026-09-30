import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE, LOCALE_COOKIE, resolveLocale } from "./config";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const headerStore = await headers();
  const locale = resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerStore.get("accept-language"));
  const messages = (await import(`../../../messages/${locale}.json`)).default;
  const fallback =
    locale === DEFAULT_LOCALE ? messages : (await import(`../../../messages/${DEFAULT_LOCALE}.json`)).default;
  return {
    locale,
    messages: deepMerge(fallback, messages),
    timeZone: "UTC",
    // Missing keys fall back to English (merged above); last resort is the key path itself.
    getMessageFallback: ({ key, namespace }) => [namespace, key].filter(Boolean).join("."),
    onError: () => {},
  };
});

type Messages = { [key: string]: string | Messages };

function deepMerge(base: Messages, override: Messages): Messages {
  const out: Messages = { ...base };
  for (const [k, v] of Object.entries(override)) {
    const b = out[k];
    out[k] = typeof v === "object" && typeof b === "object" ? deepMerge(b, v) : v;
  }
  return out;
}
