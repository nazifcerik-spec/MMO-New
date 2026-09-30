"use client";

import { useTranslations } from "next-intl";

export interface EffectData {
  effect_type: string;
  schema_version?: number;
  params: Record<string, unknown>;
}

type Labels = Record<string, string>;

function signed(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
}

function humanize(code: string): string {
  return code
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Render a structured effect as a localized one-liner. Unknown types degrade to their code. */
export function useEffectText(labels: Labels = {}) {
  const t = useTranslations("effects");
  const statName = (stat: string) => labels[`stat.${stat.toLowerCase()}.name`] ?? stat;
  const profName = (p: string) => labels[`profession.${p}.name`] ?? humanize(p);

  const render = (e: EffectData): string => {
    // Params were validated server-side by the effect registry; treat them as loosely typed here.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const p = e.params as Record<string, any>;
    switch (e.effect_type) {
      case "STAT_FLAT":
        return t("statFlat", { stat: statName(p.stat), amount: signed(p.amount) });
      case "STAT_PERCENT":
        return t("statPercent", { stat: statName(p.stat), percent: signed(p.percent) });
      case "DAMAGE_MULTIPLIER": {
        const base = p.damage_type
          ? t("damageTyped", { type: humanize(p.damage_type), percent: signed(p.percent) })
          : t("damage", { percent: signed(p.percent) });
        return p.condition ? t("when", { condition: cond(p.condition), effects: base }) : base;
      }
      case "DAMAGE_REDUCTION":
        return t("damageReduction", { percent: p.percent });
      case "HEAL_MULTIPLIER":
        return t(`heal.${(p.scope as string) ?? "outgoing"}`, { percent: signed(p.percent) });
      case "LOOT_MODIFIER":
        return t(`loot.${p.scope}`, { percent: signed(p.percent) });
      case "PROGRESSION_MODIFIER": {
        const txt = t(`progression.${p.kind}`, { percent: signed(p.percent) });
        return p.limit_points ? `${txt} ${t("limitPoints", { points: p.limit_points })}` : txt;
      }
      case "PROFESSION_YIELD_MOD":
        return t(`profession.${p.kind}`, { profession: profName(p.profession), percent: signed(p.percent) });
      case "THRESHOLD_TRIGGER":
        return t("when", {
          condition: cond(p.condition),
          effects: ((p.effects as EffectData[]) ?? []).map(render).join(", "),
        });
      default:
        return t("other", { type: humanize(e.effect_type.toLowerCase()) });
    }
  };

  function cond(c: { metric: string; op: string; value: number }): string {
    return t(`cond.${c.metric}`, { op: t(`ops.${c.op}`), value: c.value });
  }

  return render;
}

export function EffectList({ effects, labels }: { effects: EffectData[]; labels?: Labels }) {
  const render = useEffectText(labels);
  return (
    <ul className="space-y-0.5 text-sm" data-testid="effect-list">
      {effects.map((e, i) => (
        <li key={i} className="font-mono">
          • {render(e)}
        </li>
      ))}
    </ul>
  );
}
