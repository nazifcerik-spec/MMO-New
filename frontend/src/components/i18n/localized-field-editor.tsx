"use client";

import { useTranslations } from "next-intl";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { LOCALE_LABELS, LOCALES, type Locale } from "@/lib/i18n/config";

export type TranslationStatus = "missing" | "draft" | "reviewed" | "published";

export interface LocalizedValue {
  value: string;
  status: TranslationStatus;
  version?: number;
}

export type LocalizedValues = Record<Locale, LocalizedValue>;

export interface LocalizedFieldEditorProps {
  label: string;
  values: LocalizedValues;
  onChange: (locale: Locale, next: LocalizedValue) => void;
  multiline?: boolean;
  maxLength?: number;
  readOnlyLocales?: Locale[];
}

export function emptyLocalizedValues(): LocalizedValues {
  return Object.fromEntries(LOCALES.map((l) => [l, { value: "", status: "missing" }])) as LocalizedValues;
}

export function isMissing(v: LocalizedValue | undefined): boolean {
  return !v || v.status === "missing" || v.value.trim() === "";
}

/** Value a player would see for `locale`: own value -> English -> null (safe label). */
export function fallbackPreview(values: LocalizedValues, locale: Locale): { text: string | null; from: Locale | null } {
  if (!isMissing(values[locale])) return { text: values[locale].value, from: locale };
  if (!isMissing(values.en)) return { text: values.en.value, from: "en" };
  return { text: null, from: null };
}

/** Reusable EN/TR/ZH-CN/ES editor with missing badges and a fallback preview (accessible tabs). */
export function LocalizedFieldEditor({
  label,
  values,
  onChange,
  multiline,
  maxLength,
  readOnlyLocales = [],
}: LocalizedFieldEditorProps) {
  const t = useTranslations("l10nEditor");
  const baseId = useId();
  const [active, setActive] = useState<Locale>("en");
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const current = values[active];
  const preview = fallbackPreview(values, active);
  const readOnly = readOnlyLocales.includes(active);

  function onTabKey(e: KeyboardEvent<HTMLButtonElement>) {
    const idx = LOCALES.indexOf(active);
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = LOCALES[(idx + delta + LOCALES.length) % LOCALES.length];
    setActive(next);
    tabRefs.current[next]?.focus();
  }

  const fieldProps = {
    id: `${baseId}-input`,
    value: current.value,
    maxLength,
    readOnly,
    lang: active,
    "aria-label": `${label} (${LOCALE_LABELS[active]})`,
    className: "w-full rounded border border-border bg-bg p-2 font-sans",
    onChange: (e: { target: { value: string } }) =>
      onChange(active, {
        ...current,
        value: e.target.value.normalize("NFC"),
        status: current.status === "missing" ? "draft" : current.status,
      }),
  };

  return (
    <fieldset className="space-y-2 rounded border border-border p-3" data-testid="localized-field-editor">
      <legend className="px-1 text-sm font-semibold">{label}</legend>
      <div role="tablist" aria-label={label} className="flex flex-wrap gap-1">
        {LOCALES.map((l) => {
          const missing = isMissing(values[l]);
          return (
            <button
              key={l}
              ref={(el) => {
                tabRefs.current[l] = el;
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${l}`}
              aria-selected={active === l}
              aria-controls={`${baseId}-panel`}
              tabIndex={active === l ? 0 : -1}
              onClick={() => setActive(l)}
              onKeyDown={onTabKey}
              className={`rounded px-2 py-1 text-xs ${active === l ? "bg-accent text-bg" : "border border-border"}`}
            >
              {l.toUpperCase()}
              {missing ? (
                <span data-testid={`missing-${l}`} className="ml-1 rounded bg-bad px-1 text-[10px] text-bg">
                  {t("missing")}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-tab-${active}`} className="space-y-2">
        {multiline ? <textarea rows={4} {...fieldProps} /> : <input type="text" {...fieldProps} />}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label htmlFor={`${baseId}-status`}>{t("status")}</label>
          <select
            id={`${baseId}-status`}
            value={current.status}
            disabled={readOnly}
            onChange={(e) => onChange(active, { ...current, status: e.target.value as TranslationStatus })}
            className="rounded border border-border bg-panel px-1"
          >
            {(["missing", "draft", "reviewed", "published"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`statuses.${s}`)}
              </option>
            ))}
          </select>
          {maxLength ? (
            <span className="text-muted">
              {current.value.length}/{maxLength}
            </span>
          ) : null}
        </div>
        <p className="text-xs text-muted" data-testid="fallback-preview">
          {t("preview")}:{" "}
          {preview.text === null ? (
            <em>{t("safeLabel")}</em>
          ) : (
            <>
              <span lang={preview.from ?? undefined}>{preview.text}</span>
              {preview.from !== active ? <span> ({t("fallbackFrom", { locale: preview.from ?? "" })})</span> : null}
            </>
          )}
        </p>
      </div>
    </fieldset>
  );
}
