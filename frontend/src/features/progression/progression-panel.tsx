"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";
import { PRIMARY_STATS, progressionApi, type PrimaryStat, type ProgressionView, type StatLine } from "@/lib/api/progression";

function XpBar({ view }: { view: ProgressionView }) {
  const t = useTranslations("progression");
  const f = useFormatter();
  const pct = Math.min(100, Math.max(0, view.progress_percent));
  return (
    <div className="space-y-1">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={t("levelOf", { level: view.level, cap: view.level_cap })}
        className="h-3 w-full overflow-hidden rounded border border-border bg-bg"
      >
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <p className="font-mono text-xs text-muted" data-testid="xp-text">
        {view.xp_to_next === null
          ? t("maxLevel")
          : t("xpProgress", { xp: f.number(view.xp), need: f.number(view.xp_to_next), pct: pct.toFixed(1) })}
      </p>
    </div>
  );
}

export function BreakdownTable({ line, label }: { line: StatLine; label: string }) {
  const t = useTranslations("progression");
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted">{t("breakdown")}</summary>
      <table className="mt-1 w-full font-mono" aria-label={`${label} ${t("breakdown")}`}>
        <tbody>
          {line.breakdown.map((b, i) => (
            <tr key={`${b.source}-${b.ref}-${i}`}>
              <td className="pr-2">{t.has(`sources.${b.source}`) ? t(`sources.${b.source}`) : b.source}</td>
              <td className="pr-2 text-muted">{b.ref}</td>
              <td className="pr-2 text-right">{b.flat ? `+${b.flat}` : ""}</td>
              <td className="text-right">{b.percent ? `${b.percent > 0 ? "+" : ""}${b.percent}%` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function fmt(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function ProgressionPanel({ characterId }: { characterId: number }) {
  const t = useTranslations("progression");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["progression", characterId];
  const { data: view, isLoading, isError } = useQuery({ queryKey: key, queryFn: () => progressionApi.get(characterId) });
  const profiles = useQuery({ queryKey: ["stat-profiles"], queryFn: progressionApi.profiles });
  const [pending, setPending] = useState<Partial<Record<PrimaryStat, number>>>({});
  const [profile, setProfile] = useState("");
  const pendingTotal = Object.values(pending).reduce((a, b) => a + (b ?? 0), 0);

  const onDone = {
    onSuccess: () => {
      setPending({});
      qc.invalidateQueries({ queryKey: key });
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError && e.code === "version_conflict") qc.invalidateQueries({ queryKey: key });
    },
  };
  const allocate = useMutation({
    mutationFn: () => progressionApi.allocate(characterId, pending, view!.version),
    ...onDone,
  });
  const auto = useMutation({ mutationFn: () => progressionApi.auto(characterId, profile, view!.version), ...onDone });
  const quote = useQuery({ queryKey: ["respec-quote", characterId], queryFn: () => progressionApi.respecQuote(characterId) });
  const respec = useMutation({
    mutationFn: () => progressionApi.respec(characterId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: ["respec-quote", characterId] });
    },
  });

  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError || !view) return <p role="alert">{tc("error")}</p>;
  const label = (k: string) => view.labels[k] ?? k;
  const remaining = view.unspent_stat_points - pendingTotal;
  const mutationError = allocate.error ?? auto.error ?? respec.error;

  return (
    <div className="space-y-6">
      <section aria-labelledby="lvl" className="space-y-2 rounded border border-border bg-panel p-4">
        <h2 id="lvl" className="font-mono text-lg font-bold" data-testid="level-heading">
          [{label(`title.level.${view.title_code}.name`)}] {t("levelOf", { level: view.level, cap: view.level_cap })}
        </h2>
        <XpBar view={view} />
        <ul className="flex flex-wrap gap-2 text-xs">
          {view.next_title ? (
            <li className="rounded border border-border px-2 py-0.5">
              {t("nextTitle", { title: label(`title.level.${view.next_title.code}.name`), level: view.next_title.level })}
            </li>
          ) : null}
          {view.next_breakpoint ? (
            <li className="rounded border border-border px-2 py-0.5">{t("nextBreakpoint", { level: view.next_breakpoint })}</li>
          ) : null}
        </ul>
      </section>

      <section aria-labelledby="attrs" className="space-y-3 rounded border border-border bg-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="attrs" className="font-semibold">
            {t("primaryStats")}
          </h2>
          <span className="font-mono text-sm" data-testid="unspent">
            {t("unspent", { points: remaining })}
          </span>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {PRIMARY_STATS.map((s) => {
            const line = view.stats.primary[s];
            const add = pending[s] ?? 0;
            const name = label(`stat.${s.toLowerCase()}.name`);
            return (
              <li key={s} className="rounded border border-border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span>
                    <abbr title={name} className="font-mono font-bold no-underline">
                      {s}
                    </abbr>{" "}
                    <span className="text-sm text-muted">{name}</span>
                  </span>
                  <span className="flex items-center gap-1 font-mono">
                    <button
                      type="button"
                      aria-label={t("decrease", { stat: name })}
                      disabled={add <= 0}
                      onClick={() => setPending({ ...pending, [s]: add - 1 })}
                      className="h-7 w-7 rounded border border-border disabled:opacity-40"
                    >
                      −
                    </button>
                    <span data-testid={`stat-${s}`} className="min-w-12 text-center">
                      {fmt(line.final)}
                      {add ? <span className="text-good"> +{add}</span> : null}
                    </span>
                    <button
                      type="button"
                      aria-label={t("increase", { stat: name })}
                      disabled={remaining <= 0}
                      onClick={() => setPending({ ...pending, [s]: add + 1 })}
                      className="h-7 w-7 rounded border border-border disabled:opacity-40"
                    >
                      +
                    </button>
                  </span>
                </div>
                <BreakdownTable line={line} label={name} />
              </li>
            );
          })}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={pendingTotal === 0 || allocate.isPending}
            onClick={() => allocate.mutate()}
            className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50"
          >
            {t("allocate")}
          </button>
          <button type="button" disabled={pendingTotal === 0} onClick={() => setPending({})} className="text-sm underline">
            {t("reset")}
          </button>
          <label className="ml-auto flex items-center gap-2 text-sm">
            {t("profile")}
            <select
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
              className="rounded border border-border bg-panel px-1"
            >
              <option value="">—</option>
              {profiles.data?.map((p) => (
                <option key={p.code} value={p.code} title={p.description}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!profile || view.unspent_stat_points === 0 || auto.isPending}
            onClick={() => auto.mutate()}
            className="rounded border border-border px-3 py-1 text-sm disabled:opacity-50"
          >
            {t("applyProfile")}
          </button>
        </div>
        {mutationError ? (
          <p role="alert" className="text-sm text-bad" data-testid="progression-error">
            {errorMessage(mutationError)}
          </p>
        ) : null}
        {quote.data && quote.data.points_refunded > 0 ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2 text-sm">
            <span className="text-muted">
              {t("respecCost", { points: quote.data.points_refunded, gold: quote.data.gold_cost })}
            </span>
            <button
              type="button"
              className="underline"
              onClick={() => window.confirm(t("respecConfirm")) && respec.mutate()}
            >
              {t("respec")}
            </button>
          </div>
        ) : null}
      </section>

      <section aria-labelledby="derived" className="rounded border border-border bg-panel p-4">
        <h2 id="derived" className="mb-2 font-semibold">
          {t("derivedStats")}
        </h2>
        <ul className="grid gap-x-6 gap-y-1 @md:grid-cols-2 @3xl:grid-cols-3">
          {Object.values(view.stats.derived).map((line) => (
            <li key={line.code} className="text-sm">
              <div className="flex justify-between gap-2">
                <span>{label(`stat.${line.code}.name`)}</span>
                <span className="font-mono" data-testid={`derived-${line.code}`}>
                  {fmt(line.final)}
                </span>
              </div>
              <BreakdownTable line={line} label={label(`stat.${line.code}.name`)} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
