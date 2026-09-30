"use client";

import { useTranslations } from "next-intl";

import { EffectList } from "@/components/effects/effect-text";
import type { EquipPreview, ItemView, Unmet } from "@/lib/api/inventory";

export const RARITY_TEXT: Record<string, string> = {
  worn: "text-muted",
  common: "",
  fine: "text-good",
  rare: "text-accent",
  epic: "text-epic",
  legendary: "text-legendary",
  mythic: "text-legendary font-bold",
  relic: "text-bad font-bold",
};

export function useUnmetText() {
  const t = useTranslations("inventory");
  return (u: Unmet) =>
    u.kind === "stat"
      ? t("unmet.stat", { stat: u.stat ?? "", have: u.have ?? 0, need: u.required ?? 0 })
      : u.kind === "level"
        ? t("unmet.level", { need: u.required ?? 0 })
        : t(`unmet.${u.kind}`, { code: u.code ?? "" });
}

/** Localized item tooltip: identity, requirements (pass/fail), stats, affixes, unique, bind, durability,
 *  marketability, sources and — when given — the equip stat delta. */
export function ItemTooltip({ item, labels, preview }: { item: ItemView; labels: Record<string, string>; preview?: EquipPreview }) {
  const t = useTranslations("inventory");
  const tr = useTranslations("itemStudio");
  const unmetText = useUnmetText();
  const statName = (s: string) => labels[`stat.${s.toLowerCase()}.name`] ?? s;
  const broken = item.durability_max > 0 && item.durability === 0;
  return (
    <div className="space-y-1.5 rounded border border-border bg-panel p-3 text-sm" data-testid="item-tooltip">
      <p className={`font-semibold ${RARITY_TEXT[item.rarity] ?? ""}`} data-testid="tooltip-name">
        {item.name}
        {item.upgrade_level ? ` +${item.upgrade_level}` : ""}
      </p>
      <p className="text-xs text-muted">
        {tr(`rarityName.${item.rarity}`)} · T{item.tier} · {tr(`category.${item.category}`)}
        {item.slot ? ` · ${tr(`slot.${item.slot}`)}` : ""}
        {item.weapon_family ? ` · ${item.weapon_family}` : item.armor_family ? ` · ${item.armor_family}` : ""}
      </p>
      {item.description ? <p className="text-xs italic">{item.description}</p> : null}
      <ul className="text-xs" aria-label={t("requirements")}>
        <li className={item.unmet?.some((u) => u.kind === "level") ? "text-bad" : ""}>{t("reqLevel", { level: item.min_level })}</li>
        {Object.entries(item.requirements.stats ?? {}).map(([s, v]) => {
          const miss = item.unmet?.find((u) => u.kind === "stat" && u.stat === s);
          return (
            <li key={s} className={miss ? "text-bad" : ""}>
              {t("reqStat", { stat: statName(s), value: v })}
              {miss ? ` (${miss.have})` : " ✓"}
            </li>
          );
        })}
        {item.unmet
          ?.filter((u) => u.kind !== "level" && u.kind !== "stat")
          .map((u, i) => (
            <li key={i} className="text-bad">
              {unmetText(u)}
            </li>
          ))}
      </ul>
      <div className={broken ? "opacity-50" : ""}>
        <EffectList effects={item.effects.filter((e) => !item.affixes.some((a) => a.effect === e))} labels={labels} />
      </div>
      {item.affixes.length ? (
        <div>
          <p className="text-xs text-muted">{t("affixes")}</p>
          <EffectList effects={item.affixes.map((a) => a.effect)} labels={labels} />
        </div>
      ) : null}
      {item.unique_effect ? (
        <div className="text-legendary">
          <p className="text-xs">{t("unique")}</p>
          <EffectList effects={item.unique_effect.effects} labels={labels} />
        </div>
      ) : null}
      <p className="text-xs">
        {item.durability_max ? (
          <span className={broken ? "text-bad" : ""}>{t("durability", { now: item.durability, max: item.durability_max })} · </span>
        ) : null}
        {item.sockets ? `${t("sockets", { n: item.sockets })} · ` : ""}
        {item.bound ? t("bound") : tr(`bind.${item.bind_policy}`)}
      </p>
      <p className="text-xs" data-testid="tooltip-market">
        {item.tradeable ? t("tradeable") : t("notTradeable")} · {item.sellable ? t("vendor", { gold: item.vendor_value }) : t("notSellable")}
      </p>
      {item.sources.length ? <p className="text-xs text-muted">{t("sources", { list: item.sources.map((s) => t(`source.${s.kind}`)).join(", ") })}</p> : null}
      {broken ? <p className="text-xs text-bad">{t("broken")}</p> : null}
      {preview ? (
        <div data-testid="tooltip-delta">
          <p className="text-xs text-muted">{preview.replaces ? t("deltaVsEquipped") : t("deltaIfEquipped")}</p>
          <ul className="text-xs">
            {Object.entries(preview.deltas).map(([k, v]) => (
              <li key={k} className={v >= 0 ? "text-good" : "text-bad"}>
                {v >= 0 ? "+" : ""}
                {Math.round(v * 100) / 100} {statName(k)}
              </li>
            ))}
            {!Object.keys(preview.deltas).length ? <li className="text-muted">{t("noDelta")}</li> : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
