"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { STATUS_RARITY_TEXT, type StatusRarity } from "@/lib/api/goals";
import { overviewApi, type ActivityItem } from "@/lib/api/overview";

const SUMMARY_COUNT = 6;

/** Localized activity log: structured records → sentences; summary first, details on demand. */
export function ActivityLog({ characterId }: { characterId: number }) {
  const t = useTranslations("shell");
  const q = useQuery({ queryKey: ["activity", characterId], queryFn: () => overviewApi.activity(characterId), refetchInterval: 60_000 });
  const [expanded, setExpanded] = useState(false);
  const items = q.data ?? [];
  const shown = expanded ? items : items.slice(0, SUMMARY_COUNT);
  return (
    <section aria-label={t("activity")} className="rounded border border-border bg-panel p-2 text-sm" data-testid="activity-log">
      <h2 className="mb-1 text-xs font-semibold uppercase text-muted">{t("activity")}</h2>
      {!items.length ? <p className="text-xs text-muted">{t("noActivity")}</p> : null}
      <ol className="space-y-1" aria-live="polite">
        {shown.map((a, i) => (
          <ActivityLine key={`${a.type}-${a.at}-${i}`} a={a} />
        ))}
      </ol>
      {items.length > SUMMARY_COUNT ? (
        <button type="button" className="mt-1 text-xs underline" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
          {expanded ? t("showLess") : t("showMore", { n: items.length - SUMMARY_COUNT })}
        </button>
      ) : null}
    </section>
  );
}

function ActivityLine({ a }: { a: ActivityItem }) {
  const t = useTranslations("shell");
  const f = useFormatter();
  const when = f.relativeTime(new Date(a.at));
  const signals = (a.signals as { kind: string; levels?: number; count?: number }[] | undefined) ?? [];
  const levelUp = signals.find((s) => s.kind === "level_up");
  const rare = signals.find((s) => s.kind === "rare_drops");
  let text: string;
  let cls = "";
  switch (a.type) {
    case "afk_claimed":
      text = t("act.afk", { zone: String(a.zone_code), xp: f.number(Number(a.xp ?? 0)), gold: f.number(Number(a.gold ?? 0)), kills: f.number(Number(a.kills ?? 0)) });
      break;
    case "craft":
      text = t("act.craft", { recipe: String(a.recipe), ok: String(a.successes ?? 0), fail: String(a.failures ?? 0) });
      break;
    case "quest":
      text = t("act.quest", { name: String(a.name) });
      cls = "text-good";
      break;
    case "achievement":
      text = t("act.achievement", { name: String(a.name) });
      cls = `font-semibold ${STATUS_RARITY_TEXT[a.rarity as StatusRarity] ?? ""}`;
      break;
    case "market_sold":
    case "market_bought":
      text = t(`act.${a.type}`, { item: String(a.template_code), gold: f.number(Number(a.total ?? 0)) });
      break;
    case "profession_level":
      text = t("act.profession", { profession: String(a.profession), level: String(a.level) });
      break;
    default:
      text = a.type;
  }
  return (
    <li className={cls}>
      <span className="mr-1 text-xs text-muted">{when}</span>
      {text}
      {levelUp ? <span className="ml-1 font-bold text-accent">{t("act.levelUp", { n: String(levelUp.levels ?? 1) })}</span> : null}
      {rare ? <span className="ml-1 text-epic">{t("act.rare", { n: String(rare.count ?? 1) })}</span> : null}
    </li>
  );
}
