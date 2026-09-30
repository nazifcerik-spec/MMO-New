"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { afkApi, pct, type AfkProfile, type LootFilter, type ProfileUpdate } from "@/lib/api/afk-profile";
import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";

import { TacticsEditor } from "./tactics-editor";

type Draft = Omit<ProfileUpdate, "expected_version">;

const fieldCls = "w-full rounded border border-border bg-bg px-2 py-1 text-sm";

export function AfkProfileEditor({ characterId }: { characterId: number }) {
  const t = useTranslations("afk");
  const tc = useTranslations("common");
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["afk-profile", characterId];
  const { data, isLoading, isError } = useQuery({ queryKey: key, queryFn: () => afkApi.get(characterId) });
  const [advanced, setAdvanced] = useState(false);
  const [draft, setDraft] = useState<Draft>({});
  const [boss, setBoss] = useState(false);

  const save = useMutation({
    mutationFn: (body: Draft) => afkApi.update(characterId, { ...body, expected_version: data!.profile.version }),
    onSuccess: (profile) => {
      setDraft({});
      qc.setQueryData(key, { ...data!, profile });
    },
    onError: (e) => e instanceof ApiError && e.code === "version_conflict" && qc.invalidateQueries({ queryKey: key }),
  });
  const preview = useMutation({ mutationFn: () => afkApi.preview(characterId, { fights: 10, boss }) });

  if (isLoading) return <p>{tc("loading")}</p>;
  if (isError || !data) return <p role="alert">{tc("error")}</p>;
  const { options } = data;
  const p: AfkProfile = { ...data.profile, ...draft, loot_filter: { ...data.profile.loot_filter, ...draft.loot_filter } };
  const set = (patch: Draft) => setDraft({ ...draft, ...patch });
  const setLoot = (patch: Partial<LootFilter>) => set({ loot_filter: { ...p.loot_filter, ...patch } });
  const dirty = Object.keys(draft).length > 0;
  const err = save.error ?? preview.error;
  const r = preview.data;

  return (
    <div className="space-y-4" data-testid="afk-editor">
      <section aria-labelledby="afk-presets">
        <h2 id="afk-presets" className="mb-2 font-semibold">
          {t("presets")}
        </h2>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup" aria-label={t("presets")}>
          {options.presets.map((preset) => {
            const active = data.profile.preset_code === preset.code;
            return (
              <button
                key={preset.code}
                type="button"
                role="radio"
                aria-checked={active}
                data-testid={`preset-${preset.code}`}
                disabled={save.isPending}
                onClick={() => save.mutate({ preset_code: preset.code })}
                className={`rounded border p-3 text-left text-sm ${active ? "border-accent" : "border-border"} bg-panel`}
              >
                <span className="block font-semibold">{preset.name}</span>
                <span className="block text-xs text-muted">
                  {options.stances.find((s) => s.code === preset.stance)?.name} ·{" "}
                  {options.risk_levels.find((x) => x.code === preset.risk_level)?.name} ·{" "}
                  {t("potionAt", { pct: preset.potion_threshold_pct })}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <button type="button" className="text-sm underline" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
        {advanced ? t("hideAdvanced") : t("showAdvanced")}
      </button>

      {advanced ? (
        <section className="grid gap-3 rounded border border-border bg-panel p-3 sm:grid-cols-2" data-testid="afk-advanced">
          <label className="text-sm">
            {t("mode")}
            <select className={fieldCls} value={p.mode} onChange={(e) => set({ mode: e.target.value as AfkProfile["mode"] })}>
              {options.modes.map((m) => (
                <option key={m} value={m}>
                  {t(`modes.${m}`)}
                </option>
              ))}
            </select>
          </label>
          <div className="text-sm">
            <label htmlFor="afk-passive">{t("passiveProfile")}</label>
            <select
              id="afk-passive"
              aria-describedby="afk-passive-desc"
              className={fieldCls}
              value={p.passive_profile_code ?? ""}
              onChange={(e) => set({ passive_profile_code: e.target.value || null })}
            >
              {options.passive_profiles.map((pp) => (
                <option key={pp.code} value={pp.code}>
                  {pp.name}
                </option>
              ))}
            </select>
            <span id="afk-passive-desc" className="block text-xs text-muted">
              {options.passive_profiles.find((pp) => pp.code === p.passive_profile_code)?.description}
            </span>
          </div>
          <div className="text-sm">
            <label htmlFor="afk-stance">{t("stance")}</label>
            <select
              id="afk-stance"
              aria-describedby="afk-stance-desc"
              className={fieldCls}
              value={p.stance}
              onChange={(e) => set({ stance: e.target.value })}
            >
              {options.stances.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
            <span id="afk-stance-desc" className="block text-xs text-muted">
              {options.stances.find((s) => s.code === p.stance)?.description}
            </span>
          </div>
          <label className="text-sm">
            {t("targetPriority")}
            <select className={fieldCls} value={p.target_priority} onChange={(e) => set({ target_priority: e.target.value })}>
              {options.target_priorities.map((x) => (
                <option key={x.code} value={x.code}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            {t("risk")}
            <select className={fieldCls} value={p.risk_level} onChange={(e) => set({ risk_level: e.target.value })}>
              {options.risk_levels.map((x) => (
                <option key={x.code} value={x.code}>
                  {x.name} ({x.enemy_power_percent}%)
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            {t("potionThreshold", { pct: p.potion_threshold_pct })}
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              className="w-full"
              value={p.potion_threshold_pct}
              onChange={(e) => set({ potion_threshold_pct: Number(e.target.value) })}
            />
          </label>
          <fieldset className="text-sm sm:col-span-2">
            <legend className="font-semibold">{t("lootFilter")}</legend>
            <div className="mt-1 grid gap-2 sm:grid-cols-4">
              <label>
                {t("minRarity")}
                <select className={fieldCls} value={p.loot_filter.min_rarity} onChange={(e) => setLoot({ min_rarity: e.target.value })}>
                  {options.rarities.map((x) => (
                    <option key={x} value={x}>
                      {t(`rarity.${x}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("minTier")}
                <input
                  type="number"
                  min={0}
                  max={10}
                  className={fieldCls}
                  value={p.loot_filter.min_tier}
                  onChange={(e) => setLoot({ min_tier: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })}
                />
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={p.loot_filter.keep_materials}
                  onChange={(e) => setLoot({ keep_materials: e.target.checked })}
                />
                {t("keepMaterials")}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={p.loot_filter.auto_salvage}
                  onChange={(e) => setLoot({ auto_salvage: e.target.checked })}
                />
                {t("autoSalvage")}
              </label>
            </div>
          </fieldset>
          <div className="flex gap-2 sm:col-span-2">
            <button
              type="button"
              data-testid="afk-save"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate(draft)}
              className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50"
            >
              {t("save")}
            </button>
            <button type="button" className="text-sm underline" disabled={!dirty} onClick={() => setDraft({})}>
              {t("discard")}
            </button>
          </div>
        </section>
      ) : null}

      {advanced && p.mode !== "PASSIVE_ONLY" ? (
        <TacticsEditor
          key={data.profile.version}
          characterId={characterId}
          options={options.tactics}
          saved={data.profile.tactics}
          saving={save.isPending}
          onSave={(tactics) => save.mutate({ ...draft, tactics })}
        />
      ) : null}

      {err ? (
        <p role="alert" className="text-sm text-bad" data-testid="afk-error">
          {errorMessage(err)}
        </p>
      ) : null}

      <section aria-labelledby="afk-preview" className="rounded border border-border bg-panel p-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="afk-preview" className="font-semibold">
            {t("preview")}
          </h2>
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={boss} onChange={(e) => setBoss(e.target.checked)} />
            {t("bossEncounter")}
          </label>
          <button
            type="button"
            data-testid="afk-run-preview"
            disabled={preview.isPending || dirty}
            onClick={() => preview.mutate()}
            className="rounded border border-border px-3 py-1 text-sm disabled:opacity-50"
          >
            {preview.isPending ? tc("loading") : t("runPreview")}
          </button>
          {dirty ? <span className="text-xs text-muted">{t("saveFirst")}</span> : null}
        </div>
        {r ? (
          <div className="mt-2 space-y-2 text-sm" data-testid="afk-preview-result">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono sm:grid-cols-4">
              <dt className="text-muted">{t("winRate")}</dt>
              <dd data-testid="preview-win-rate">{pct(r.win_rate)}</dd>
              <dt className="text-muted">{t("deathRate")}</dt>
              <dd>{pct(r.death_rate)}</dd>
              <dt className="text-muted">{t("avgDuration")}</dt>
              <dd>{t("seconds", { s: r.avg_duration_s })}</dd>
              <dt className="text-muted">{t("dps")}</dt>
              <dd>{r.dps}</dd>
              <dt className="text-muted">{t("potionsUsed")}</dt>
              <dd>{r.avg_potions_used}</dd>
            </dl>
            <ol className="list-decimal pl-5 text-xs">
              {r.rules.map((rule) => (
                <li key={rule.index}>
                  {rule.name ?? rule.ability ?? rule.tag} — {t("uses", { n: rule.uses })}
                </li>
              ))}
              <li className="list-none text-muted">{t("fallback", { n: r.fallback_basic_attacks })}</li>
            </ol>
          </div>
        ) : null}
      </section>
    </div>
  );
}
