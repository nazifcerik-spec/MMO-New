"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { newIdempotencyKey } from "@/lib/api/client";
import { afkApi, formatDuration, remainingSeconds, type AfkClaim, type AfkSessionView } from "@/lib/api/afk";
import { useErrorMessage } from "@/lib/api/errors";
import { worldApi } from "@/lib/api/world";

const RISKS = ["safe", "balanced", "dangerous", "elite_hunt"] as const;

export function AfkSessionPanel({ characterId }: { characterId: number }) {
  const t = useTranslations("afkSession");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["afk-session", characterId];
  const current = useQuery({ queryKey: key, queryFn: () => afkApi.current(characterId) });
  const [claimed, setClaimed] = useState<AfkClaim | null>(null);
  const claimKey = useRef<string>(newIdempotencyKey());
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const claim = useMutation({
    mutationFn: () => afkApi.claim(characterId, claimKey.current),
    onSuccess: (c) => {
      setClaimed(c);
      claimKey.current = newIdempotencyKey();
      refresh();
      qc.invalidateQueries({ queryKey: ["progression", characterId] });
    },
  });
  const stop = useMutation({ mutationFn: () => afkApi.stop(characterId), onSuccess: refresh });

  if (current.isLoading) return <p>{tc("loading")}</p>;
  if (current.isError || !current.data) return <p role="alert">{tc("error")}</p>;
  const session = current.data.session;
  const err = claim.error ?? stop.error;

  return (
    <section aria-labelledby="afk-session-title" className="space-y-3 rounded border border-border bg-panel p-3 text-sm" data-testid="afk-session">
      <h2 id="afk-session-title" className="font-semibold">
        {t("title")}
      </h2>
      {claimed ? <ClaimSummary claim={claimed} onClose={() => setClaimed(null)} /> : null}
      {!claimed && !session ? <StartForm characterId={characterId} onStarted={refresh} /> : null}
      {!claimed && session ? (
        <Running
          session={session}
          fetchedAt={current.dataUpdatedAt}
          onClaim={() => claim.mutate()}
          onStop={() => window.confirm(t("stopConfirm")) && stop.mutate()}
          busy={claim.isPending || stop.isPending}
          onExpire={refresh}
        />
      ) : null}
      {err ? (
        <p role="alert" className="text-bad" data-testid="afk-session-error">
          {errorMessage(err)}
        </p>
      ) : null}
    </section>
  );
}

function StartForm({ characterId, onStarted }: { characterId: number; onStarted: () => void }) {
  const t = useTranslations("afkSession");
  const ta = useTranslations("afk");
  const errorMessage = useErrorMessage();
  const zones = useQuery({ queryKey: ["zones", characterId, "eligible"], queryFn: () => worldApi.zones(characterId) });
  const eligible = (zones.data?.items ?? []).filter((z) => z.eligible);
  const [zone, setZone] = useState("");
  const [minutes, setMinutes] = useState(180);
  const [risk, setRisk] = useState("");
  const start = useMutation({
    mutationFn: () =>
      afkApi.start(characterId, { zone_code: zone || eligible[0]?.code, duration_s: minutes * 60, ...(risk ? { risk_level: risk } : {}) }),
    onSuccess: onStarted,
  });
  return (
    <form
      className="grid gap-2 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        start.mutate();
      }}
    >
      <label>
        {t("zone")}
        <select className="w-full rounded border border-border bg-bg px-2 py-1" value={zone || eligible[0]?.code || ""} onChange={(e) => setZone(e.target.value)}>
          {eligible.map((z) => (
            <option key={z.code} value={z.code}>
              {z.name} ({z.tier_name})
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("duration", { d: formatDuration(minutes * 60) })}
        <input
          type="range"
          min={5}
          max={180}
          step={5}
          className="w-full"
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        />
      </label>
      <label>
        {ta("risk")}
        <select className="w-full rounded border border-border bg-bg px-2 py-1" value={risk} onChange={(e) => setRisk(e.target.value)}>
          <option value="">{t("profileRisk")}</option>
          {RISKS.map((r) => (
            <option key={r} value={r}>
              {t(`risk.${r}`)}
            </option>
          ))}
        </select>
      </label>
      <div className="sm:col-span-3">
        <button
          type="submit"
          data-testid="afk-start"
          disabled={start.isPending || !eligible.length}
          className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
        >
          {t("start")}
        </button>
        <span className="ml-2 text-xs text-muted">{t("cap")}</span>
      </div>
      {start.error ? (
        <p role="alert" className="text-bad sm:col-span-3">
          {errorMessage(start.error)}
        </p>
      ) : null}
    </form>
  );
}

function Running({
  session,
  fetchedAt,
  onClaim,
  onStop,
  onExpire,
  busy,
}: {
  session: AfkSessionView;
  fetchedAt: number;
  onClaim: () => void;
  onStop: () => void;
  onExpire: () => void;
  busy: boolean;
}) {
  const t = useTranslations("afkSession");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const remaining = session.claimable ? 0 : remainingSeconds(session, nowMs, fetchedAt);
  useEffect(() => {
    if (session.claimable) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [session.claimable]);
  useEffect(() => {
    if (!session.claimable && remaining === 0) onExpire();
  }, [remaining, session.claimable, onExpire]);
  const b = session.build;
  return (
    <div className="space-y-2" data-testid="afk-running">
      <p>
        {t("farming", { zone: session.zone_name })} · {t(`risk.${session.risk_level}`)}
      </p>
      <p className="font-mono text-2xl" role="timer" aria-live="off" data-testid="afk-countdown">
        {session.claimable ? t("finished") : formatDuration(remaining)}
      </p>
      <p className="text-xs text-muted" data-testid="afk-snapshot">
        {t("snapshot", { level: Number(b.level ?? 0), cls: String(b.specialization ?? b.branch ?? b.class ?? ""), stance: String(b.stance ?? "") })}
      </p>
      <ul className="flex flex-wrap gap-2 text-xs">
        {session.efficiency.map((e) => (
          <li key={e.from_s} className="rounded border border-border px-1">
            {t("band", { from: formatDuration(e.from_s), to: formatDuration(e.to_s), pct: e.percent })}
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="afk-claim"
          disabled={!session.claimable || busy}
          onClick={onClaim}
          className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
        >
          {t("claim")}
        </button>
        {!session.claimable ? (
          <button type="button" data-testid="afk-stop" disabled={busy} onClick={onStop} className="underline">
            {t("stop")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function ClaimSummary({ claim, onClose }: { claim: AfkClaim; onClose: () => void }) {
  const t = useTranslations("afkSession");
  const ta = useTranslations("afk");
  const f = useFormatter();
  const r = claim.result;
  return (
    <div className="space-y-2" data-testid="afk-claim-summary">
      <ul className="space-y-1" aria-label={t("signals")}>
        {claim.signals.map((s, i) => (
          <li key={i} className="font-semibold text-accent" data-testid={`signal-${s.kind}`}>
            {t(`signal.${s.kind}`, { levels: s.levels ?? 0, level: s.level ?? 0, percent: s.percent ?? 0, count: s.count ?? 0, amount: f.number(s.amount ?? 0) })}
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs sm:grid-cols-4">
        <dt className="text-muted">{t("time")}</dt>
        <dd>{formatDuration(r.elapsed_s)}</dd>
        <dt className="text-muted">{t("fights")}</dt>
        <dd data-testid="summary-fights">{f.number(r.fights)}</dd>
        <dt className="text-muted">{t("kills")}</dt>
        <dd>{f.number(r.kills)}</dd>
        <dt className="text-muted">{t("deaths")}</dt>
        <dd>{r.deaths}</dd>
        <dt className="text-muted">XP</dt>
        <dd data-testid="summary-xp">{f.number(r.xp)}</dd>
        <dt className="text-muted">{t("gold")}</dt>
        <dd>{f.number(claim.gold)}</dd>
        <dt className="text-muted">{t("efficiency")}</dt>
        <dd>{r.avg_efficiency_pct}%</dd>
        <dt className="text-muted">{t("durability")}</dt>
        <dd>-{r.durability_loss_pct}%</dd>
      </dl>
      {claim.loot_pending.length ? (
        <div>
          <h3 className="font-semibold">{t("drops")}</h3>
          <ul className="text-xs">
            {claim.loot_pending.map((d, i) => (
              <li key={i}>
                {d.qty}× {d.kind === "item_pool" ? t("itemPool", { tier: d.tier ?? 0, rarity: d.rarity ? ta(`rarity.${d.rarity}`) : "" }) : (d.ref ?? d.kind)}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">{t("pendingLoot")}</p>
        </div>
      ) : null}
      <button type="button" className="underline" onClick={onClose}>
        {t("close")}
      </button>
    </div>
  );
}
