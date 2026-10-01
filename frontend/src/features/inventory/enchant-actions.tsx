"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { craftingApi } from "@/lib/api/crafting";
import { useErrorMessage } from "@/lib/api/errors";
import type { ItemView } from "@/lib/api/inventory";

/** Enchanting (safe reroll / imbue), salvage and recipe learning for a bag item. All outcomes are server-rolled. */
export function EnchantActions({ characterId, item, onDone }: { characterId: number; item: ItemView; onDone: () => void }) {
  const t = useTranslations("crafting");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const imbues = useQuery({ queryKey: ["imbues"], queryFn: craftingApi.imbues, staleTime: 300_000 });
  const [affix, setAffix] = useState(0);
  const [imbue, setImbue] = useState("");
  const refresh = () => {
    for (const k of ["inventory", "professions", "recipes", "progression"]) qc.invalidateQueries({ queryKey: [k, characterId] });
  };
  const onError = (e: unknown) => toast("error", errorMessage(e));
  const reroll = useMutation({
    mutationFn: () => craftingApi.reroll(characterId, item.id, affix),
    onSuccess: (r) => {
      toast("success", t("rerolled", { gold: r.cost.gold }));
      refresh();
      onDone();
    },
    onError,
  });
  const doImbue = useMutation({
    mutationFn: (code: string) => craftingApi.imbue(characterId, item.id, code),
    onSuccess: () => {
      toast("success", t("imbued"));
      refresh();
      onDone();
    },
    onError,
  });
  const salvage = useMutation({
    mutationFn: () => craftingApi.salvage(characterId, item.id),
    onSuccess: () => {
      toast("success", t("salvaged"));
      refresh();
      onDone();
    },
    onError,
  });
  const learn = useMutation({
    mutationFn: () => craftingApi.learn(characterId, item.id),
    onSuccess: () => {
      toast("success", t("learned"));
      refresh();
      onDone();
    },
    onError,
  });
  if (item.location !== "inventory") return null;
  const rerollable = item.affixes.map((a, i) => ({ a, i })).filter(({ a }) => a.kind !== "fixed");
  const fitting = (imbues.data ?? []).filter((m) => m.categories.includes(item.category) && (!m.slots.length || (item.slot && m.slots.includes(item.slot))));
  const busy = reroll.isPending || doImbue.isPending || salvage.isPending || learn.isPending;
  return (
    <div className="space-y-1 text-xs" data-testid="enchant-actions">
      {item.category === "recipe" ? (
        <button type="button" data-testid="learn-recipe" className="rounded bg-accent px-2 py-0.5 font-semibold text-bg" disabled={busy} onClick={() => learn.mutate()}>
          {t("learn")}
        </button>
      ) : null}
      {rerollable.length ? (
        <div className="flex items-center gap-1">
          <select aria-label={t("affix")} className="rounded border border-border bg-bg px-1" value={affix} onChange={(e) => setAffix(Number(e.target.value))}>
            {rerollable.map(({ a, i }) => (
              <option key={i} value={i}>
                {a.code} ({a.value})
              </option>
            ))}
          </select>
          <button type="button" data-testid="reroll" className="underline" disabled={busy} onClick={() => window.confirm(t("rerollConfirm")) && reroll.mutate()}>
            {t("reroll")}
          </button>
        </div>
      ) : null}
      {fitting.length ? (
        <div className="flex items-center gap-1">
          <select aria-label={t("imbue")} className="rounded border border-border bg-bg px-1" value={imbue} onChange={(e) => setImbue(e.target.value)}>
            <option value="">{t("chooseImbue")}</option>
            {fitting.map((m) => (
              <option key={m.code} value={m.code}>
                {m.name} ({m.gold_cost}g)
              </option>
            ))}
          </select>
          <button type="button" className="underline" disabled={busy || !imbue} onClick={() => window.confirm(t("imbueConfirm")) && doImbue.mutate(imbue)}>
            {t("imbue")}
          </button>
        </div>
      ) : null}
      {item.slot || item.category === "weapon" || item.category === "armor" ? (
        <button type="button" data-testid="salvage" className="text-bad underline" disabled={busy} onClick={() => window.confirm(t("salvageConfirm", { name: item.name })) && salvage.mutate()}>
          {t("salvage")}
        </button>
      ) : null}
    </div>
  );
}
