export const LOCALES = ["en", "tr", "zh-CN", "es"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "locale";

export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  tr: "Türkçe",
  "zh-CN": "简体中文",
  es: "Español",
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/** Resolve a locale from an explicit value or an Accept-Language header; falls back to `en`. */
export function resolveLocale(explicit?: string | null, acceptLanguage?: string | null): Locale {
  if (isLocale(explicit)) return explicit;
  if (acceptLanguage) {
    const tags = acceptLanguage
      .split(",")
      .map((part) => part.split(";")[0].trim())
      .filter(Boolean);
    for (const tag of tags) {
      if (isLocale(tag)) return tag;
      const lower = tag.toLowerCase();
      if (lower.startsWith("zh")) return "zh-CN";
      const base = lower.split("-")[0];
      if (isLocale(base)) return base;
    }
  }
  return DEFAULT_LOCALE;
}
