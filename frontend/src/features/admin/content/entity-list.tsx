"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { contentApi } from "@/lib/api/admin-content";
import { useErrorMessage } from "@/lib/api/errors";

/** Generic list for one content type: search, status filter, paging, create. */
export function EntityList({ type }: { type: string }) {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useQuery({ queryKey: ["content-list", type, search, status, offset], queryFn: () => contentApi.list(type, { search: search || undefined, status: status || undefined, offset }) });
  const [code, setCode] = useState("");
  const [json, setJson] = useState("{}");
  const create = useMutation({
    mutationFn: () => contentApi.create(type, code.trim(), JSON.parse(json)),
    onSuccess: () => router.push(`/admin/content/${type}/${encodeURIComponent(code.trim())}`),
    onError: (e) => toast("error", e instanceof SyntaxError ? t("badJson") : errorMessage(e)),
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-sm">
        <input aria-label={t("search")} placeholder={t("search")} value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} className="rounded border border-border bg-bg px-2 py-1" />
        <select aria-label={t("status")} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="rounded border border-border bg-bg px-2 py-1">
          <option value="">{t("anyStatus")}</option>
          {["draft", "published", "disabled", "archived"].map((s) => (
            <option key={s} value={s}>
              {t(`stage.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <table className="w-full text-sm" data-testid="entity-table">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th>{t("code")}</th>
            <th>{t("status")}</th>
            <th>{t("revision")}</th>
          </tr>
        </thead>
        <tbody>
          {(q.data?.items ?? []).map((r) => (
            <tr key={r.code} className="border-t border-border">
              <td>
                <Link href={`/admin/content/${type}/${encodeURIComponent(r.code)}`} className="underline">
                  {r.code}
                </Link>
              </td>
              <td>{t(`stage.${r.status}`)}</td>
              <td>r{r.revision_no}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.data ? (
        <p className="flex items-center gap-2 text-xs">
          {t("showing", { from: q.data.total ? offset + 1 : 0, to: Math.min(offset + 50, q.data.total), total: q.data.total })}
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))} className="underline disabled:opacity-40">
            {t("prev")}
          </button>
          <button type="button" disabled={offset + 50 >= q.data.total} onClick={() => setOffset(offset + 50)} className="underline disabled:opacity-40">
            {t("next")}
          </button>
        </p>
      ) : null}
      <details className="rounded border border-border p-2 text-sm">
        <summary>{t("create")}</summary>
        <div className="mt-2 space-y-2">
          <input aria-label={t("code")} placeholder="new_code" value={code} onChange={(e) => setCode(e.target.value)} className="w-full rounded border border-border bg-bg px-2 py-1 font-mono" />
          <textarea aria-label={t("data")} value={json} onChange={(e) => setJson(e.target.value)} rows={8} className="w-full rounded border border-border bg-bg p-2 font-mono text-xs" />
          <button type="button" data-testid="create-entity" disabled={!code.trim() || create.isPending} onClick={() => create.mutate()} className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50">
            {t("createDraft")}
          </button>
        </div>
      </details>
    </div>
  );
}
