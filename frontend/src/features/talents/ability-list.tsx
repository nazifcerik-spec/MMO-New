"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EffectList } from "@/components/effects/effect-text";
import { talentApi } from "@/lib/api/talents";

export function AbilityList({ characterId }: { characterId: number }) {
  const t = useTranslations("abilities");
  const { data } = useQuery({ queryKey: ["abilities", characterId], queryFn: () => talentApi.abilities(characterId) });
  if (!data) return null;
  return (
    <section aria-labelledby="abilities-title" className="space-y-2 rounded border border-border bg-panel p-4">
      <h2 id="abilities-title" className="font-semibold">
        {t("title")}
      </h2>
      {data.awakening ? (
        <p className={`text-sm ${data.awakening.active ? "text-legendary" : "text-muted"}`} data-testid="awakening">
          {t("awakening", { name: data.awakening.name })}
          {data.awakening.active ? "" : ` · ${t("awakeningInactive", { level: data.awakening.required_level })}`}
        </p>
      ) : null}
      <ul className="grid gap-2 md:grid-cols-2" data-testid="ability-list">
        {data.abilities.map((a) => (
          <li key={a.code} className={`rounded border border-border p-2 ${a.unlocked ? "" : "opacity-50"}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold">{a.name}</span>
              <span className="text-xs text-muted">{t.has(`types.${a.type}`) ? t(`types.${a.type}`) : a.type}</span>
            </div>
            {a.description ? <p className="text-xs text-muted">{a.description}</p> : null}
            <EffectList effects={a.effects} labels={data.labels} />
            <p className="text-[11px] text-muted">
              {a.unlocked ? null : t("unlockAt", { level: a.unlock_level })}
              {a.cooldown_s ? ` ${t("cooldown", { seconds: a.cooldown_s })}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
