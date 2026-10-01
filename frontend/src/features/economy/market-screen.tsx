"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { economyApi, type Listing, type MarketFilters } from "@/lib/api/economy";
import { useErrorMessage } from "@/lib/api/errors";
import { RARITY_TEXT } from "@/features/inventory/item-tooltip";

type Tab = "browse" | "mine" | "vendor";

/** Buyout market + static vendor. Prices are integers validated server-side; the client never decides outcomes. */
export function MarketScreen({ characterId }: { characterId: number }) {
  const t = useTranslations("market");
  const [tab, setTab] = useState<Tab>("browse");
  return (
    <div className="space-y-3">
      <div role="tablist" className="flex gap-2 text-sm">
        {(["browse", "mine", "vendor"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} data-testid={`tab-${k}`} onClick={() => setTab(k)} className={`rounded px-2 py-1 ${tab === k ? "bg-accent text-bg" : "border border-border"}`}>
            {t(`tab.${k}`)}
          </button>
        ))}
      </div>
      {tab === "browse" ? <Browse characterId={characterId} /> : tab === "mine" ? <MyListings characterId={characterId} /> : <Vendor characterId={characterId} />}
    </div>
  );
}

function useRefresh(characterId: number) {
  const qc = useQueryClient();
  return () => {
    for (const k of ["market", "my-listings", "inventory", "progression", "wallet"]) qc.invalidateQueries({ queryKey: [k] });
    qc.invalidateQueries({ queryKey: ["inventory", characterId] });
  };
}

function ListingRow({ l, action }: { l: Listing; action?: React.ReactNode }) {
  const t = useTranslations("market");
  const f = useFormatter();
  return (
    <li className="flex flex-wrap items-center gap-2 rounded border border-border p-2 text-sm" data-testid={`listing-${l.id}`}>
      <span className={`font-semibold ${RARITY_TEXT[l.rarity] ?? ""}`}>{l.name}</span>
      {l.quantity > 1 ? <span className="text-xs">×{l.quantity}</span> : null}
      <span className="text-xs text-muted">T{l.tier}</span>
      <span className="text-xs">{t("price", { unit: l.unit_price, total: l.total_price })}</span>
      <span className="text-xs text-muted">{l.status === "active" ? t("expires", { at: f.dateTime(new Date(l.expires_at), { dateStyle: "short", timeStyle: "short" }) }) : t(`status.${l.status}`)}</span>
      <span className="ml-auto">{action}</span>
    </li>
  );
}

function Browse({ characterId }: { characterId: number }) {
  const t = useTranslations("market");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const refresh = useRefresh(characterId);
  const [filters, setFilters] = useState<MarketFilters>({});
  const q = useQuery({ queryKey: ["market", filters], queryFn: () => economyApi.market(filters) });
  const buy = useMutation({
    mutationFn: (l: Listing) => economyApi.buy(characterId, l.id),
    onSuccess: (r) => {
      toast("success", t("bought", { total: r.total }));
      refresh();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <section className="space-y-2" aria-label={t("tab.browse")}>
      <div className="flex flex-wrap gap-2 text-xs">
        <label>
          {t("tier")}{" "}
          <select className="rounded border border-border bg-bg px-1" value={filters.tier ?? ""} onChange={(e) => setFilters({ ...filters, tier: e.target.value === "" ? undefined : Number(e.target.value), after_id: undefined, after_price: undefined })}>
            <option value="">{t("any")}</option>
            {Array.from({ length: 11 }, (_, i) => (
              <option key={i} value={i}>
                T{i}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("maxPrice")}{" "}
          <input type="number" min={1} className="w-24 rounded border border-border bg-bg px-1" value={filters.max_unit_price ?? ""} onChange={(e) => setFilters({ ...filters, max_unit_price: e.target.value ? Math.max(1, Math.floor(Number(e.target.value))) : undefined })} />
        </label>
        <span className="text-muted">{q.data ? t("taxNote", { tax: q.data.tax_pct, fee: q.data.listing_fee_pct }) : null}</span>
      </div>
      {q.isLoading ? <p>{tc("loading")}</p> : null}
      <ul className="space-y-1">
        {(q.data?.items ?? []).map((l) => (
          <ListingRow
            key={l.id}
            l={l}
            action={
              l.seller_character_id === characterId ? (
                <span className="text-xs text-muted">{t("yours")}</span>
              ) : (
                <button type="button" data-testid={`buy-${l.id}`} disabled={buy.isPending} onClick={() => window.confirm(t("buyConfirm", { name: l.name, total: l.total_price })) && buy.mutate(l)} className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg disabled:opacity-50">
                  {t("buy")}
                </button>
              )
            }
          />
        ))}
        {q.data && !q.data.items.length ? <li className="text-sm text-muted">{t("empty")}</li> : null}
      </ul>
      {q.data?.next_cursor ? (
        <button type="button" className="text-sm underline" onClick={() => setFilters({ ...filters, ...q.data!.next_cursor! })}>
          {t("next")}
        </button>
      ) : null}
    </section>
  );
}

function MyListings({ characterId }: { characterId: number }) {
  const t = useTranslations("market");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const refresh = useRefresh(characterId);
  const q = useQuery({ queryKey: ["my-listings", characterId], queryFn: () => economyApi.myListings(characterId) });
  const cancel = useMutation({ mutationFn: (id: number) => economyApi.cancel(characterId, id), onSuccess: refresh, onError: (e) => toast("error", errorMessage(e)) });
  return (
    <section aria-label={t("tab.mine")}>
      <p className="mb-1 text-xs text-muted">{t("listHint")}</p>
      <ul className="space-y-1">
        {(q.data ?? []).map((l) => (
          <ListingRow
            key={l.id}
            l={l}
            action={
              l.status === "active" ? (
                <button type="button" data-testid={`cancel-${l.id}`} className="text-xs text-bad underline" disabled={cancel.isPending} onClick={() => cancel.mutate(l.id)}>
                  {t("cancel")}
                </button>
              ) : null
            }
          />
        ))}
        {q.data && !q.data.length ? <li className="text-sm text-muted">{t("noListings")}</li> : null}
      </ul>
    </section>
  );
}

function Vendor({ characterId }: { characterId: number }) {
  const t = useTranslations("market");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const refresh = useRefresh(characterId);
  const q = useQuery({ queryKey: ["vendor"], queryFn: () => economyApi.vendor() });
  const [qty, setQty] = useState<Record<string, number>>({});
  const buy = useMutation({
    mutationFn: ({ code, n }: { code: string; n: number }) => economyApi.vendorBuy(characterId, code, n),
    onSuccess: (r) => {
      toast("success", t("vendorBought", { gold: r.price }));
      refresh();
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <ul className="space-y-1" aria-label={t("tab.vendor")}>
      {(q.data?.items ?? []).map((v) => (
        <li key={v.template_code} className="flex flex-wrap items-center gap-2 rounded border border-border p-2 text-sm" data-testid={`vendor-${v.template_code}`}>
          <span className={`font-semibold ${RARITY_TEXT[v.rarity] ?? ""}`}>{v.name}</span>
          <span className="text-xs text-muted">T{v.tier}</span>
          <span className="text-xs">{t("each", { gold: v.price })}</span>
          <input type="number" aria-label={t("quantity")} min={1} max={v.stack_size > 1 ? 999 : 20} value={qty[v.template_code] ?? 1} onChange={(e) => setQty({ ...qty, [v.template_code]: Math.max(1, Math.floor(Number(e.target.value) || 1)) })} className="ml-auto w-16 rounded border border-border bg-bg px-1" />
          <button type="button" data-testid={`vendor-buy-${v.template_code}`} disabled={buy.isPending} onClick={() => buy.mutate({ code: v.template_code, n: qty[v.template_code] ?? 1 })} className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg disabled:opacity-50">
            {t("buy")}
          </button>
        </li>
      ))}
    </ul>
  );
}
