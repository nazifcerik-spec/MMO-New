"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useState, type ReactNode } from "react";

import { useToast } from "@/components/ui/toast";
import { useShortcut, useUnsavedGuard } from "@/components/ui/use-unsaved-guard";
import { ApiError } from "@/lib/api/client";
import { useErrorMessage } from "@/lib/api/errors";
import {
  adminItemsApi,
  requirementPercent,
  type Inspector,
  type ItemData,
  type LocaleTexts,
  type Meta,
  type RegistryEntry,
  type TextField,
} from "@/lib/api/admin-items";
import { LOCALES } from "@/lib/i18n/config";

import { EffectListEditor } from "./effect-editor";

export const TABS = [
  "general",
  "localization",
  "requirements",
  "stats",
  "affixes",
  "unique",
  "sockets",
  "sources",
  "craft",
  "preview",
  "history",
] as const;
type Tab = (typeof TABS)[number];
const ctl = "w-full rounded border border-border bg-bg px-2 py-1 text-sm";
const num = "w-24 rounded border border-border bg-bg px-2 py-1 text-sm";

function Row({ label, children, htmlFor }: { label: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-0.5 text-sm">
      <label htmlFor={htmlFor} className="text-xs text-muted">
        {label}
      </label>
      {children}
    </div>
  );
}

function MultiToggle({ options, value, onChange, label }: { options: string[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
  return (
    <fieldset className="text-sm">
      <legend className="text-xs text-muted">{label}</legend>
      <div className="flex flex-wrap gap-1">
        {options.map((o) => {
          const on = value.includes(o);
          return (
            <button
              key={o}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
              className={`rounded border px-1.5 text-xs ${on ? "border-accent bg-accent/15" : "border-border"}`}
            >
              {o}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ItemEditor({ code }: { code: string }) {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["item-inspector", code];
  const ins = useQuery({ queryKey: key, queryFn: () => adminItemsApi.inspector(code) });
  const meta = useQuery({ queryKey: ["item-meta"], queryFn: adminItemsApi.meta });
  const registry = useQuery({ queryKey: ["effect-registry"], queryFn: adminItemsApi.registry });
  const [tab, setTab] = useState<Tab>("general");
  const [draft, setDraft] = useState<ItemData | null>(null);
  const [conflict, setConflict] = useState<ItemData | null>(null);
  const data = draft ?? ins.data?.data ?? null;
  const dirty = draft !== null;
  useUnsavedGuard(dirty);
  const set = (patch: Partial<ItemData>) => data && setDraft({ ...data, ...patch });
  const reload = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["admin-items"] });
  };
  const save = useMutation({
    mutationFn: () => adminItemsApi.save(code, draft!, ins.data!.edit_version),
    onSuccess: () => {
      setDraft(null);
      setConflict(null);
      toast("success", t("saved"));
      reload();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "version_conflict") {
        setConflict(((e.details as { current_data?: ItemData }) ?? {}).current_data ?? null);
      }
      toast("error", errorMessage(e));
    },
  });
  const publish = useMutation({
    mutationFn: () => adminItemsApi.publish(code, true),
    onSuccess: () => {
      toast("success", t("published"));
      reload();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const status = useMutation({
    mutationFn: (s: "disabled" | "archived" | "published") => adminItemsApi.setStatus(code, s),
    onSuccess: () => {
      toast("success", t("statusChanged"));
      reload();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const doSave = useCallback(() => {
    if (dirty && !save.isPending) save.mutate();
  }, [dirty, save]);
  useShortcut("s", doSave, dirty);

  if (ins.isLoading || meta.isLoading || registry.isLoading) return <p>{t("loading")}</p>;
  if (!ins.data || !meta.data || !registry.data || !data) return <p role="alert">{t("loadError")}</p>;
  const view = ins.data;
  const errors = view.issues.filter((i) => i.level === "error");

  return (
    <div className="space-y-3" data-testid="item-editor">
      <header className="flex flex-wrap items-center gap-2">
        <Link href="/admin/items" className="text-sm underline">
          ← {t("backToList")}
        </Link>
        <h1 className="text-xl font-bold">{view.texts.name.en.value || code}</h1>
        <span className="font-mono text-xs text-muted" data-testid="editor-status">
          {code} · r{view.revision_no} · {t(`statusName.${view.status}`)}
          {view.has_pending_changes ? ` · ${t("pending")}` : ""}
        </span>
        <span className="ml-auto flex flex-wrap gap-2 text-sm">
          <button type="button" data-testid="editor-save" disabled={!dirty || save.isPending} onClick={() => save.mutate()} className="rounded bg-accent px-3 py-1 font-semibold text-bg disabled:opacity-50" title="Ctrl+S">
            {t("save")}
          </button>
          <button type="button" disabled={!dirty} onClick={() => window.confirm(t("discardConfirm")) && setDraft(null)} className="underline disabled:opacity-50">
            {t("discard")}
          </button>
          <button
            type="button"
            data-testid="editor-publish"
            disabled={dirty || errors.length > 0 || !view.has_pending_changes || publish.isPending}
            onClick={() => window.confirm(t("publishConfirm")) && publish.mutate()}
            className="rounded border border-border px-3 py-1 disabled:opacity-50"
          >
            {t("publish")}
          </button>
          {view.revision_no > 0 && view.status !== "archived" ? (
            <button type="button" className="underline text-bad" onClick={() => window.confirm(t("archiveConfirm")) && status.mutate("archived")}>
              {t("archive")}
            </button>
          ) : null}
          {view.status === "published" ? (
            <button type="button" className="underline" onClick={() => window.confirm(t("disableConfirm")) && status.mutate("disabled")}>
              {t("disable")}
            </button>
          ) : null}
          {view.status === "archived" || view.status === "disabled" ? (
            <button type="button" className="underline" onClick={() => status.mutate("published")}>
              {t("restore")}
            </button>
          ) : null}
        </span>
      </header>
      {conflict ? (
        <div role="alert" className="rounded border border-bad p-2 text-sm" data-testid="conflict">
          <p className="font-semibold">{t("conflictTitle")}</p>
          <ul className="text-xs">
            {Object.keys(conflict)
              .filter((k) => JSON.stringify(conflict[k as keyof ItemData]) !== JSON.stringify(data[k as keyof ItemData]))
              .map((k) => (
                <li key={k}>
                  <span className="font-mono">{k}</span>: {t("theirs")} {JSON.stringify(conflict[k as keyof ItemData])} ≠ {t("yours")} {JSON.stringify(data[k as keyof ItemData])}
                </li>
              ))}
          </ul>
          <button
            type="button"
            className="underline"
            onClick={() => {
              setDraft(null);
              setConflict(null);
              reload();
            }}
          >
            {t("reloadTheirs")}
          </button>
        </div>
      ) : null}
      <IssuesBox view={view} />
      <div role="tablist" aria-label={t("tabs")} className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map((tb, i) => (
          <button
            key={tb}
            role="tab"
            id={`tab-${tb}`}
            aria-selected={tab === tb}
            aria-controls={`panel-${tb}`}
            data-testid={`tab-${tb}`}
            onClick={() => setTab(tb)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") setTab(TABS[(i + 1) % TABS.length]);
              if (e.key === "ArrowLeft") setTab(TABS[(i - 1 + TABS.length) % TABS.length]);
            }}
            className={`rounded-t px-2 py-1 text-sm ${tab === tb ? "border border-b-0 border-border bg-panel font-semibold" : "text-muted"}`}
          >
            {t(`tab.${tb}`)}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="rounded border border-border bg-panel p-3">
        {tab === "general" ? <GeneralTab data={data} meta={meta.data} set={set} /> : null}
        {tab === "localization" ? <LocalizationTab code={code} texts={view.texts} onSaved={reload} /> : null}
        {tab === "requirements" ? <RequirementsTab data={data} meta={meta.data} set={set} view={view} /> : null}
        {tab === "stats" ? <StatsTab data={data} meta={meta.data} registry={registry.data} set={set} /> : null}
        {tab === "affixes" ? <AffixTab data={data} meta={meta.data} set={set} /> : null}
        {tab === "unique" ? <UniqueTab data={data} meta={meta.data} registry={registry.data} set={set} /> : null}
        {tab === "sockets" ? <SocketsTab data={data} meta={meta.data} set={set} /> : null}
        {tab === "sources" ? <SourcesTab data={data} meta={meta.data} set={set} view={view} /> : null}
        {tab === "craft" ? <CraftTab data={data} set={set} /> : null}
        {tab === "preview" ? <PreviewTab code={code} data={data} view={view} dirty={dirty} /> : null}
        {tab === "history" ? <HistoryTab code={code} onChanged={reload} /> : null}
      </section>
    </div>
  );
}

function IssuesBox({ view }: { view: Inspector }) {
  const t = useTranslations("itemStudio");
  if (!view.issues.length) return <p className="text-sm text-good" data-testid="editor-valid">{t("valid")}</p>;
  return (
    <ul className="space-y-0.5 text-xs" data-testid="editor-issues">
      {view.issues.map((i, n) => (
        <li key={n} className={i.level === "error" ? "text-bad" : "text-legendary"}>
          {i.level === "error" ? "⛔" : "⚠"} <span className="font-mono">{i.path}</span> {i.code}: {i.message}
        </li>
      ))}
    </ul>
  );
}

interface TabProps {
  data: ItemData;
  meta: Meta;
  set: (patch: Partial<ItemData>) => void;
}

function GeneralTab({ data, meta, set }: TabProps) {
  const t = useTranslations("itemStudio");
  const slots = meta.slots_by_category[data.category] ?? [];
  const gate = meta.tiers[data.tier];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Row label={t("colCategory")} htmlFor="f-category">
        <select id="f-category" className={ctl} value={data.category} onChange={(e) => set({ category: e.target.value, slot: null })}>
          {meta.categories.map((c) => (
            <option key={c} value={c}>
              {t(`category.${c}`)}
            </option>
          ))}
        </select>
      </Row>
      <Row label={t("subcategory")} htmlFor="f-sub">
        <input id="f-sub" className={ctl} value={data.subcategory ?? ""} onChange={(e) => set({ subcategory: e.target.value || null })} />
      </Row>
      <Row label={t("family")} htmlFor="f-family">
        <input id="f-family" className={ctl} value={data.family ?? ""} onChange={(e) => set({ family: e.target.value || null })} />
      </Row>
      <Row label={t("slotLabel")} htmlFor="f-slot">
        <select id="f-slot" className={ctl} value={data.slot ?? ""} onChange={(e) => set({ slot: e.target.value || null })} disabled={!slots.length}>
          <option value="">—</option>
          {slots.map((s) => (
            <option key={s} value={s}>
              {t(`slot.${s}`)}
            </option>
          ))}
        </select>
      </Row>
      {data.category === "weapon" ? (
        <Row label={t("weaponFamily")} htmlFor="f-wf">
          <select id="f-wf" className={ctl} value={data.weapon_family ?? ""} onChange={(e) => set({ weapon_family: e.target.value || null })}>
            <option value="">—</option>
            {meta.weapon_families.map((w) => (
              <option key={w.code} value={w.code}>
                {w.code} ({w.kind}, {w.hands}H)
              </option>
            ))}
          </select>
        </Row>
      ) : null}
      {data.category === "armor" ? (
        <Row label={t("armorFamily")} htmlFor="f-af">
          <select id="f-af" className={ctl} value={data.armor_family ?? ""} onChange={(e) => set({ armor_family: e.target.value || null })}>
            <option value="">—</option>
            {meta.armor_families.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </Row>
      ) : null}
      <Row label={t("tier")} htmlFor="f-tier">
        <select id="f-tier" className={ctl} value={data.tier} onChange={(e) => set({ tier: Number(e.target.value), min_level: meta.tiers[Number(e.target.value)].min_level })}>
          {meta.tiers.map((g) => (
            <option key={g.tier} value={g.tier}>
              T{g.tier} (Lv {g.min_level}–{g.max_level})
            </option>
          ))}
        </select>
      </Row>
      <Row label={t("minLevel", { min: gate.min_level, max: gate.max_level })} htmlFor="f-lvl">
        <input id="f-lvl" type="number" className={num} min={gate.min_level} max={gate.max_level} value={data.min_level} onChange={(e) => set({ min_level: Number(e.target.value) })} />
      </Row>
      <Row label={t("rarity")} htmlFor="f-rarity">
        <select id="f-rarity" className={ctl} value={data.rarity} onChange={(e) => set({ rarity: e.target.value })}>
          {meta.rarities.map((r) => (
            <option key={r} value={r}>
              {t(`rarityName.${r}`)}
              {gate.rarities.includes(r) ? " ✓" : ""}
            </option>
          ))}
        </select>
      </Row>
      <Row label={t("stackSize")} htmlFor="f-stack">
        <input id="f-stack" type="number" className={num} min={1} max={9999} value={data.stack_size} onChange={(e) => set({ stack_size: Number(e.target.value) })} />
      </Row>
      <Row label={t("bindPolicy")} htmlFor="f-bind">
        <select id="f-bind" className={ctl} value={data.bind_policy} onChange={(e) => set({ bind_policy: e.target.value })}>
          {meta.bind_policies.map((b) => (
            <option key={b} value={b}>
              {t(`bind.${b}`)}
            </option>
          ))}
        </select>
      </Row>
      <Row label={t("vendorValue")} htmlFor="f-vendor">
        <input id="f-vendor" type="number" className={num} min={0} value={data.vendor_value} onChange={(e) => set({ vendor_value: Math.max(0, Number(e.target.value)) })} />
      </Row>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={data.tradeable} onChange={(e) => set({ tradeable: e.target.checked })} /> {t("tradeable")}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={data.sellable} onChange={(e) => set({ sellable: e.target.checked })} /> {t("sellable")}
      </label>
      <Row label={t("icon")} htmlFor="f-icon">
        <input id="f-icon" className={ctl} value={data.icon ?? ""} onChange={(e) => set({ icon: e.target.value || null })} />
      </Row>
      <div className="sm:col-span-3">
        <MultiToggle label={t("classTags")} options={meta.class_tags} value={data.class_tags} onChange={(v) => set({ class_tags: v })} />
      </div>
    </div>
  );
}

function LocalizationTab({ code, texts, onSaved }: { code: string; texts: Record<TextField, LocaleTexts>; onSaved: () => void }) {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const [loc, setLoc] = useState<string>("en");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: async () => {
      for (const [k, value] of Object.entries(edits)) {
        const [field, locale] = k.split("|") as [TextField, string];
        await adminItemsApi.setText(code, field, locale, value, texts[field][locale].version);
      }
    },
    onSuccess: () => {
      setEdits({});
      toast("success", t("saved"));
      onSaved();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  useUnsavedGuard(Object.keys(edits).length > 0);
  const fields: TextField[] = ["name", "short_description", "description", "lore"];
  return (
    <div className="space-y-3">
      <div role="tablist" aria-label={t("locales")} className="flex gap-1">
        {LOCALES.map((l) => {
          const missing = !texts.name[l].value;
          return (
            <button key={l} role="tab" aria-selected={loc === l} data-testid={`loc-${l}`} onClick={() => setLoc(l)} className={`rounded border px-2 text-sm ${loc === l ? "border-accent" : "border-border"}`}>
              {l} <span className={missing ? "text-bad" : "text-muted"}>{missing ? "!" : t(`tstatus.${texts.name[l].status}`)}</span>
            </button>
          );
        })}
      </div>
      {fields.map((f) => {
        const cur = texts[f][loc];
        const k = `${f}|${loc}`;
        const value = edits[k] ?? cur.value;
        const long = f !== "name";
        return (
          <div key={f} className="space-y-0.5">
            <label htmlFor={`t-${f}`} className="flex items-center gap-2 text-xs text-muted">
              {t(`textField.${f}`)} <span className="rounded border border-border px-1">{t(`tstatus.${cur.status}`)}</span>
              {!cur.value && loc !== "en" && texts[f].en.value ? <span className="text-legendary">{t("fallbackPreview", { text: texts[f].en.value })}</span> : null}
            </label>
            {long ? (
              <textarea id={`t-${f}`} dir="auto" lang={loc} className={`${ctl} h-16`} value={value} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })} />
            ) : (
              <input id={`t-${f}`} dir="auto" lang={loc} className={ctl} value={value} onChange={(e) => setEdits({ ...edits, [k]: e.target.value })} data-testid={`text-${f}`} />
            )}
          </div>
        );
      })}
      <button type="button" data-testid="save-texts" disabled={!Object.keys(edits).length || save.isPending} onClick={() => save.mutate()} className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50">
        {t("saveTexts")}
      </button>
    </div>
  );
}

function RequirementsTab({ data, meta, set, view }: TabProps & { view: Inspector }) {
  const t = useTranslations("itemStudio");
  const reqs = data.requirements.stats;
  const est = requirementPercent(meta, data.min_level, reqs);
  const level = est.percent > meta.requirement_error_pct ? "error" : est.percent > meta.requirement_warn_pct ? "warning" : "ok";
  const suggest = () => {
    const p = data.requirement_profile ? meta.requirement_profiles[data.requirement_profile] : null;
    if (!p) return;
    const scale = data.min_level / 600;
    set({ requirements: { ...data.requirements, stats: { [p.primary[0]]: Math.round(p.primary_at_600 * scale), [p.secondary]: Math.round(p.secondary_at_600 * scale) } } });
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Row label={t("requirementProfile")} htmlFor="f-rp">
          <select id="f-rp" className={ctl} value={data.requirement_profile ?? ""} onChange={(e) => set({ requirement_profile: e.target.value || null })}>
            <option value="">—</option>
            {Object.keys(meta.requirement_profiles).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Row>
        <button type="button" className="underline text-sm" onClick={suggest} disabled={!data.requirement_profile}>
          {t("suggest")}
        </button>
      </div>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
        {meta.primary_stats.map((s) => (
          <Row key={s} label={s} htmlFor={`req-${s}`}>
            <input
              id={`req-${s}`}
              type="number"
              min={0}
              className={num}
              value={reqs[s] ?? 0}
              onChange={(e) => {
                const v = Math.max(0, Number(e.target.value) || 0);
                const next = { ...reqs, [s]: v };
                if (!v) delete next[s];
                set({ requirements: { ...data.requirements, stats: next } });
              }}
            />
          </Row>
        ))}
      </div>
      <div data-testid="budget-meter" className="text-sm">
        <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(est.percent)} aria-label={t("requirementBudget")} className="h-2 w-full overflow-hidden rounded bg-bg">
          <div className={`h-full ${level === "error" ? "bg-bad" : level === "warning" ? "bg-legendary" : "bg-good"}`} style={{ width: `${Math.min(100, est.percent)}%` }} />
        </div>
        <p className={level === "error" ? "text-bad" : level === "warning" ? "text-legendary" : ""}>
          {t("budgetLine", { total: est.total, budget: est.budget, pct: est.percent.toFixed(1), warn: meta.requirement_warn_pct, err: meta.requirement_error_pct })}
        </p>
        <p className="text-xs text-muted">{t("tierBand", { min: view.tier_gate.stat_req_min, max: view.tier_gate.stat_req_max })}</p>
      </div>
      <MultiToggle label={t("allowedClasses")} options={meta.classes} value={data.allowed_classes} onChange={(v) => set({ allowed_classes: v })} />
      <MultiToggle label={t("blockedClasses")} options={meta.classes} value={data.blocked_classes} onChange={(v) => set({ blocked_classes: v })} />
      <MultiToggle label={t("allowedRaces")} options={meta.races} value={data.allowed_races} onChange={(v) => set({ allowed_races: v })} />
      <MultiToggle label={t("blockedRaces")} options={meta.races} value={data.blocked_races} onChange={(v) => set({ blocked_races: v })} />
      <div className="flex gap-2">
        <Row label={t("professionCode")} htmlFor="f-prof">
          <input
            id="f-prof"
            className={ctl}
            value={data.requirements.profession?.code ?? ""}
            onChange={(e) =>
              set({ requirements: { ...data.requirements, profession: e.target.value ? { code: e.target.value, level: data.requirements.profession?.level ?? 1 } : null } })
            }
          />
        </Row>
        <Row label={t("professionLevel")} htmlFor="f-plvl">
          <input
            id="f-plvl"
            type="number"
            min={1}
            max={500}
            className={num}
            disabled={!data.requirements.profession}
            value={data.requirements.profession?.level ?? 1}
            onChange={(e) => data.requirements.profession && set({ requirements: { ...data.requirements, profession: { ...data.requirements.profession, level: Number(e.target.value) } } })}
          />
        </Row>
      </div>
    </div>
  );
}

function StatsTab({ data, meta, registry, set }: TabProps & { registry: RegistryEntry[] }) {
  const t = useTranslations("itemStudio");
  const stats = [...meta.primary_stats, ...meta.derived_stats];
  return (
    <div className="space-y-3">
      <fieldset className="space-y-1">
        <legend className="font-semibold">{t("baseStats")}</legend>
        {data.base_stats.map((s, i) => (
          <div key={i} className="flex items-center gap-2" data-testid="base-stat-row">
            <select aria-label={t("stat")} className="rounded border border-border bg-bg px-1 text-sm" value={s.stat} onChange={(e) => set({ base_stats: data.base_stats.map((x, j) => (j === i ? { ...x, stat: e.target.value } : x)) })}>
              {stats.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
            <input aria-label={t("amount")} type="number" className={num} value={s.amount} onChange={(e) => set({ base_stats: data.base_stats.map((x, j) => (j === i ? { ...x, amount: Number(e.target.value) } : x)) })} />
            <button type="button" aria-label={t("remove")} onClick={() => set({ base_stats: data.base_stats.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <button type="button" className="text-sm underline" data-testid="add-base-stat" onClick={() => set({ base_stats: [...data.base_stats, { stat: "attack_power", amount: 0 }] })}>
          {t("addStat")}
        </button>
      </fieldset>
      <fieldset>
        <legend className="font-semibold">{t("fixedEffects")}</legend>
        <EffectListEditor value={data.effects} onChange={(effects) => set({ effects })} registry={registry} meta={meta} testId="effects-editor" />
      </fieldset>
    </div>
  );
}

function AffixTab({ data, meta, set }: TabProps) {
  const t = useTranslations("itemStudio");
  const budget = meta.rarity_budgets[data.rarity];
  const ar = data.affix_rules;
  const groups = [...new Set(meta.affixes.map((a) => a.group))];
  return (
    <div className="space-y-3 text-sm">
      <p data-testid="rarity-budget">
        {t("rarityBudget", { rarity: t(`rarityName.${data.rarity}`), min: budget.min, max: budget.max })}
        {budget.unique_required ? ` · ${t("needsUnique")}` : ""}
        {budget.mastery_scaling_required ? ` · ${t("needsMastery")}` : ""}
        {budget.fixed ? ` · ${t("fixedOnly")}` : ""}
      </p>
      <div className="flex gap-2">
        <Row label={t("minAffixes")} htmlFor="f-amin">
          <input id="f-amin" type="number" className={num} min={budget.min} max={budget.max} value={ar.min ?? ""} placeholder={String(budget.min)} onChange={(e) => set({ affix_rules: { ...ar, min: e.target.value === "" ? null : Number(e.target.value) } })} />
        </Row>
        <Row label={t("maxAffixes")} htmlFor="f-amax">
          <input id="f-amax" type="number" className={num} min={budget.min} max={budget.max} value={ar.max ?? ""} placeholder={String(budget.max)} onChange={(e) => set({ affix_rules: { ...ar, max: e.target.value === "" ? null : Number(e.target.value) } })} />
        </Row>
      </div>
      <fieldset>
        <legend className="text-xs text-muted">{t("affixPool")}</legend>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th />
              <th>{t("affix")}</th>
              <th>{t("kind")}</th>
              <th>{t("group")}</th>
              <th>{t("minRarity")}</th>
              <th>{t("classTag")}</th>
            </tr>
          </thead>
          <tbody>
            {meta.affixes.map((a) => {
              const on = ar.pool.includes(a.code) || ar.pool.includes(`group:${a.group}`);
              return (
                <tr key={a.code}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={a.code}
                      checked={on}
                      onChange={(e) => set({ affix_rules: { ...ar, pool: e.target.checked ? [...ar.pool, a.code] : ar.pool.filter((p) => p !== a.code) } })}
                    />
                  </td>
                  <td className="font-mono">{a.code}</td>
                  <td>{a.kind}</td>
                  <td>{a.group}</td>
                  <td>{a.rarity_min}</td>
                  <td>{a.class_tag ?? ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-muted">{t("groupHint", { groups: groups.join(", ") })}</p>
      </fieldset>
    </div>
  );
}

function UniqueTab({ data, meta, registry, set }: TabProps & { registry: RegistryEntry[] }) {
  const t = useTranslations("itemStudio");
  const u = data.unique_effect;
  const itemSet = meta.sets.find((s) => s.code === data.set_code);
  return (
    <div className="space-y-3 text-sm">
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={!!u} onChange={(e) => set({ unique_effect: e.target.checked ? { key: "unique_effect", effects: [], mastery_scaling: data.rarity === "mythic" } : null })} />
        {t("hasUnique")}
      </label>
      {u ? (
        <div className="space-y-2 rounded border border-border p-2">
          <Row label={t("uniqueKey")} htmlFor="f-ukey">
            <input id="f-ukey" className={ctl} value={u.key} onChange={(e) => set({ unique_effect: { ...u, key: e.target.value } })} />
          </Row>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={u.mastery_scaling} onChange={(e) => set({ unique_effect: { ...u, mastery_scaling: e.target.checked } })} />
            {t("masteryScaling")}
          </label>
          <EffectListEditor value={u.effects} onChange={(effects) => set({ unique_effect: { ...u, effects } })} registry={registry} meta={meta} />
        </div>
      ) : null}
      <Row label={t("setMembership")} htmlFor="f-set">
        <select id="f-set" className={ctl} value={data.set_code ?? ""} onChange={(e) => set({ set_code: e.target.value || null })}>
          <option value="">—</option>
          {meta.sets.map((s) => (
            <option key={s.code} value={s.code}>
              {s.code}
            </option>
          ))}
        </select>
      </Row>
      {itemSet ? (
        <ul className="text-xs" data-testid="set-bonuses">
          {itemSet.bonuses.map((b) => (
            <li key={b.pieces}>
              {t("pieces", { n: b.pieces })}: {b.effects.map((e) => `${e.effect_type} ${JSON.stringify(e.params)}`).join("; ")}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function SocketsTab({ data, meta, set }: TabProps) {
  const t = useTranslations("itemStudio");
  return (
    <div className="space-y-3 text-sm">
      <div className="flex gap-2">
        <Row label={t("socketMin")} htmlFor="f-smin">
          <input id="f-smin" type="number" min={0} max={meta.max_sockets} className={num} value={data.sockets.min} onChange={(e) => set({ sockets: { ...data.sockets, min: Number(e.target.value) } })} />
        </Row>
        <Row label={t("socketMax")} htmlFor="f-smax">
          <input id="f-smax" type="number" min={0} max={meta.max_sockets} className={num} value={data.sockets.max} onChange={(e) => set({ sockets: { ...data.sockets, max: Number(e.target.value) } })} />
        </Row>
        <Row label={t("durabilityMax")} htmlFor="f-dur">
          <input id="f-dur" type="number" min={0} className={num} value={data.durability.max} onChange={(e) => set({ durability: { max: Number(e.target.value) } })} />
        </Row>
      </div>
      <p className="text-xs text-muted">{t("upgradeCurve", { max: meta.max_upgrade_level, pct: meta.upgrade_pct_per_level })}</p>
      <table className="text-xs">
        <tbody>
          {data.base_stats.map((s) => (
            <tr key={s.stat}>
              <td className="pr-2 font-mono">{s.stat}</td>
              {[0, 5, meta.max_upgrade_level].map((lvl) => (
                <td key={lvl} className="pr-2">
                  +{lvl}: {Math.round(s.amount * (1 + (lvl * meta.upgrade_pct_per_level) / 100) * 100) / 100}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourcesTab({ data, meta, set, view }: TabProps & { view: Inspector }) {
  const t = useTranslations("itemStudio");
  return (
    <div className="space-y-3 text-sm">
      <fieldset className="space-y-1">
        <legend className="font-semibold">{t("declaredSources")}</legend>
        {data.sources.map((s, i) => (
          <div key={i} className="flex gap-2">
            <select aria-label={t("sourceKind")} className="rounded border border-border bg-bg px-1" value={s.kind} onChange={(e) => set({ sources: data.sources.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)) })}>
              {meta.source_kinds.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <input aria-label={t("sourceRef")} className="rounded border border-border bg-bg px-1" value={s.ref ?? ""} onChange={(e) => set({ sources: data.sources.map((x, j) => (j === i ? { ...x, ref: e.target.value || null } : x)) })} />
            <button type="button" aria-label={t("remove")} onClick={() => set({ sources: data.sources.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <button type="button" className="underline" onClick={() => set({ sources: [...data.sources, { kind: "drop", ref: null }] })}>
          {t("addSource")}
        </button>
      </fieldset>
      <div data-testid="reverse-references">
        <h3 className="font-semibold">{t("reverseRefs")}</h3>
        {Object.entries(view.references).map(([kind, refs]) => (
          <p key={kind} className="text-xs">
            <span className="text-muted">{t(`ref.${kind}`)}:</span> {refs.length ? refs.map((r) => `${r.code}${r.match ? ` (${r.match})` : ""}${r.via ? ` ← ${r.via}` : ""}`).join(", ") : "—"}
          </p>
        ))}
      </div>
    </div>
  );
}

function CraftTab({ data, set }: { data: ItemData; set: (p: Partial<ItemData>) => void }) {
  const t = useTranslations("itemStudio");
  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted">{t("craftHint")}</p>
      <fieldset className="space-y-1">
        <legend className="font-semibold">{t("salvage")}</legend>
        {data.salvage.map((s, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2" data-testid="salvage-row">
            <input aria-label={t("salvageItem")} className="rounded border border-border bg-bg px-1" value={s.template_code} onChange={(e) => set({ salvage: data.salvage.map((x, j) => (j === i ? { ...x, template_code: e.target.value } : x)) })} />
            <input aria-label={t("minQty")} type="number" min={1} className={num} value={s.min_qty} onChange={(e) => set({ salvage: data.salvage.map((x, j) => (j === i ? { ...x, min_qty: Number(e.target.value) } : x)) })} />
            <input aria-label={t("maxQty")} type="number" min={1} className={num} value={s.max_qty} onChange={(e) => set({ salvage: data.salvage.map((x, j) => (j === i ? { ...x, max_qty: Number(e.target.value) } : x)) })} />
            <input aria-label={t("chance")} type="number" min={0.01} max={100} className={num} value={s.chance_pct} onChange={(e) => set({ salvage: data.salvage.map((x, j) => (j === i ? { ...x, chance_pct: Number(e.target.value) } : x)) })} />
            <button type="button" aria-label={t("remove")} onClick={() => set({ salvage: data.salvage.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <button type="button" className="underline" onClick={() => set({ salvage: [...data.salvage, { template_code: "", min_qty: 1, max_qty: 1, chance_pct: 100 }] })}>
          {t("addSalvage")}
        </button>
      </fieldset>
    </div>
  );
}

function PreviewTab({ code, data, view, dirty }: { code: string; data: ItemData; view: Inspector; dirty: boolean }) {
  const t = useTranslations("itemStudio");
  const errorMessage = useErrorMessage();
  const profiles = useQuery({ queryKey: ["preview-profiles"], queryFn: adminItemsApi.profiles });
  const [picked, setProfile] = useState("");
  const profile = picked || profiles.data?.[0]?.code || "";
  const run = useMutation({ mutationFn: (p: string) => adminItemsApi.preview(code, p) });
  return (
    <div className="space-y-3 text-sm">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" data-testid="tooltip-previews">
        {LOCALES.map((l) => (
          <div key={l} lang={l} className="rounded border border-border bg-bg p-2">
            <p className="text-[10px] uppercase text-muted">{l}</p>
            <p className="font-semibold">{view.texts.name[l].value || <span className="text-legendary">{view.texts.name.en.value || code} ({t("fallback")})</span>}</p>
            <p className="text-xs">
              {t(`rarityName.${data.rarity}`)} · T{data.tier} · Lv{data.min_level}
            </p>
            <ul className="text-xs">
              {data.base_stats.map((s) => (
                <li key={s.stat}>
                  +{s.amount} {s.stat}
                </li>
              ))}
            </ul>
            {view.texts.short_description[l].value ? <p className="text-xs italic">{view.texts.short_description[l].value}</p> : null}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="pv-profile">{t("testCharacter")}</label>
        <select id="pv-profile" className="rounded border border-border bg-bg px-1" value={profile} onChange={(e) => setProfile(e.target.value)} data-testid="preview-profile">
          {(profiles.data ?? []).map((p) => (
            <option key={p.code} value={p.code}>
              {t("previewOn", { cls: p.class, level: p.level })}
            </option>
          ))}
        </select>
        <button type="button" data-testid="run-preview" disabled={!profile || run.isPending} onClick={() => run.mutate(profile)} className="rounded border border-border px-2">
          {t("runPreview")}
        </button>
        {dirty ? <span className="text-xs text-muted">{t("previewUsesSaved")}</span> : null}
      </div>
      {run.error ? <p role="alert" className="text-bad">{errorMessage(run.error)}</p> : null}
      {run.data ? (
        <div data-testid="preview-result">
          <p className={run.data.requirements_met ? "text-good" : "text-bad"}>
            {run.data.requirements_met ? t("reqPass") : t("reqFail", { list: run.data.unmet.map((u) => (u.stat ? `${u.stat} ${u.have}/${u.required}` : u.kind)).join(", ") })}
          </p>
          <table className="text-xs">
            <tbody>
              {Object.entries(run.data.deltas).map(([k, v]) => (
                <tr key={k}>
                  <td className="pr-2 font-mono">{k}</td>
                  <td className="pr-2 text-muted">{run.data.before[k]}</td>
                  <td className={v >= 0 ? "text-good" : "text-bad"}>
                    {v >= 0 ? "+" : ""}
                    {v}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function HistoryTab({ code, onChanged }: { code: string; onChanged: () => void }) {
  const t = useTranslations("itemStudio");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const history = useQuery({ queryKey: ["item-history", code], queryFn: () => adminItemsApi.history(code) });
  const [pair, setPair] = useState<[number, number] | null>(null);
  const diff = useQuery({ queryKey: ["item-diff", code, pair], queryFn: () => adminItemsApi.diff(code, pair![0], pair![1]), enabled: !!pair });
  const rollback = useMutation({
    mutationFn: (rev: number) => adminItemsApi.rollback(code, rev),
    onSuccess: () => {
      toast("success", t("rolledBack"));
      history.refetch();
      onChanged();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (history.isLoading) return <p>{t("loading")}</p>;
  const revs = history.data ?? [];
  return (
    <div className="space-y-2 text-sm">
      {!revs.length ? <p className="text-muted">{t("noHistory")}</p> : null}
      <table className="w-full text-xs" data-testid="history-table">
        <thead>
          <tr className="text-left text-muted">
            <th>{t("revision")}</th>
            <th>{t("status")}</th>
            <th>{t("release")}</th>
            <th>{t("author")}</th>
            <th>{t("time")}</th>
            <th>{t("summary")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {revs.map((r, i) => (
            <tr key={r.revision_no}>
              <td>r{r.revision_no}</td>
              <td>{r.status}</td>
              <td>v{r.release_version}</td>
              <td>{r.created_by ?? "system"}</td>
              <td>{new Date(r.created_at).toLocaleString()}</td>
              <td>{r.change_summary ?? ""}</td>
              <td className="space-x-2">
                {i + 1 < revs.length ? (
                  <button type="button" className="underline" onClick={() => setPair([revs[i + 1].revision_no, r.revision_no])}>
                    {t("diffPrev")}
                  </button>
                ) : null}
                {i > 0 ? (
                  <button type="button" className="underline" data-testid={`rollback-${r.revision_no}`} onClick={() => window.confirm(t("rollbackConfirm", { rev: r.revision_no })) && rollback.mutate(r.revision_no)}>
                    {t("rollback")}
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {diff.data ? (
        <ul className="text-xs" data-testid="history-diff">
          {diff.data.diff.map((d) => (
            <li key={d.path}>
              <span className="font-mono">{d.path}</span>: <span className="text-bad line-through">{JSON.stringify(d.from)}</span> → <span className="text-good">{JSON.stringify(d.to)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
