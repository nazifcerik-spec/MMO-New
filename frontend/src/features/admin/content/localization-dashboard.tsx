"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { l10nAdminApi } from "@/lib/api/admin-content";
import { useErrorMessage } from "@/lib/api/errors";
import { LOCALES } from "@/lib/i18n/config";

/** Per-locale completion, missing-key worklist and JSON export/import (dry-run first). */
export function LocalizationDashboard() {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const [ns, setNs] = useState("");
  const [missing, setMissing] = useState("tr");
  const namespaces = useQuery({ queryKey: ["l10n-ns"], queryFn: l10nAdminApi.namespaces });
  const dash = useQuery({ queryKey: ["l10n-dash", ns], queryFn: () => l10nAdminApi.dashboard(ns || undefined) });
  const keys = useQuery({ queryKey: ["l10n-missing", ns, missing], queryFn: () => l10nAdminApi.keys({ namespace: ns || undefined, missing_locale: missing }) });
  const [importText, setImportText] = useState("");
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const doImport = useMutation({
    mutationFn: (dry: boolean) => l10nAdminApi.import((JSON.parse(importText) as { rows?: unknown[] }).rows ?? (JSON.parse(importText) as unknown[]), dry),
    onSuccess: (r) => setReport(r),
    onError: (e) => toast("error", e instanceof SyntaxError ? t("badJson") : errorMessage(e)),
  });
  const download = async () => {
    try {
      const data = await l10nAdminApi.exportJson(ns || undefined);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `translations-${ns || "all"}.json` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast("error", errorMessage(e));
    }
  };
  return (
    <div className="space-y-4 text-sm">
      <label className="flex items-center gap-2">
        {t("namespace")}
        <select value={ns} onChange={(e) => setNs(e.target.value)} className="rounded border border-border bg-bg px-2 py-1" data-testid="ns-filter">
          <option value="">{t("allNamespaces")}</option>
          {(namespaces.data ?? []).map((n) => (
            <option key={n.namespace} value={n.namespace}>
              {n.namespace} ({n.keys})
            </option>
          ))}
        </select>
      </label>
      <table className="w-full text-sm" data-testid="l10n-completion">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th>{t("locale")}</th>
            <th>{t("complete")}</th>
            <th className="text-right">{t("missingCol")}</th>
            <th className="text-right">{t("stage.draft")}</th>
            <th className="text-right">{t("reviewedCol")}</th>
            <th className="text-right">{t("stage.published")}</th>
          </tr>
        </thead>
        <tbody>
          {LOCALES.map((loc) => {
            const s = dash.data?.locales[loc];
            return (
              <tr key={loc} className="border-t border-border">
                <td className="font-mono">{loc}</td>
                <td>
                  <span className="mr-2">{s ? `${s.present_pct}% / ${s.reviewed_pct}%` : "…"}</span>
                  <span className="inline-block h-1.5 w-24 rounded bg-border align-middle" role="progressbar" aria-valuenow={s?.present_pct ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={loc}>
                    <span className="block h-1.5 rounded bg-accent" style={{ width: `${s?.present_pct ?? 0}%` }} />
                  </span>
                </td>
                <td className="text-right">{s?.missing ?? "…"}</td>
                <td className="text-right">{s?.draft ?? "…"}</td>
                <td className="text-right">{s?.reviewed ?? "…"}</td>
                <td className="text-right">{s?.published ?? "…"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <section className="space-y-1">
        <label className="flex items-center gap-2">
          {t("missingIn")}
          <select value={missing} onChange={(e) => setMissing(e.target.value)} className="rounded border border-border bg-bg px-2 py-1">
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted">{t("missingCount", { n: keys.data?.total ?? 0 })}</span>
        </label>
        <ul className="max-h-48 overflow-y-auto font-mono text-xs" data-testid="missing-keys">
          {(keys.data?.items ?? []).map((k) => (
            <li key={k.key}>
              {k.key} — <span className="text-muted">{k.values.en?.value}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="space-y-2">
        <button type="button" onClick={() => void download()} className="rounded border border-border px-2 py-1" data-testid="export-json">
          {t("exportJson")}
        </button>
        <textarea aria-label={t("importJson")} placeholder={t("importPlaceholder")} value={importText} onChange={(e) => setImportText(e.target.value)} rows={5} className="w-full rounded border border-border bg-bg p-2 font-mono text-xs" />
        <div className="flex gap-2">
          <button type="button" disabled={!importText.trim()} onClick={() => doImport.mutate(true)} className="rounded border border-border px-2 py-1 disabled:opacity-50" data-testid="import-dry">
            {t("dryRun")}
          </button>
          <button type="button" disabled={!report || !report.dry_run} onClick={() => doImport.mutate(false)} className="rounded bg-accent px-2 py-1 font-semibold text-bg disabled:opacity-50">
            {t("applyImport")}
          </button>
        </div>
        {report ? (
          <p className="text-xs" data-testid="import-report">
            {t("importReport", { created: String(report.created), updated: String(report.updated), skipped: String(report.skipped_reviewed), unknown: String(report.unknown_key), dry: report.dry_run ? t("dryRunLabel") : "" })}
          </p>
        ) : null}
      </section>
    </div>
  );
}
