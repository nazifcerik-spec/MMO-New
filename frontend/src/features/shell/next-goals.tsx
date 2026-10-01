"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import type { NextGoal } from "@/lib/api/overview";

const HREF: Partial<Record<NextGoal["kind"], string>> = {
  afk_claim: "",
  stat_points: "",
  talent_points: "/talents",
  class_stage_ready: "/class",
  class_stage: "/class",
  zone_unlock: "/zones",
  profession_rank: "/professions",
  item_tier: "/inventory",
};

/** "Next meaningful goal" card: actionable items first, then the nearest milestones. */
export function NextGoals({ characterId, goals, compact = false }: { characterId: number; goals: NextGoal[]; compact?: boolean }) {
  const t = useTranslations("shell");
  if (!goals.length) return null;
  const list = compact ? goals.slice(0, 2) : goals;
  return (
    <section aria-label={t("nextGoals")} className="rounded border border-border bg-panel p-2 text-sm" data-testid="next-goals">
      <h2 className="mb-1 text-xs font-semibold uppercase text-muted">{t("nextGoals")}</h2>
      <ul className="space-y-1">
        {list.map((g, i) => {
          const href = `/game/characters/${characterId}${HREF[g.kind] ?? ""}`;
          const actionable = ["afk_claim", "stat_points", "talent_points", "class_stage_ready"].includes(g.kind);
          return (
            <li key={i}>
              <Link href={href} className={`hover:underline ${actionable ? "font-semibold text-accent" : ""}`} data-testid={`goal-${g.kind}`}>
                {t(`goal.${g.kind}`, { ...(g as Record<string, string | number>) })}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
