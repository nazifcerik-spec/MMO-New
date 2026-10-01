"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { LocalizedFieldEditor, emptyLocalizedValues, type LocalizedValues } from "@/components/i18n/localized-field-editor";
import { useToast } from "@/components/ui/toast";
import { contentApi, l10nAdminApi, type Issue, type WorkflowState } from "@/lib/api/admin-content";
import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";
import type { Locale } from "@/lib/i18n/config";

type Tab = "general" | "localization" | "workflow" | "references" | "history";
const STAGES = ["draft", "validation", "review", "published", "archived"] as const;

/** Generic content editor: data (JSON, validated server-side), localization, workflow, dependencies, history. */
export function EntityEditor({ type, code }: { type: string; code: string }) {
  const t = useTranslations("contentStudio");
  const tc = useTranslations("common");
  const [tab, setTab] = useState<Tab>("general");
  const q = useQuery({ queryKey: ["content-entity", type, code], queryFn: () => contentApi.get(type, code) });
  if (q.isLoading) return <p>{tc("loading")}</p>;
  if (!q.data) return <p role="alert">{tc("error")}</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        <Link href={`/admin/content/${type}`} className="underline">
          {type}
        </Link>{" "}
        / <span className="font-mono">{code}</span> · {t(`stage.${q.data.status}`)} · r{q.data.revision_no}
        {q.data.has_pending_changes ? <span className="ml-2 rounded bg-accent px-1 text-xs text-bg">{t("unpublished")}</span> : null}
      </p>
      <div role="tablist" className="flex flex-wrap gap-2 text-sm">
        {(["general", "localization", "workflow", "references", "history"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} data-testid={`editor-tab-${k}`} onClick={() => setTab(k)} className={`rounded px-2 py-1 ${tab === k ? "bg-accent text-bg" : "border border-border"}`}>
            {t(`tab.${k}`)}
          </button>
        ))}
      </div>
      {tab === "general" ? <GeneralTab type={type} code={code} /> : null}
      {tab === "localization" ? <LocalizationTab keys={[q.data.name_key, q.data.description_key].filter((k): k is string => !!k)} /> : null}
      {tab === "workflow" ? <WorkflowTab type={type} code={code} /> : null}
      {tab === "references" ? <ReferencesTab type={type} code={code} /> : null}
      {tab === "history" ? <HistoryTab type={type} code={code} /> : null}
    </div>
  );
}

function IssueList({ issues }: { issues: Issue[] }) {
  const t = useTranslations("contentStudio");
  if (!issues.length) return <p className="text-xs text-good">{t("valid")}</p>;
  return (
    <ul className="text-xs" data-testid="issues">
      {issues.map((i, n) => (
        <li key={n} className={i.level === "error" ? "text-bad" : "text-legendary"}>
          [{i.level}] {i.path ? `${i.path}: ` : ""}
          {i.message}
        </li>
      ))}
    </ul>
  );
}

function GeneralTab({ type, code }: { type: string; code: string }) {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["content-entity", type, code], queryFn: () => contentApi.get(type, code) });
  const [text, setText] = useState<string | null>(null);
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const shown = text ?? JSON.stringify(q.data?.data ?? {}, null, 2);
  const refresh = () => {
    setText(null);
    for (const k of [["content-entity", type, code], ["content-workflow", type, code]]) qc.invalidateQueries({ queryKey: k });
  };
  const save = useMutation({
    mutationFn: () => contentApi.update(type, code, JSON.parse(shown), q.data!.edit_version),
    onSuccess: () => {
      toast("success", t("saved"));
      refresh();
    },
    onError: (e) => {
      if (e instanceof ApiError && Array.isArray(e.details)) setIssues(e.details as Issue[]);
      toast("error", e instanceof SyntaxError ? t("badJson") : errorMessage(e));
    },
  });
  const validate = useMutation({ mutationFn: () => contentApi.validate(type, code), onSuccess: (r) => setIssues(r.issues), onError: (e) => toast("error", errorMessage(e)) });
  const discard = useMutation({ mutationFn: () => contentApi.discard(type, code), onSuccess: refresh, onError: (e) => toast("error", errorMessage(e)) });
  return (
    <section className="space-y-2" aria-label={t("tab.general")}>
      <textarea aria-label={t("data")} value={shown} onChange={(e) => setText(e.target.value)} rows={18} spellCheck={false} className="w-full rounded border border-border bg-bg p-2 font-mono text-xs" data-testid="data-editor" />
      <div className="flex flex-wrap gap-2 text-sm">
        <button type="button" data-testid="save-draft" disabled={save.isPending || text === null} onClick={() => save.mutate()} className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50">
          {t("saveDraft")}
        </button>
        <button type="button" data-testid="validate" onClick={() => validate.mutate()} className="rounded border border-border px-3 py-1">
          {t("validate")}
        </button>
        {q.data?.revision_no && q.data.has_pending_changes ? (
          <button type="button" className="underline" onClick={() => window.confirm(t("discardConfirm")) && discard.mutate()}>
            {t("discard")}
          </button>
        ) : null}
      </div>
      {issues ? <IssueList issues={issues} /> : null}
    </section>
  );
}

function LocalizationTab({ keys }: { keys: string[] }) {
  return (
    <section className="space-y-3">
      {keys.map((k) => (
        <KeyEditor key={k} k={k} />
      ))}
    </section>
  );
}

function KeyEditor({ k }: { k: string }) {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const q = useQuery({ queryKey: ["l10n-key", k], queryFn: () => l10nAdminApi.keys({ search: k }) });
  const [draft, setDraft] = useState<Partial<LocalizedValues>>({});
  const server = q.data?.items.find((i) => i.key === k)?.values;
  const values = { ...emptyLocalizedValues(), ...(server as unknown as LocalizedValues | undefined), ...draft } as LocalizedValues;
  const save = useMutation({
    mutationFn: async () => {
      for (const [loc, v] of Object.entries(draft)) {
        if (v) await l10nAdminApi.set(k, loc, v.value, v.status === "missing" ? "draft" : v.status, v.version ?? null);
      }
    },
    onSuccess: () => {
      toast("success", t("saved"));
      setDraft({});
      q.refetch();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <div className="space-y-1">
      <LocalizedFieldEditor label={k} values={values} onChange={(loc: Locale, next) => setDraft((d) => ({ ...d, [loc]: next }))} multiline={k.endsWith(".description")} />
      <button type="button" disabled={!Object.keys(draft).length || save.isPending} onClick={() => save.mutate()} className="rounded border border-border px-2 py-0.5 text-xs disabled:opacity-50">
        {t("saveTexts")}
      </button>
    </div>
  );
}

function WorkflowTab({ type, code }: { type: string; code: string }) {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const wf = useQuery({ queryKey: ["content-workflow", type, code], queryFn: () => contentApi.workflow(type, code) });
  const [note, setNote] = useState("");
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const done = () => {
    for (const k of [["content-workflow", type, code], ["content-entity", type, code], ["content-history", type, code]]) qc.invalidateQueries({ queryKey: k });
  };
  const run = (fn: () => Promise<unknown>, ok: string, retryStatus?: "archived" | "disabled"): Promise<void> =>
    fn()
      .then(() => {
        toast("success", ok);
        done();
      })
      .catch((e) => {
        if (e instanceof ApiError && e.code === "publish_blocked" && e.details) {
          setIssues(Object.values(e.details as Record<string, Issue[]>).flat());
        }
        if (e instanceof ApiError && e.code === "referenced" && retryStatus) {
          const n = Object.values((e.details as { by_type: Record<string, number> }).by_type).reduce((a, b) => a + b, 0);
          if (window.confirm(t("referencedConfirm", { n }))) {
            void run(() => contentApi.status(type, code, retryStatus, true), t("statusChanged"));
          }
          return;
        }
        toast("error", errorMessage(e));
      });
  const w = wf.data;
  if (!w) return null;
  const at = (s: (typeof STAGES)[number]) =>
    s === "validation" ? (w.stage === "draft" ? "current" : "done") : s === w.stage || (s === "review" && w.stage === "approved") ? "current" : STAGES.indexOf(s) < STAGES.indexOf(w.stage === "approved" ? "review" : (w.stage as (typeof STAGES)[number])) ? "done" : "todo";
  return (
    <section className="space-y-2 text-sm" aria-label={t("tab.workflow")}>
      <ol className="flex flex-wrap gap-1" data-testid="workflow-stages">
        {STAGES.map((s) => (
          <li key={s} aria-current={at(s) === "current" ? "step" : undefined} className={`rounded px-2 py-0.5 text-xs ${at(s) === "current" ? "bg-accent text-bg" : at(s) === "done" ? "border border-good text-good" : "border border-border text-muted"}`}>
            {t(`stage.${s}`)}
          </li>
        ))}
      </ol>
      <p className="text-xs text-muted" data-testid="workflow-stage">
        {t(`stageHelp.${w.stage}`)}
        {w.review_required ? ` ${t("reviewRequired")}` : ""}
        {w.review?.note ? ` · ${t("reviewNote", { note: w.review.note })}` : ""}
      </p>
      <input aria-label={t("note")} placeholder={t("note")} value={note} onChange={(e) => setNote(e.target.value)} className="w-full rounded border border-border bg-bg px-2 py-1" />
      <div className="flex flex-wrap gap-2">
        {w.stage === "draft" ? (
          <button type="button" data-testid="request-review" className="rounded border border-border px-2 py-1" onClick={() => void run(() => contentApi.requestReview(type, code), t("reviewRequested"))}>
            {t("requestReview")}
          </button>
        ) : null}
        {w.stage === "review" ? (
          <>
            <button type="button" data-testid="approve" className="rounded border border-good px-2 py-1 text-good" onClick={() => void run(() => contentApi.approve(type, code, note || undefined), t("approved"))}>
              {t("approve")}
            </button>
            <button type="button" className="rounded border border-bad px-2 py-1 text-bad" onClick={() => void run(() => contentApi.reject(type, code, note || undefined), t("rejected"))}>
              {t("reject")}
            </button>
          </>
        ) : null}
        {w.stage !== "published" && w.stage !== "archived" ? (
          <button type="button" data-testid="publish" className="rounded bg-accent px-2 py-1 font-semibold text-bg" onClick={() => void run(() => contentApi.publish([{ entity_type: type, code }], undefined, true), t("published"))}>
            {t("publish")}
          </button>
        ) : null}
        {w.stage === "published" ? (
          <>
            <button type="button" className="underline" onClick={() => void run(() => contentApi.status(type, code, "disabled"), t("statusChanged"), "disabled")}>
              {t("disable")}
            </button>
            <button type="button" data-testid="archive" className="text-bad underline" onClick={() => void run(() => contentApi.status(type, code, "archived"), t("statusChanged"), "archived")}>
              {t("archive")}
            </button>
          </>
        ) : null}
      </div>
      {issues ? <IssueList issues={issues} /> : null}
    </section>
  );
}

function ReferencesTab({ type, code }: { type: string; code: string }) {
  const t = useTranslations("contentStudio");
  const q = useQuery({ queryKey: ["content-refs", type, code], queryFn: () => contentApi.references(type, code) });
  if (!q.data) return null;
  const r = q.data;
  const link = (et: string, c: string) => (et === "item_template" ? `/admin/items/${encodeURIComponent(c)}` : `/admin/content/${et}/${encodeURIComponent(c)}`);
  return (
    <section className="grid gap-3 text-sm md:grid-cols-2" data-testid="references">
      <div>
        <h3 className="font-semibold">{t("incoming", { n: r.total })}</h3>
        <p className="text-xs text-muted">{Object.entries(r.by_type).map(([k, v]) => `${k}: ${v}`).join(" · ") || t("noRefs")}</p>
        <ul className="text-xs">
          {r.items.map((i) => (
            <li key={`${i.entity_type}:${i.code}`}>
              <Link href={link(i.entity_type, i.code)} className="underline">
                {i.entity_type}:{i.code}
              </Link>{" "}
              <span className="text-muted">({i.via})</span>
            </li>
          ))}
        </ul>
        {r.total ? <p className="text-xs text-legendary">{t("protected")}</p> : null}
      </div>
      <div>
        <h3 className="font-semibold">{t("outgoing", { n: r.outgoing.length })}</h3>
        <ul className="text-xs">
          {r.outgoing.map((o) => (
            <li key={`${o.entity_type}:${o.code}`}>
              <Link href={link(o.entity_type, o.code)} className="underline">
                {o.entity_type}:{o.code}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HistoryTab({ type, code }: { type: string; code: string }) {
  const t = useTranslations("contentStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["content-history", type, code], queryFn: () => contentApi.history(type, code) });
  const [diffFrom, setDiffFrom] = useState<number | null>(null);
  const diff = useQuery({ queryKey: ["content-diff", type, code, diffFrom], queryFn: () => contentApi.diff(type, code, diffFrom!), enabled: diffFrom !== null });
  const rollback = useMutation({
    mutationFn: (rev: number) => contentApi.rollback(type, code, rev),
    onSuccess: () => {
      toast("success", t("rolledBack"));
      qc.invalidateQueries({ queryKey: ["content-history", type, code] });
      qc.invalidateQueries({ queryKey: ["content-entity", type, code] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <section className="space-y-2 text-sm" data-testid="history">
      <ul className="space-y-1">
        {(q.data ?? []).map((h) => (
          <li key={h.revision_no} className="flex flex-wrap items-center gap-2">
            <span className="font-mono">r{h.revision_no}</span>
            <span className="text-xs text-muted">
              {t("release", { v: h.release_version })} · {h.status} · {new Date(h.created_at).toISOString().slice(0, 16).replace("T", " ")}
            </span>
            <button type="button" className="text-xs underline" onClick={() => setDiffFrom(h.revision_no)}>
              {t("diffToCurrent")}
            </button>
            <button type="button" className="text-xs underline" onClick={() => window.confirm(t("rollbackConfirm", { rev: h.revision_no })) && rollback.mutate(h.revision_no)}>
              {t("rollback")}
            </button>
          </li>
        ))}
      </ul>
      {diff.data ? (
        <ul className="rounded border border-border p-2 font-mono text-xs" data-testid="diff">
          {diff.data.length ? (
            diff.data.map((d, i) => (
              <li key={i}>
                {d.path}: <span className="text-bad">{JSON.stringify(d.before)}</span> → <span className="text-good">{JSON.stringify(d.after)}</span>
              </li>
            ))
          ) : (
            <li>{t("noDiff")}</li>
          )}
        </ul>
      ) : null}
    </section>
  );
}

export type { WorkflowState };
