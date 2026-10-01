"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { inventoryApi, type ItemView } from "@/lib/api/inventory";

import { EnchantActions } from "./enchant-actions";
import { ItemTooltip, RARITY_TEXT, useUnmetText } from "./item-tooltip";
import { RepairPanel, TradeActions } from "./trade-actions";

export function InventoryScreen({ characterId }: { characterId: number }) {
  const t = useTranslations("inventory");
  const tr = useTranslations("itemStudio");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const unmetText = useUnmetText();
  const qc = useQueryClient();
  const eq = useQuery({ queryKey: ["equipment", characterId], queryFn: () => inventoryApi.equipment(characterId) });
  const inv = useQuery({ queryKey: ["inventory", characterId], queryFn: () => inventoryApi.inventory(characterId) });
  const mail = useQuery({ queryKey: ["mailbox", characterId], queryFn: () => inventoryApi.inventory(characterId, "mail") });
  const [selected, setSelected] = useState<ItemView | null>(null);
  const [category, setCategory] = useState("");
  const preview = useQuery({
    queryKey: ["equip-preview", characterId, selected?.id],
    queryFn: () => inventoryApi.preview(characterId, selected!.id),
    enabled: !!selected && !!selected.slot && selected.location === "inventory",
  });
  const refresh = () => {
    for (const k of ["equipment", "inventory", "mailbox", "progression"]) qc.invalidateQueries({ queryKey: [k, characterId] });
    qc.invalidateQueries({ queryKey: ["equip-preview", characterId] });
  };
  const onError = (e: unknown) => toast("error", errorMessage(e));
  const equip = useMutation({
    mutationFn: (item: ItemView) => inventoryApi.equip(characterId, item.id),
    onSuccess: (r) => {
      toast("success", t("equipped", { slot: tr(`slot.${r.slot.replace(/_\d$/, "")}`) }));
      setSelected(null);
      refresh();
    },
    onError,
  });
  const unequip = useMutation({ mutationFn: (slot: string) => inventoryApi.unequip(characterId, slot), onSuccess: refresh, onError });
  const destroy = useMutation({
    mutationFn: (item: ItemView) => inventoryApi.destroy(characterId, item.id),
    onSuccess: () => {
      setSelected(null);
      refresh();
    },
    onError,
  });
  const claimMail = useMutation({
    mutationFn: () => inventoryApi.claimMail(characterId),
    onSuccess: (r) => {
      toast("success", t("mailClaimed", { n: r.moved }));
      refresh();
    },
    onError,
  });

  if (eq.isLoading || inv.isLoading) return <p>{tc("loading")}</p>;
  if (!eq.data || !inv.data) return <p role="alert">{tc("error")}</p>;
  const labels = { ...eq.data.labels, ...inv.data.labels, ...(mail.data?.labels ?? {}) };
  const items = inv.data.items.filter((i) => !category || i.category === category);
  const categories = [...new Set(inv.data.items.map((i) => i.category))];
  const statName = (s: string) => labels[`stat.${s.toLowerCase()}.name`] ?? s;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)_20rem]">
      <section id="equipment" aria-labelledby="equip-title" className="scroll-mt-4 space-y-2" data-testid="equipment">
        <h2 id="equip-title" className="font-semibold">
          {t("equipment")}
        </h2>
        <ul className="space-y-1 text-sm">
          {eq.data.slots.map((s) => (
            <li key={s.code} className="flex items-center gap-2 rounded border border-border px-2 py-1" data-testid={`slot-${s.code}`}>
              <span className="w-20 shrink-0 text-xs text-muted">{tr(`slot.${s.accepts[0]}`)}</span>
              {s.item ? (
                <>
                  <button type="button" className={`truncate text-left ${RARITY_TEXT[s.item.rarity] ?? ""}`} onClick={() => setSelected(s.item)}>
                    {s.item.name}
                  </button>
                  <button type="button" className="ml-auto text-xs underline" aria-label={t("unequipSlot", { slot: s.code })} onClick={() => unequip.mutate(s.code)}>
                    {t("unequip")}
                  </button>
                </>
              ) : (
                <span className="text-xs text-muted">—</span>
              )}
            </li>
          ))}
        </ul>
        <details className="text-xs" open>
          <summary className="font-semibold">{t("stats")}</summary>
          <dl className="grid grid-cols-2 gap-x-2" data-testid="equipment-stats">
            {Object.entries(eq.data.primary).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{k}</dt>
                <dd className="font-mono">{Math.round(v)}</dd>
              </div>
            ))}
            {["max_hp", "attack_power", "spell_power", "armor", "magic_resist", "crit_chance", "dodge"].map((k) =>
              eq.data!.derived[k] !== undefined ? (
                <div key={k} className="contents">
                  <dt className="text-muted">{statName(k)}</dt>
                  <dd className="font-mono" data-testid={`stat-${k}`}>
                    {Math.round(eq.data!.derived[k] * 10) / 10}
                  </dd>
                </div>
              ) : null,
            )}
          </dl>
        </details>
      </section>

      <section aria-labelledby="bag-title" className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="bag-title" className="font-semibold">
            {t("bag")}
          </h2>
          <span className={`font-mono text-xs ${inv.data.used >= inv.data.capacity ? "text-bad" : ""}`} data-testid="bag-capacity">
            {t("capacity", { used: inv.data.used, cap: inv.data.capacity })}
          </span>
          <select aria-label={t("filterCategory")} className="ml-auto rounded border border-border bg-bg px-1 text-sm" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("allCategories")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {tr(`category.${c}`)}
              </option>
            ))}
          </select>
        </div>
        {!items.length ? <p className="text-sm text-muted">{t("empty")}</p> : null}
        <ul className="grid gap-1 sm:grid-cols-2" data-testid="bag">
          {items.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                data-testid={`bag-item-${i.template_code}`}
                aria-pressed={selected?.id === i.id}
                onClick={() => setSelected(i)}
                className={`w-full rounded border px-2 py-1 text-left text-sm ${selected?.id === i.id ? "border-accent" : "border-border"}`}
              >
                <span className={RARITY_TEXT[i.rarity] ?? ""}>{i.name}</span>
                {i.quantity > 1 ? <span className="ml-1 font-mono text-xs">×{i.quantity}</span> : null}
                <span className="block text-xs text-muted">
                  T{i.tier} · {tr(`rarityName.${i.rarity}`)}
                  {i.slot && i.equippable === false ? ` · ${t("cannotEquip")}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="rounded border border-border p-2 text-sm" data-testid="mailbox">
          <p className={inv.data.mailbox_warn ? "text-legendary" : ""}>
            {t("mailbox", { n: inv.data.mailbox, cap: inv.data.mailbox_capacity })}
            {inv.data.mailbox_warn ? ` — ${t("mailboxWarn")}` : ""}
          </p>
          {inv.data.mailbox ? (
            <button type="button" data-testid="claim-mail" className="underline" onClick={() => claimMail.mutate()} disabled={claimMail.isPending}>
              {t("claimMail")}
            </button>
          ) : null}
          <p className="text-xs text-muted">{t("overflowPolicy")}</p>
          <RepairPanel characterId={characterId} />
        </div>
      </section>

      <aside aria-label={t("details")} className="space-y-2">
        {selected ? (
          <>
            <ItemTooltip item={selected} labels={labels} preview={preview.data} />
            {selected.location === "inventory" && selected.slot ? (
              <button
                type="button"
                data-testid="equip"
                disabled={equip.isPending || preview.data?.equippable === false}
                onClick={() => equip.mutate(selected)}
                className="rounded bg-accent px-3 py-1 text-sm font-semibold text-bg disabled:opacity-50"
              >
                {t("equip")}
              </button>
            ) : null}
            {preview.data && !preview.data.equippable ? (
              <ul className="text-xs text-bad" data-testid="equip-blockers">
                {preview.data.unmet.map((u, i) => (
                  <li key={i}>{unmetText(u)}</li>
                ))}
              </ul>
            ) : null}
            {selected.location === "inventory" ? (
              <button type="button" className="ml-2 text-sm text-bad underline" onClick={() => window.confirm(t("destroyConfirm", { name: selected.name })) && destroy.mutate(selected)}>
                {t("destroy")}
              </button>
            ) : null}
            <EnchantActions characterId={characterId} item={selected} onDone={() => setSelected(null)} />
            <TradeActions characterId={characterId} item={selected} onDone={() => setSelected(null)} />
          </>
        ) : (
          <p className="text-sm text-muted">{t("pick")}</p>
        )}
      </aside>
    </div>
  );
}
