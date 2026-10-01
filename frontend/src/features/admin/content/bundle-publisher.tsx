"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { contentApi, type Issue } from "@/lib/api/admin-content";
import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";

/** Publish bundle: related drafts (e.g. class + skill + talent) go live atomically under one release. */
export function BundlePublisher() {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["content-pending"], queryFn: contentApi.pending });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [label, setLabel] = useState("");
  const [ack, setAck] = useState(false);
  const [problems, setProblems] = useState<Record<string, Issue[]> | null>(null);
  const pub = useMutation({
    mutationFn: () =>
      contentApi.publish(
        [...picked].map((k) => {
          const [entity_type, code] = k.split(":");
          return { entity_type, code };
        }),
        label || undefined,
        ack,
      ),
    onSuccess: (r) => {
      toast("success", t("bundlePublished", { v: r.release_version, n: picked.size }));
      setPicked(new Set());
      setProblems(null);
      qc.invalidateQueries({ queryKey: ["content-pending"] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "publish_blocked") setProblems(e.details as Record<string, Issue[]>);
      toast("error", errorMessage(e));
    },
  });
  const toggle = (k: string) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    return n;
  });
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted">{t("bundleHelp")}</p>
      <ul className="space-y-1" data-testid="pending-list">
        {(q.data ?? []).map((r) => {
          const k = `${r.entity_type}:${r.code}`;
          return (
            <li key={k} className="flex items-center gap-2">
              <input type="checkbox" aria-label={k} checked={picked.has(k)} onChange={() => toggle(k)} />
              <Link href={`/admin/content/${r.entity_type}/${encodeURIComponent(r.code)}`} className="underline">
                {k}
              </Link>
              <span className="text-xs text-muted">{r.new ? t("newEntity") : t("changed")}</span>
              {problems?.[k] ? <span className="text-xs text-bad">{problems[k].map((i) => i.message).join("; ")}</span> : null}
            </li>
          );
        })}
        {q.data && !q.data.length ? <li className="text-muted">{t("nothingPending")}</li> : null}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label={t("releaseLabel")} placeholder={t("releaseLabel")} value={label} onChange={(e) => setLabel(e.target.value)} className="rounded border border-border bg-bg px-2 py-1" />
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          {t("ackWarnings")}
        </label>
        <button type="button" data-testid="publish-bundle" disabled={!picked.size || pub.isPending} onClick={() => pub.mutate()} className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50">
          {t("publishBundle", { n: picked.size })}
        </button>
      </div>
    </div>
  );
}
