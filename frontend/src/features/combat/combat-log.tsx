"use client";

import { useFormatter, useTranslations } from "next-intl";

import type { CombatEvent, SampleLog } from "@/lib/api/afk-profile";

const STYLE: Record<string, string> = {
  CRIT: "font-semibold text-legendary",
  CRIT_HEAL: "font-semibold text-good",
  HEAL: "text-good",
  BLOCK: "text-accent",
  DODGE: "text-muted",
  PROC: "text-epic",
  DEATH: "font-bold text-bad",
  END: "font-semibold",
};
const SHOWN = new Set(["HIT", "CRIT", "BLOCK", "DODGE", "HEAL", "CRIT_HEAL", "PROC", "ABILITY", "SHIELD", "DEBUFF", "POTION", "DEATH", "END", "TICK"]);

/** Readable text combat log: summary first (counts), localized line-by-line details on demand. */
export function CombatLog({ log }: { log: SampleLog }) {
  const t = useTranslations("combatLog");
  const f = useFormatter();
  const counts: Record<string, number> = {};
  for (const e of log.events) counts[e.event_type] = (counts[e.event_type] ?? 0) + 1;
  const name = (id?: string) => {
    if (!id) return "";
    const a = log.actors[id];
    if (!a) return id;
    return a.side === "players" ? t("you") : (log.labels[`enemy.${a.code}.name`] ?? a.code.replace(/_/g, " "));
  };
  const ability = (code?: string | null) => (code ? (log.labels[`ability.${code}.name`] ?? code.replace(/_/g, " ")) : t("attack"));
  const line = (e: CombatEvent) => {
    const side = (id?: string) => (id && log.actors[id]?.side === "players" ? "yes" : "no");
    const p = { self: side(e.actor_id), tself: side(e.target_id), actor: name(e.actor_id), target: name(e.target_id), ability: ability(e.ability_code), amount: f.number(Math.round(e.amount ?? 0)), kind: e.kind ?? "", proc: (e.proc ?? "").split(":")[0].replace(/_/g, " "), outcome: e.outcome ?? "" };
    return t.has(`event.${e.event_type}`) ? t(`event.${e.event_type}`, p) : e.event_type;
  };
  const end = log.events.find((e) => e.event_type === "END");
  return (
    <div className="space-y-1 text-xs" data-testid="combat-log">
      <p className="font-semibold">
        {end ? t(`outcome.${end.outcome}`) : t("sample")} ·{" "}
        {t("summary", { hits: counts.HIT ?? 0, crits: counts.CRIT ?? 0, blocks: counts.BLOCK ?? 0, dodges: counts.DODGE ?? 0, procs: counts.PROC ?? 0, kills: counts.DEATH ?? 0 })}
      </p>
      <details>
        <summary className="cursor-pointer underline">{t("details")}</summary>
        <ol className="mt-1 max-h-64 space-y-0.5 overflow-y-auto font-mono">
          {log.events
            .filter((e) => SHOWN.has(e.event_type))
            .map((e, i) => (
              <li key={i} className={STYLE[e.event_type] ?? ""}>
                <span className="text-muted">[{e.t.toFixed(1)}s]</span> {line(e)}
              </li>
            ))}
        </ol>
      </details>
    </div>
  );
}
