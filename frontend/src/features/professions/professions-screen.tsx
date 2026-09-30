"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { professionApi, type ProfessionCard } from "@/lib/api/professions";

export function ProfessionsScreen({ characterId }: { characterId: number }) {
  const t = useTranslations("professions");
  const tc = useTranslations("common");
  const f = useFormatter();
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["professions", characterId];
  const q = useQuery({ queryKey: key, queryFn: () => professionApi.view(characterId) });
  const [type, setType] = useState<"all" | "gathering" | "crafting">("all");
  const done = (msg: string) => {
    toast("success", msg);
    qc.invalidateQueries({ queryKey: key });
  };
  const license = useMutation({
    mutationFn: ({ code, active }: { code: string; active: boolean }) => professionApi.license(characterId, code, active),
    onSuccess: (r) => done(r.cost_gold ? t("licensePaid", { gold: r.cost_gold }) : t("licenseUpdated")),
    onError: (e) => toast("error", errorMessage(e)),
  });
  const specialize = useMutation({
    mutationFn: ({ code, spec }: { code: string; spec: string }) => professionApi.specialize(characterId, code, spec),
    onSuccess: () => done(t("specialized")),
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (q.isLoading) return <p>{tc("loading")}</p>;
  if (!q.data) return <p role="alert">{tc("error")}</p>;
  const v = q.data;
  const list = v.professions.filter((p) => type === "all" || p.type === type);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded border border-border bg-panel p-2 text-sm" data-testid="license-summary">
        <span className="font-semibold">{t("licenses", { active: v.licenses.active, max: v.licenses.max })}</span>
        <span className="text-xs text-muted">
          {v.licenses.free_remaining ? t("freeLicenses", { n: v.licenses.free_remaining }) : t("swapRules")}
        </span>
        {v.licenses.cooldown_until ? (
          <span className="text-xs text-legendary">{t("cooldown", { at: f.dateTime(new Date(v.licenses.cooldown_until), { dateStyle: "medium", timeStyle: "short" }) })}</span>
        ) : null}
        <label className="ml-auto text-xs">
          {t("show")}{" "}
          <select className="rounded border border-border bg-bg px-1" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option value="all">{t("all")}</option>
            <option value="gathering">{t("type.gathering")}</option>
            <option value="crafting">{t("type.crafting")}</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-muted">{t("rules", { cap: v.unlicensed_level_cap, spec: v.specialization_level })}</p>
      <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {list.map((p) => (
          <ProfessionItem
            key={p.code}
            p={p}
            specLevel={v.specialization_level}
            canLicense={p.licensed || v.licenses.active < v.licenses.max}
            busy={license.isPending || specialize.isPending}
            onLicense={(active) =>
              (active && p.swap_cost_gold ? window.confirm(t("licenseCostConfirm", { gold: p.swap_cost_gold })) : true) &&
              (!active ? window.confirm(t("unlicenseConfirm", { name: p.name, cap: v.unlicensed_level_cap })) : true) &&
              license.mutate({ code: p.code, active })
            }
            onSpecialize={(spec) => window.confirm(t("specializeConfirm")) && specialize.mutate({ code: p.code, spec })}
          />
        ))}
      </ul>
    </div>
  );
}

function ProfessionItem({
  p,
  specLevel,
  canLicense,
  busy,
  onLicense,
  onSpecialize,
}: {
  p: ProfessionCard;
  specLevel: number;
  canLicense: boolean;
  busy: boolean;
  onLicense: (active: boolean) => void;
  onSpecialize: (spec: string) => void;
}) {
  const t = useTranslations("professions");
  const pct = p.xp_to_next ? Math.min(100, (100 * p.xp) / p.xp_to_next) : 100;
  const mods = Object.entries(p.modifiers).filter(([, v]) => v);
  return (
    <li className={`space-y-1 rounded border p-2 text-sm ${p.licensed ? "border-accent" : "border-border"}`} data-testid={`profession-${p.code}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{p.name}</span>
        <span className="font-mono text-xs" data-testid={`prof-level-${p.code}`}>
          {p.rank_name} · {t("level", { level: p.level, cap: p.level_cap_now })}
        </span>
      </div>
      <div role="progressbar" aria-label={t("xpOf", { name: p.name })} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} className="h-1.5 w-full rounded bg-bg">
        <div className="h-full rounded bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted">
        {t(`type.${p.type}`)} · {t("tool", { tool: p.tool_kind })} · {p.stats.join("/")} ({t("statBonus", { speed: p.stat_bonuses.speed, quality: p.stat_bonuses.quality })})
      </p>
      {mods.length ? (
        <p className="text-xs text-good">{mods.map(([k, val]) => t(`mod.${k}`, { pct: val })).join(" · ")}</p>
      ) : null}
      {p.title_earned ? <p className="text-xs text-legendary" data-testid={`title-${p.code}`}>🏆 {p.title}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid={`license-${p.code}`}
          disabled={busy || (!p.licensed && !canLicense)}
          onClick={() => onLicense(!p.licensed)}
          className={`rounded px-2 py-0.5 text-xs ${p.licensed ? "border border-border" : "bg-accent font-semibold text-bg"} disabled:opacity-50`}
        >
          {p.licensed ? t("revoke") : p.swap_cost_gold ? t("licenseFor", { gold: p.swap_cost_gold }) : t("license")}
        </button>
        {p.licensed && p.level >= specLevel ? (
          <label className="text-xs">
            {t("specialization")}{" "}
            <select
              className="rounded border border-border bg-bg px-1"
              value={p.specialization_code ?? ""}
              data-testid={`spec-${p.code}`}
              disabled={busy}
              onChange={(e) => e.target.value && onSpecialize(e.target.value)}
            >
              <option value="">—</option>
              {p.specializations.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="text-xs text-muted">{t("specAt", { level: specLevel, names: p.specializations.map((s) => s.name).join(" / ") })}</span>
        )}
      </div>
    </li>
  );
}
