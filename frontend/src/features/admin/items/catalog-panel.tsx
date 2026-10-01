"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useToast } from "@/components/ui/toast";
import { adminItemsApi } from "@/lib/api/admin-items";
import { useErrorMessage } from "@/lib/api/errors";

/** Launch catalog (1,520 templates): server-side dry-run through the real validators, then draft/publish commit. */
export function CatalogPanel() {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const dry = useMutation({ mutationFn: adminItemsApi.catalogDryRun, onError: (e) => toast("error", errorMessage(e)) });
  const commit = useMutation({
    mutationFn: (publish: boolean) => adminItemsApi.catalogCommit(publish),
    onSuccess: (r) => toast("success", t("catalogCommitted", { created: r.created, published: r.published, skipped: r.skipped_existing })),
    onError: (e) => toast("error", errorMessage(e)),
  });
  const s = dry.data;
  return (
    <section aria-label={t("catalogTitle")} className="space-y-2 rounded border border-border bg-panel p-3" data-testid="catalog-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{t("catalogTitle")}</h2>
        <button type="button" data-testid="catalog-dry-run" className="ml-auto rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg disabled:opacity-50" disabled={dry.isPending} onClick={() => dry.mutate()}>
          {dry.isPending ? t("catalogRunning") : t("catalogDryRun")}
        </button>
      </div>
      <p className="text-xs text-muted">{t("catalogHint")}</p>
      {s ? (
        <div className="space-y-1 text-sm" data-testid="catalog-summary">
          <p className={s.matches_targets && !s.errors ? "text-good" : "text-bad"}>
            {t("catalogTotals", { total: s.distribution.total, target: s.target_total, errors: s.errors, warnings: s.warnings })}
          </p>
          <ul className="grid grid-cols-2 gap-x-4 text-xs md:grid-cols-3">
            {Object.entries(s.targets).map(([c, n]) => (
              <li key={c}>
                {t(`category.${c}`)}: {s.distribution.by_category[c] ?? 0}/{n}
              </li>
            ))}
          </ul>
          <p className="text-xs">{t("catalogOutliers", { n: s.outliers.length })}</p>
          <div className="flex gap-2">
            <button type="button" className="underline disabled:opacity-50" disabled={!!s.errors || commit.isPending} onClick={() => commit.mutate(false)}>
              {t("catalogCommitDrafts")}
            </button>
            <button type="button" className="underline disabled:opacity-50" disabled={!!s.errors || commit.isPending} onClick={() => window.confirm(t("catalogPublishConfirm")) && commit.mutate(true)}>
              {t("catalogCommitPublish")}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
