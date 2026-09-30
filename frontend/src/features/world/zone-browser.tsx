"use client";

import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { pct } from "@/lib/api/afk-profile";
import { useErrorMessage } from "@/lib/api/errors";
import { worldApi, type Requirement } from "@/lib/api/world";

function useRequirementText() {
  const t = useTranslations("zones");
  return (r: Requirement) => (r.kind === "min_level" ? t("req.min_level", { level: r.value ?? 0 }) : t(`req.${r.kind}`, { code: r.code ?? "" }));
}

export function ZoneBrowser({ characterId }: { characterId: number }) {
  const t = useTranslations("zones");
  const tc = useTranslations("common");
  const reqText = useRequirementText();
  const [selected, setSelected] = useState<string | null>(null);
  const list = useInfiniteQuery({
    queryKey: ["zones", characterId],
    queryFn: ({ pageParam }) => worldApi.zones(characterId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  if (list.isLoading) return <p>{tc("loading")}</p>;
  if (list.isError || !list.data) return <p role="alert">{tc("error")}</p>;
  const zones = list.data.pages.flatMap((p) => p.items);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <ul className="space-y-2" aria-label={t("list")}>
        {zones.map((z) => (
          <li key={z.code}>
            <button
              type="button"
              data-testid={`zone-${z.code}`}
              aria-pressed={selected === z.code}
              onClick={() => setSelected(z.code)}
              className={`w-full rounded border bg-panel p-3 text-left text-sm ${selected === z.code ? "border-accent" : "border-border"} ${z.eligible ? "" : "opacity-70"}`}
            >
              <span className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold">{z.name}</span>
                <span className="font-mono text-xs">{z.tier_name}</span>
              </span>
              <span className="block text-xs text-muted">
                {t("levels", { min: z.min_level, rec: z.recommended_level, max: z.max_level })} · {t("danger", { n: z.danger_rating })}
              </span>
              {z.eligible === false ? (
                <span className="block text-xs text-bad" data-testid={`zone-locked-${z.code}`}>
                  {t("locked")}: {z.unmet?.map(reqText).join(", ")}
                </span>
              ) : null}
            </button>
          </li>
        ))}
        {list.hasNextPage ? (
          <li>
            <button type="button" className="text-sm underline" onClick={() => list.fetchNextPage()}>
              {t("more")}
            </button>
          </li>
        ) : null}
      </ul>
      {selected ? <ZoneDetailPanel characterId={characterId} code={selected} /> : <p className="text-sm text-muted">{t("pick")}</p>}
    </div>
  );
}

function ZoneDetailPanel({ characterId, code }: { characterId: number; code: string }) {
  const t = useTranslations("zones");
  const ta = useTranslations("afk");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const reqText = useRequirementText();
  const { data: z, isLoading, isError } = useQuery({ queryKey: ["zone", code, characterId], queryFn: () => worldApi.zone(code, characterId) });
  const [boss, setBoss] = useState(false);
  const preview = useMutation({ mutationFn: () => worldApi.preview(characterId, code, boss) });
  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError || !z) return <p role="alert">{tc("error")}</p>;
  const r = preview.data?.zone === code ? preview.data : undefined;

  return (
    <section aria-labelledby="zone-title" className="space-y-3 rounded border border-border bg-panel p-3 text-sm" data-testid="zone-detail">
      <header>
        <h2 id="zone-title" className="text-lg font-semibold">
          {z.name}
        </h2>
        <p className="text-xs text-muted">
          {z.tier_name} · {t("levels", { min: z.min_level, rec: z.recommended_level, max: z.max_level })} · {t("danger", { n: z.danger_rating })}
        </p>
        {z.description ? <p className="mt-1">{z.description}</p> : null}
        {z.unmet?.length ? (
          <p className="text-bad">
            {t("locked")}: {z.unmet.map(reqText).join(", ")}
          </p>
        ) : null}
      </header>
      <div>
        <h3 className="font-semibold">{t("enemies")}</h3>
        <ul className="grid gap-1 sm:grid-cols-2">
          {z.enemies.map((e) => (
            <li key={e.code}>
              {e.name} <span className="text-xs text-muted">({t(`rank.${e.rank}`)} · {e.damage_type})</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="font-semibold">{t("bosses", { pct: z.boss_chance_pct })}</h3>
        <ul>
          {z.bosses.map((b) => (
            <li key={b.code} className="text-legendary" data-testid={`boss-${b.code}`}>
              {b.name} <span className="text-xs text-muted">({b.damage_type})</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="font-semibold">{t("drops")}</h3>
        <p className="text-xs">
          {z.drops
            .map((d) => (d.kind === "item_pool" ? t("dropPool", { tier: d.tier ?? 0, rarity: d.rarity ? ta(`rarity.${d.rarity}`) : "" }) : t(`drop.${d.kind}`)))
            .join(" · ")}
        </p>
      </div>
      <table className="w-full text-xs">
        <caption className="text-left font-semibold">{t("risk")}</caption>
        <thead>
          <tr className="text-muted">
            <th className="text-left font-normal">{t("riskLevel")}</th>
            <th className="text-right font-normal">{t("xpLoot")}</th>
            <th className="text-right font-normal">{t("deathRisk")}</th>
          </tr>
        </thead>
        <tbody>
          {z.risk_profiles.map((rp) => (
            <tr key={rp.code}>
              <td>{rp.name}</td>
              <td className="text-right font-mono">
                {rp.xp_loot_percent}%{rp.rare_bonus_percent ? ` +${rp.rare_bonus_percent}% ${t("rare")}` : ""}
              </td>
              <td className="text-right font-mono">×{(rp.death_risk_percent / 100).toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={boss} onChange={(e) => setBoss(e.target.checked)} />
          {ta("bossEncounter")}
        </label>
        <button
          type="button"
          data-testid="zone-preview"
          disabled={preview.isPending}
          onClick={() => preview.mutate()}
          className="rounded border border-border px-3 py-1 disabled:opacity-50"
        >
          {preview.isPending ? tc("loading") : ta("runPreview")}
        </button>
      </div>
      {preview.error ? (
        <p role="alert" className="text-bad">
          {errorMessage(preview.error)}
        </p>
      ) : null}
      {r ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs sm:grid-cols-4" data-testid="zone-preview-result">
          <dt className="text-muted">{ta("winRate")}</dt>
          <dd data-testid="zone-win-rate">{pct(r.win_rate)}</dd>
          <dt className="text-muted">{ta("deathRate")}</dt>
          <dd>{pct(r.death_rate)}</dd>
          <dt className="text-muted">{ta("avgDuration")}</dt>
          <dd>{ta("seconds", { s: r.avg_duration_s })}</dd>
          <dt className="text-muted">{ta("dps")}</dt>
          <dd>{r.dps}</dd>
        </dl>
      ) : null}
    </section>
  );
}
