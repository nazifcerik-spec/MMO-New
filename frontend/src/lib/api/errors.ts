"use client";

import { useTranslations } from "next-intl";

import { ApiError } from "./client";

/** Map an API error code to a localized message (falls back to `errors.unknown`). */
export function useErrorMessage() {
  const t = useTranslations("errors");
  return (err: unknown): string => {
    const code =
      err instanceof ApiError
        ? err.code
        : typeof err === "object" && err !== null && "code" in err && typeof err.code === "string"
          ? err.code
          : "unknown";
    return t.has(code) ? t(code) : t("unknown");
  };
}
