"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { balanceApi, type SimParams } from "@/lib/api/admin-balance";
import { useErrorMessage } from "@/lib/api/errors";

import { BarChart } from "./bar-chart";

const CLASSES = ["warrior", "rogue", "ranger", "mage", "monk", "cleric", "paladin", "druid", "bard", "shaman"];
const RACES = ["human", "high_elf", "dark_elf", "dwarf", "orc", "sylvan", "beastkin", "revenant"];
const SECTIONS = ["support", "racial", "specializations", "talents", "items"];

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  URL.revokeObjectURL(url);
}

/** Balance lab: simulator, class/race checker and aggregate telemetry. Decision support only. */
export function BalanceLab() {
  const t = useTranslations("balanceLab");
  return (
    <div className="space-y-6">
      <p className="rounded border border-border bg-panel p-2 text-xs text-muted">{t("decisionOnly")}</p>
      <Simulator />
      <Checker />
      <TelemetryPanel />
    </div>
  );
}

function Simulator() {
  const t = useTranslations("balanceLab");
  const f = useFormatter();
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const [p, setP] = useState<SimParams>({ level: 100, race: "human", base_class: "warrior", talent_build: "auto", gear_budget_pct: 100, risk: "balanced", duration_s: 10800, iterations: 5, fights: 10, seed: 1, specialization: null, zone: null, profession_node: null, gear_tier: null });
  const set = (patch: Partial<SimParams>) => setP((x) => ({ ...x, ...patch }));
  const run = useMutation({ mutationFn: () => balanceApi.simulate(p), onError: (e) => toast("error", errorMessage(e)) });
  const r = run.data;
  const num = (label: string, key: keyof SimParams, min: number, max: number) => (
    <label className="flex flex-col text-xs">
      {label}
      <input type="number" min={min} max={max} value={(p[key] as number | null) ?? ""} onChange={(e) => set({ [key]: e.target.value === "" ? null : Number(e.target.value) } as Partial<SimParams>)} className="w-24 rounded border border-border bg-bg px-1" />
    </label>
  );
  return (
    <section aria-label={t("simulator")} className="space-y-2">
      <h2 className="font-semibold">{t("simulator")}</h2>
      <div className="flex flex-wrap items-end gap-2">
        {num(t("level"), "level", 1, 1000)}
        <label className="flex flex-col text-xs">
          {t("class")}
          <select value={p.base_class} onChange={(e) => set({ base_class: e.target.value, specialization: null })} className="rounded border border-border bg-bg px-1">
            {CLASSES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs">
          {t("race")}
          <select value={p.race} onChange={(e) => set({ race: e.target.value })} className="rounded border border-border bg-bg px-1">
            {RACES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs">
          {t("spec")}
          <input value={p.specialization ?? ""} onChange={(e) => set({ specialization: e.target.value || null })} placeholder="iron_bastion" className="w-28 rounded border border-border bg-bg px-1" />
        </label>
        <label className="flex flex-col text-xs">
          {t("talents")}
          <input value={p.talent_build} onChange={(e) => set({ talent_build: e.target.value || "auto" })} className="w-24 rounded border border-border bg-bg px-1" />
        </label>
        {num(t("gearTier"), "gear_tier", -1, 10)}
        {num(t("gearBudget"), "gear_budget_pct", 0, 300)}
        <label className="flex flex-col text-xs">
          {t("zone")}
          <input value={p.zone ?? ""} onChange={(e) => set({ zone: e.target.value || null })} placeholder={t("auto")} className="w-32 rounded border border-border bg-bg px-1" />
        </label>
        <label className="flex flex-col text-xs">
          {t("risk")}
          <select value={p.risk} onChange={(e) => set({ risk: e.target.value })} className="rounded border border-border bg-bg px-1">
            {["safe", "balanced", "elite_hunt", "boss_rush"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        {num(t("duration"), "duration_s", 300, 10800)}
        {num(t("iterations"), "iterations", 1, 20)}
        {num(t("fights"), "fights", 1, 40)}
        {num(t("seed"), "seed", 0, 2147483647)}
        <label className="flex flex-col text-xs">
          {t("node")}
          <input value={p.profession_node ?? ""} onChange={(e) => set({ profession_node: e.target.value || null })} placeholder="meadow_herbs" className="w-28 rounded border border-border bg-bg px-1" />
        </label>
        <button type="button" data-testid="run-sim" disabled={run.isPending} onClick={() => run.mutate()} className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50">
          {run.isPending ? t("running") : t("run")}
        </button>
      </div>
      {r ? (
        <div className="space-y-3" data-testid="sim-result">
          <p className="text-xs text-muted">{t("zoneUsed", { zone: r.zone })}</p>
          <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            {Object.entries(r.metrics).map(([k, s]) => (
              <div key={k} className="rounded border border-border bg-panel p-2">
                <dt className="text-xs text-muted">{t(`metric.${k}`)}</dt>
                <dd className="font-semibold">{f.number(s.mean)}</dd>
                <dd className="text-xs text-muted">
                  {f.number(s.min)}–{f.number(s.max)} (σ {f.number(s.stdev)})
                </dd>
              </div>
            ))}
            {Object.entries(r.combat).map(([k, v]) => (
              <div key={k} className="rounded border border-border bg-panel p-2">
                <dt className="text-xs text-muted">{t(`metric.${k}`)}</dt>
                <dd className="font-semibold">{f.number(v)}</dd>
              </div>
            ))}
          </dl>
          <BarChart title={t("metric.xp_per_hour")} tableLabel={t("table")} bars={r.per_iteration.map((it) => ({ label: `#${it.iteration} seed ${it.seed % 10000}`, value: it.xp_per_hour }))} />
          {r.profession ? (
            <p className="text-xs">{t("professionLine", { node: r.profession.node, value: f.number(r.profession.value_per_hour), xp: f.number(r.profession.xp_per_hour) })}</p>
          ) : null}
          <div className="flex gap-2 text-xs">
            <button type="button" className="underline" onClick={() => download("simulation.json", JSON.stringify(r, null, 2), "application/json")}>
              {t("exportJson")}
            </button>
            <button type="button" className="underline" onClick={() => void balanceApi.simulateCsv(p).then((csv) => download("simulation.csv", csv, "text/csv")).catch((e) => toast("error", errorMessage(e)))}>
              {t("exportCsv")}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Checker() {
  const t = useTranslations("balanceLab");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const [level, setLevel] = useState(100);
  const [sections, setSections] = useState<string[]>(["support", "racial", "items"]);
  const run = useMutation({ mutationFn: () => balanceApi.check(level, sections, 4), onError: (e) => toast("error", errorMessage(e)) });
  const rep = run.data;
  const support = (rep?.sections.support as { class: string; category: string; vs_dps_pct: number }[] | undefined) ?? [];
  return (
    <section aria-label={t("checker")} className="space-y-2">
      <h2 className="font-semibold">{t("checker")}</h2>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label>
          {t("level")}{" "}
          <input type="number" min={1} max={1000} value={level} onChange={(e) => setLevel(Number(e.target.value) || 1)} className="w-20 rounded border border-border bg-bg px-1" />
        </label>
        {SECTIONS.map((s) => (
          <label key={s} className="flex items-center gap-1">
            <input type="checkbox" checked={sections.includes(s)} onChange={(e) => setSections((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} />
            {t(`section.${s}`)}
          </label>
        ))}
        <button type="button" data-testid="run-check" disabled={run.isPending || !sections.length} onClick={() => run.mutate()} className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50">
          {run.isPending ? t("running") : t("runCheck")}
        </button>
      </div>
      {rep ? (
        <div className="space-y-2" data-testid="check-result">
          <ul className="text-sm">
            {rep.warnings.map((w, i) => (
              <li key={i}>
                <span aria-hidden>⚠ </span>
                <span className="font-semibold">{t(`section.${w.section}`)}</span> · {w.subject}: {w.message}
              </li>
            ))}
            {!rep.warnings.length ? <li className="text-good">{t("noWarnings")}</li> : null}
          </ul>
          {support.length ? (
            <BarChart title={t("supportChart")} unit="%" band={[70, 80]} tableLabel={t("table")} bars={support.map((s) => ({ label: s.class, value: s.vs_dps_pct, note: s.category }))} />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function TelemetryPanel() {
  const t = useTranslations("balanceLab");
  const f = useFormatter();
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["telemetry", days], queryFn: () => balanceApi.telemetry(days) });
  const d = q.data;
  return (
    <section aria-label={t("telemetry")} className="space-y-2" data-testid="telemetry">
      <h2 className="flex items-center gap-2 font-semibold">
        {t("telemetry")}
        <select aria-label={t("window")} value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-border bg-bg px-1 text-xs font-normal">
          {[7, 30, 90].map((n) => (
            <option key={n} value={n}>
              {t("days", { n })}
            </option>
          ))}
        </select>
      </h2>
      <p className="text-xs text-muted">{t("privacy", { k: d?.min_bucket ?? 3 })}</p>
      {d ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <dl className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(d.sessions).map(([k, v]) => (
              <div key={k} className="rounded border border-border bg-panel p-2">
                <dt className="text-xs text-muted">{t(`session.${k}`)}</dt>
                <dd className="font-semibold">{k.endsWith("rate") || k.endsWith("fight") ? `${f.number(v * 100, { maximumFractionDigits: 1 })}%` : f.number(v)}</dd>
              </div>
            ))}
          </dl>
          <BarChart title={t("funnel")} tableLabel={t("table")} bars={d.funnel.map((s) => ({ label: t(`step.${s.step}`), value: s.count, note: s.drop_off_pct ? `−${s.drop_off_pct}%` : undefined }))} />
          <BarChart title={t("zones")} tableLabel={t("table")} bars={Object.entries(d.zones).map(([k, v]) => ({ label: k, value: v }))} />
          <BarChart title={t("professions")} tableLabel={t("table")} bars={[...Object.entries(d.profession_usage.gathering), ...Object.entries(d.profession_usage.crafting)].map(([k, v]) => ({ label: k, value: v }))} />
        </div>
      ) : null}
    </section>
  );
}
