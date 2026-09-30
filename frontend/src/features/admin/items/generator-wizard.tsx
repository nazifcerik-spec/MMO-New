"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { adminItemsApi, downloadText, type GeneratorParams, type GeneratorResult } from "@/lib/api/admin-items";
import { LOCALES } from "@/lib/i18n/config";

const ctl = "w-full rounded border border-border bg-bg px-2 py-1 text-sm";

const DEFAULTS: GeneratorParams = {
  category: "weapon",
  slot: "main_hand",
  weapon_family: "sword",
  armor_family: null,
  tier_from: 0,
  tier_to: 2,
  rarity_weights: { common: 2, fine: 2, rare: 1 },
  requirement_profile: "heavy_weapon",
  count: 10,
  code_pattern: "{theme}_{family}_t{tier}_{n}",
  name_patterns: { en: "{theme} {family} {n}", tr: "{theme} {family} {n}", "zh-CN": "{theme}{family}{n}", es: "{family} {theme} {n}" },
  theme: { code: "iron", names: { en: "Iron", tr: "Demir", "zh-CN": "铁", es: "de hierro" } },
  affix_pool: [],
  class_tags: [],
  salvage_material: null,
};

export function GeneratorWizard() {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const meta = useQuery({ queryKey: ["item-meta"], queryFn: adminItemsApi.meta });
  const [p, setP] = useState<GeneratorParams>(DEFAULTS);
  const [result, setResult] = useState<GeneratorResult | null>(null);
  const set = (patch: Partial<GeneratorParams>) => {
    setP({ ...p, ...patch });
    setResult(null); // any change invalidates the dry-run
  };
  const run = useMutation({
    mutationFn: (commit: boolean) => adminItemsApi.generator(p, commit),
    onSuccess: (r) => {
      setResult(r);
      if (r.summary.committed) toast("success", t("generatorCommitted", { n: r.summary.count }));
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (!meta.data) return <p>{t("loading")}</p>;
  const m = meta.data;
  const slots = m.slots_by_category[p.category] ?? [];
  return (
    <div className="space-y-3" data-testid="generator-wizard">
      <Link href="/admin/items" className="text-sm underline">
        ← {t("backToList")}
      </Link>
      <p className="text-sm text-muted">{t("generatorIntro")}</p>
      <div className="grid gap-3 rounded border border-border bg-panel p-3 sm:grid-cols-3">
        <label className="text-sm">
          {t("colCategory")}
          <select className={ctl} value={p.category} onChange={(e) => set({ category: e.target.value as GeneratorParams["category"], slot: m.slots_by_category[e.target.value]?.[0] ?? "", weapon_family: null, armor_family: null })}>
            {["weapon", "armor", "accessory"].map((c) => (
              <option key={c} value={c}>
                {t(`category.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          {t("slotLabel")}
          <select className={ctl} value={p.slot} onChange={(e) => set({ slot: e.target.value })}>
            {slots.map((s) => (
              <option key={s} value={s}>
                {t(`slot.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {p.category === "weapon" ? (
          <label className="text-sm">
            {t("weaponFamily")}
            <select className={ctl} value={p.weapon_family ?? ""} onChange={(e) => set({ weapon_family: e.target.value || null })} data-testid="gen-weapon-family">
              {m.weapon_families.map((w) => (
                <option key={w.code} value={w.code}>
                  {w.code}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {p.category === "armor" ? (
          <label className="text-sm">
            {t("armorFamily")}
            <select className={ctl} value={p.armor_family ?? ""} onChange={(e) => set({ armor_family: e.target.value || null })}>
              <option value="">—</option>
              {m.armor_families.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="text-sm">
          {t("tierFrom")}
          <input type="number" min={0} max={10} className={ctl} value={p.tier_from} onChange={(e) => set({ tier_from: Number(e.target.value) })} data-testid="gen-tier-from" />
        </label>
        <label className="text-sm">
          {t("tierTo")}
          <input type="number" min={0} max={10} className={ctl} value={p.tier_to} onChange={(e) => set({ tier_to: Number(e.target.value) })} data-testid="gen-tier-to" />
        </label>
        <label className="text-sm">
          {t("count")}
          <input type="number" min={1} max={200} className={ctl} value={p.count} onChange={(e) => set({ count: Number(e.target.value) })} data-testid="gen-count" />
        </label>
        <label className="text-sm">
          {t("requirementProfile")}
          <select className={ctl} value={p.requirement_profile ?? ""} onChange={(e) => set({ requirement_profile: e.target.value || null })}>
            <option value="">—</option>
            {Object.keys(m.requirement_profiles).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          {t("codePattern")}
          <input className={`${ctl} font-mono`} value={p.code_pattern} onChange={(e) => set({ code_pattern: e.target.value })} />
        </label>
        <label className="text-sm">
          {t("themeCode")}
          <input className={`${ctl} font-mono`} value={p.theme.code} onChange={(e) => set({ theme: { ...p.theme, code: e.target.value } })} data-testid="gen-theme" />
        </label>
        <label className="text-sm">
          {t("salvageMaterial")}
          <input className={`${ctl} font-mono`} value={p.salvage_material ?? ""} onChange={(e) => set({ salvage_material: e.target.value || null })} />
        </label>
        <fieldset className="sm:col-span-3">
          <legend className="text-sm">{t("rarityDistribution")}</legend>
          <div className="flex flex-wrap gap-2">
            {m.rarities.map((r) => (
              <label key={r} className="flex items-center gap-1 text-xs">
                {t(`rarityName.${r}`)}
                <input
                  type="number"
                  min={0}
                  className="w-14 rounded border border-border bg-bg px-1"
                  value={p.rarity_weights[r] ?? 0}
                  onChange={(e) => {
                    const w = { ...p.rarity_weights, [r]: Math.max(0, Number(e.target.value)) };
                    if (!w[r]) delete w[r];
                    set({ rarity_weights: w });
                  }}
                />
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="sm:col-span-3">
          <legend className="text-sm">{t("namingPatterns")}</legend>
          <div className="grid gap-2 sm:grid-cols-4">
            {LOCALES.map((l) => (
              <div key={l} className="space-y-1">
                <label className="block text-xs">
                  {t("namePatternFor", { locale: l })}
                  <input lang={l} className={ctl} value={p.name_patterns[l] ?? ""} onChange={(e) => set({ name_patterns: { ...p.name_patterns, [l]: e.target.value } })} />
                </label>
                <label className="block text-xs">
                  {t("themeNameFor", { locale: l })}
                  <input lang={l} className={ctl} value={p.theme.names[l] ?? ""} onChange={(e) => set({ theme: { ...p.theme, names: { ...p.theme.names, [l]: e.target.value } } })} />
                </label>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted">{t("placeholders")}</p>
        </fieldset>
        <fieldset className="sm:col-span-3">
          <legend className="text-sm">{t("affixPool")}</legend>
          <div className="flex flex-wrap gap-1">
            {m.affixes.map((a) => {
              const on = p.affix_pool.includes(a.code);
              return (
                <button key={a.code} type="button" aria-pressed={on} className={`rounded border px-1 text-xs ${on ? "border-accent bg-accent/15" : "border-border"}`} onClick={() => set({ affix_pool: on ? p.affix_pool.filter((x) => x !== a.code) : [...p.affix_pool, a.code] })}>
                  {a.code}
                </button>
              );
            })}
          </div>
        </fieldset>
        <fieldset className="sm:col-span-3">
          <legend className="text-sm">{t("classTags")}</legend>
          <div className="flex flex-wrap gap-1">
            {m.class_tags.map((c) => {
              const on = p.class_tags.includes(c);
              return (
                <button key={c} type="button" aria-pressed={on} className={`rounded border px-1 text-xs ${on ? "border-accent bg-accent/15" : "border-border"}`} onClick={() => set({ class_tags: on ? p.class_tags.filter((x) => x !== c) : [...p.class_tags, c] })}>
                  {c}
                </button>
              );
            })}
          </div>
        </fieldset>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="gen-dry-run" disabled={run.isPending} onClick={() => run.mutate(false)} className="rounded border border-border px-3 py-1">
          {t("dryRun")}
        </button>
        <button
          type="button"
          data-testid="gen-commit"
          disabled={!result || result.summary.errors > 0 || result.summary.committed || run.isPending}
          onClick={() => window.confirm(t("generatorConfirm", { n: result!.summary.count })) && run.mutate(true)}
          className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50"
        >
          {t("createDrafts")}
        </button>
        {result ? (
          <button type="button" className="underline" onClick={() => downloadText("generator-report.json", JSON.stringify(result, null, 2))}>
            {t("downloadReport")}
          </button>
        ) : null}
      </div>
      {result ? (
        <div className="space-y-1" data-testid="gen-result">
          <p className={result.summary.errors ? "text-bad" : "text-good"} data-testid="gen-summary">
            {t("generatorSummary", { count: result.summary.count, errors: result.summary.errors, warnings: result.summary.warnings })}
          </p>
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted">
                  <th>{t("code")}</th>
                  <th>{t("colName")}</th>
                  <th>T</th>
                  <th>{t("colLevel")}</th>
                  <th>{t("rarity")}</th>
                  <th>{t("baseStats")}</th>
                  <th>{t("requirements")}</th>
                  <th>{t("issues")}</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.code} className={r.issues.some((i) => i.level === "error") ? "bg-bad/10" : ""}>
                    <td className="font-mono">{r.code}</td>
                    <td>{r.name}</td>
                    <td>{r.tier}</td>
                    <td>{r.min_level}</td>
                    <td>{t(`rarityName.${r.rarity}`)}</td>
                    <td>{r.base_stats.map((s) => `${s.stat} ${s.amount}`).join(", ")}</td>
                    <td>{Object.entries(r.requirements).map(([k, v]) => `${k} ${v}`).join(", ")}</td>
                    <td>{r.issues.map((i) => `${i.level === "error" ? "⛔" : "⚠"}${i.code}`).join(" ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
