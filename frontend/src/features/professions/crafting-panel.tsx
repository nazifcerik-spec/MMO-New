"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { afkApi } from "@/lib/api/afk";
import { craftingApi, type CraftJobView, type RecipeView } from "@/lib/api/crafting";
import { useErrorMessage } from "@/lib/api/errors";
import type { ProfessionCard } from "@/lib/api/professions";
import { worldApi } from "@/lib/api/world";

function fmt(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** Recipe list + craft queue (server-authoritative timers) for crafting professions. */
export function CraftingPanel({ characterId, professions }: { characterId: number; professions: ProfessionCard[] }) {
  const t = useTranslations("crafting");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const crafting = professions.filter((p) => p.type === "crafting");
  const [prof, setProf] = useState(crafting[0]?.code ?? "");
  const recipes = useQuery({ queryKey: ["recipes", characterId, prof], queryFn: () => craftingApi.recipes(characterId, prof), enabled: !!prof });
  const jobs = useQuery({ queryKey: ["crafts", characterId], queryFn: () => craftingApi.jobs(characterId), refetchInterval: 15_000 });
  const refresh = () => {
    for (const k of ["recipes", "crafts", "inventory", "professions"]) qc.invalidateQueries({ queryKey: [k, characterId] });
  };
  const onError = (e: unknown) => toast("error", errorMessage(e));
  const start = useMutation({
    mutationFn: ({ code, qty }: { code: string; qty: number }) => craftingApi.start(characterId, code, qty),
    onSuccess: () => {
      toast("success", t("started"));
      refresh();
    },
    onError,
  });
  const claim = useMutation({
    mutationFn: (job: number) => craftingApi.claim(characterId, job),
    onSuccess: (r) => {
      toast("success", t("claimed", { ok: r.successes, fail: r.failures, xp: r.profession_xp.xp_gained }));
      refresh();
    },
    onError,
  });
  const cancel = useMutation({ mutationFn: (job: number) => craftingApi.cancel(characterId, job), onSuccess: refresh, onError });

  return (
    <section aria-label={t("title")} className="space-y-2 rounded border border-border bg-panel p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{t("title")}</h2>
        <label className="ml-auto text-xs">
          {t("profession")}{" "}
          <select data-testid="craft-profession" className="rounded border border-border bg-bg px-1" value={prof} onChange={(e) => setProf(e.target.value)}>
            {crafting.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name} ({p.level})
              </option>
            ))}
          </select>
        </label>
      </div>
      <CraftQueue jobs={jobs.data ?? []} onClaim={(id) => claim.mutate(id)} onCancel={(id) => window.confirm(t("cancelConfirm")) && cancel.mutate(id)} busy={claim.isPending || cancel.isPending} />
      {recipes.isLoading ? <p>{tc("loading")}</p> : null}
      <ul className="space-y-1" data-testid="recipe-list">
        {(recipes.data ?? []).map((r) => (
          <RecipeRow key={r.code} r={r} busy={start.isPending} onCraft={(qty) => start.mutate({ code: r.code, qty })} />
        ))}
        {recipes.data && !recipes.data.length ? <li className="text-sm text-muted">{t("noRecipes")}</li> : null}
      </ul>
    </section>
  );
}

function RecipeRow({ r, busy, onCraft }: { r: RecipeView; busy: boolean; onCraft: (qty: number) => void }) {
  const t = useTranslations("crafting");
  const [qty, setQty] = useState(1);
  const blocker = !r.known ? t("unknown") : !r.craftable ? (r.tool_ok ? t("levelNeeded", { level: r.required_level }) : t("toolNeeded")) : r.max_craftable < 1 ? t("noMaterials") : null;
  return (
    <li className="rounded border border-border p-2 text-sm" data-testid={`recipe-${r.code}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{r.name}</span>
        <span className="text-xs text-muted">
          {t("meta", { level: r.required_level, time: fmt(r.craft_time_s), xp: r.xp, fail: r.fail_chance_pct })}
        </span>
        {r.quality_applies ? <span className="text-xs text-epic">{t("quality")}</span> : null}
      </div>
      <p className="text-xs">
        {r.ingredients.map((i) => (
          <span key={i.template_code} className={i.have >= i.qty ? "mr-2" : "mr-2 text-bad"}>
            {i.name} {i.have}/{i.qty}
          </span>
        ))}
        → {r.output.name} ×{r.output.qty}
        {r.workstation ? ` · ${t("workstation", { name: r.workstation })}` : ""}
      </p>
      {blocker ? (
        <p className="text-xs text-bad">{blocker}</p>
      ) : (
        <div className="mt-1 flex items-center gap-2">
          <input
            type="number"
            aria-label={t("quantity")}
            min={1}
            max={r.max_craftable}
            value={qty}
            onChange={(e) => setQty(Math.max(1, Math.min(r.max_craftable, Number(e.target.value) || 1)))}
            className="w-16 rounded border border-border bg-bg px-1"
          />
          <button type="button" data-testid={`craft-${r.code}`} disabled={busy} onClick={() => onCraft(qty)} className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg disabled:opacity-50">
            {t("craft")}
          </button>
        </div>
      )}
    </li>
  );
}

function CraftQueue({ jobs, onClaim, onCancel, busy }: { jobs: CraftJobView[]; onClaim: (id: number) => void; onCancel: (id: number) => void; busy: boolean }) {
  const t = useTranslations("crafting");
  const [now, setNow] = useState(() => Date.now());
  const [fetchedAt, setFetchedAt] = useState(now);
  const [prevJobs, setPrevJobs] = useState(jobs);
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(i);
  }, []);
  if (prevJobs !== jobs) {
    setPrevJobs(jobs);
    setFetchedAt(now);
  }
  if (!jobs.length) return <p className="text-xs text-muted">{t("queueEmpty")}</p>;
  const elapsed = Math.max(0, (now - fetchedAt) / 1000);
  return (
    <ul className="space-y-1" data-testid="craft-queue" aria-live="polite">
      {jobs.map((j) => {
        const left = Math.max(0, Math.round(j.remaining_s - elapsed));
        return (
          <li key={j.id} className="flex items-center gap-2 text-sm">
            <span>
              {j.recipe} ×{j.quantity}
            </span>
            <span className="text-xs text-muted">{left ? fmt(left) : t("ready")}</span>
            {left ? (
              <button type="button" className="ml-auto text-xs text-bad underline" disabled={busy} onClick={() => onCancel(j.id)}>
                {t("cancel")}
              </button>
            ) : (
              <button type="button" data-testid={`claim-craft-${j.id}`} className="ml-auto rounded bg-good px-2 text-xs font-semibold text-bg" disabled={busy} onClick={() => onClaim(j.id)}>
                {t("claim")}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Start an AFK gathering session on a node of an unlocked zone (same 3h AFK engine). */
export function GatheringPanel({ characterId }: { characterId: number }) {
  const t = useTranslations("crafting");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const zones = useQuery({ queryKey: ["zones", characterId], queryFn: () => worldApi.zones(characterId) });
  const eligible = (zones.data?.items ?? []).filter((z) => z.eligible !== false);
  const [zone, setZone] = useState("");
  const zoneCode = zone || eligible[0]?.code || "";
  const detail = useQuery({ queryKey: ["zone", zoneCode, characterId], queryFn: () => worldApi.zone(zoneCode, characterId), enabled: !!zoneCode });
  const [hours, setHours] = useState(1);
  const start = useMutation({
    mutationFn: (node: string) => afkApi.start(characterId, { zone_code: zoneCode, duration_s: hours * 3600, profession_task: { node_code: node } }),
    onSuccess: () => toast("success", t("gatheringStarted")),
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <section aria-label={t("gathering")} className="space-y-2 rounded border border-border bg-panel p-3" data-testid="gathering-panel">
      <h2 className="font-semibold">{t("gathering")}</h2>
      <div className="flex flex-wrap gap-2 text-xs">
        <label>
          {t("zone")}{" "}
          <select className="rounded border border-border bg-bg px-1" value={zoneCode} onChange={(e) => setZone(e.target.value)}>
            {eligible.map((z) => (
              <option key={z.code} value={z.code}>
                {z.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("hours")}{" "}
          <select className="rounded border border-border bg-bg px-1" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {[1, 2, 3].map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="space-y-1 text-sm">
        {(detail.data?.profession_nodes ?? []).map((n) => (
          <li key={n.node_code} className="flex items-center gap-2">
            <span>
              {n.node_code} · {n.profession_code} · T{n.tier}
            </span>
            <button type="button" data-testid={`gather-${n.node_code}`} className="ml-auto rounded bg-accent px-2 text-xs font-semibold text-bg disabled:opacity-50" disabled={start.isPending} onClick={() => start.mutate(n.node_code)}>
              {t("gather")}
            </button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">{t("gatheringHint")}</p>
    </section>
  );
}
