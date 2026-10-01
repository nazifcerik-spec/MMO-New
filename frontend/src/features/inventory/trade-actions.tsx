"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { economyApi } from "@/lib/api/economy";
import { useErrorMessage } from "@/lib/api/errors";
import type { ItemView } from "@/lib/api/inventory";

/** Vendor sell + market listing for a bag item (server validates tradeability, price bounds and escrow). */
export function TradeActions({ characterId, item, onDone }: { characterId: number; item: ItemView; onDone: () => void }) {
  const t = useTranslations("market");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const [price, setPrice] = useState(Math.max(1, item.vendor_value));
  const [hours, setHours] = useState(24);
  const done = (msg: string) => {
    toast("success", msg);
    for (const k of ["inventory", "progression", "my-listings"]) qc.invalidateQueries({ queryKey: [k, characterId] });
    onDone();
  };
  const sell = useMutation({
    mutationFn: () => economyApi.vendorSell(characterId, item.id, item.quantity),
    onSuccess: (r) => done(t("soldToVendor", { gold: r.gold })),
    onError: (e) => toast("error", errorMessage(e)),
  });
  const list = useMutation({
    mutationFn: () => economyApi.list(characterId, item.id, price, hours),
    onSuccess: (r) => done(t("listed", { fee: r.fee })),
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (item.location !== "inventory") return null;
  const busy = sell.isPending || list.isPending;
  return (
    <div className="space-y-1 text-xs" data-testid="trade-actions">
      {item.sellable ? (
        <button type="button" data-testid="vendor-sell" className="underline" disabled={busy} onClick={() => window.confirm(t("sellConfirm", { name: item.name })) && sell.mutate()}>
          {t("sellToVendor")}
        </button>
      ) : null}
      {item.tradeable ? (
        <div className="flex flex-wrap items-center gap-1">
          <input type="number" aria-label={t("unitPrice")} min={1} value={price} onChange={(e) => setPrice(Math.max(1, Math.floor(Number(e.target.value) || 1)))} className="w-24 rounded border border-border bg-bg px-1" />
          <select aria-label={t("duration")} className="rounded border border-border bg-bg px-1" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {[12, 24, 48, 72].map((h) => (
              <option key={h} value={h}>
                {t("hours", { h })}
              </option>
            ))}
          </select>
          <button type="button" data-testid="list-item" className="underline" disabled={busy} onClick={() => list.mutate()}>
            {t("listOnMarket")}
          </button>
        </div>
      ) : (
        <p className="text-muted">{t("notTradeable")}</p>
      )}
    </div>
  );
}

/** Repair quote + repair-all (gold sink). */
export function RepairPanel({ characterId }: { characterId: number }) {
  const t = useTranslations("market");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const quote = useQuery({ queryKey: ["repair", characterId], queryFn: () => economyApi.repairQuote(characterId) });
  const repair = useMutation({
    mutationFn: () => economyApi.repair(characterId),
    onSuccess: (r) => {
      toast("success", t("repaired", { gold: r.cost }));
      for (const k of ["repair", "inventory", "equipment", "progression"]) qc.invalidateQueries({ queryKey: [k, characterId] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  if (!quote.data?.items.length) return null;
  return (
    <p className="text-xs" data-testid="repair-panel">
      {t("repairQuote", { n: quote.data.items.length, gold: quote.data.total })}{" "}
      <button type="button" data-testid="repair-all" className="underline" disabled={repair.isPending} onClick={() => repair.mutate()}>
        {t("repairAll")}
      </button>
    </p>
  );
}
