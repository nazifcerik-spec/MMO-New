"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { contentApi } from "@/lib/api/admin-content";

/** Content Studio home: every module with per-status counts and pending drafts. */
export function ContentHome() {
  const t = useTranslations("contentStudio");
  const tc = useTranslations("common");
  const q = useQuery({ queryKey: ["content-modules"], queryFn: contentApi.modules });
  if (q.isLoading) return <p>{tc("loading")}</p>;
  if (!q.data) return <p role="alert">{tc("error")}</p>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm">
        <Link href="/admin/content/bundle" className="underline" data-testid="open-bundle">
          {t("bundle")}
        </Link>
        <Link href="/admin/localization" className="underline" data-testid="open-l10n-dashboard">
          {t("localization")}
        </Link>
        <Link href="/admin/items" className="underline">
          {t("itemStudio")}
        </Link>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="content-modules">
        {q.data.map((m) => (
          <li key={m.module} className="rounded border border-border bg-panel p-3">
            <h2 className="font-semibold">{t(`module.${m.module}`)}</h2>
            <ul className="mt-1 space-y-0.5 text-sm">
              {m.types.map((ty) => (
                <li key={ty.entity_type} className="flex flex-wrap items-center gap-2">
                  <Link href={ty.entity_type === "item_template" ? "/admin/items" : `/admin/content/${ty.entity_type}`} className="underline" data-testid={`type-${ty.entity_type}`}>
                    {ty.entity_type}
                  </Link>
                  <span className="text-xs text-muted">{t("counts", { published: ty.counts.published ?? 0, draft: ty.counts.draft ?? 0 })}</span>
                  {ty.pending_drafts ? <span className="rounded bg-accent px-1 text-xs text-bg">{t("pending", { n: ty.pending_drafts })}</span> : null}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
