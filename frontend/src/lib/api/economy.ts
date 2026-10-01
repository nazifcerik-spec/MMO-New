import { apiFetch, newIdempotencyKey } from "./client";

export interface VendorItem {
  template_code: string;
  name: string;
  category: string;
  tier: number;
  rarity: string;
  min_level: number;
  stack_size: number;
  price: number;
}

export interface Listing {
  id: number;
  template_code: string;
  name: string;
  category: string;
  tier: number;
  rarity: string;
  quantity: number;
  unit_price: number;
  total_price: number;
  status: "active" | "sold" | "cancelled" | "expired";
  expires_at: string;
  seller_character_id: number;
  instance_id: number;
}

export interface MarketPage {
  items: Listing[];
  next_cursor: { after_price: number; after_id: number } | null;
  tax_pct: number;
  listing_fee_pct: number;
  durations_h: number[];
}

export interface RepairQuote {
  items: { instance_id: number; template_code: string; missing: number; cost: number }[];
  total: number;
}

export interface EconomySummary {
  gold: { sources: number; sinks: number; transfers: number; net_created: number; by_reason: { reason: string; kind: string; entries: number; gold_in: number; gold_out: number }[] };
  items: Record<string, number>;
  market: { sales: number; volume: number; tax: number; active_listings: number };
}

export type MarketFilters = { template_code?: string; category?: string; tier?: number; rarity?: string; max_unit_price?: number; after_price?: number; after_id?: number };

const post = <T,>(path: string, body?: unknown) => apiFetch<T>(path, { method: "POST", body, idempotencyKey: newIdempotencyKey() });

export const economyApi = {
  vendor: (after?: string) => apiFetch<{ items: VendorItem[]; next_cursor: string | null }>("/vendor", { query: { after } }),
  vendorBuy: (id: number, template_code: string, quantity: number) => post<{ price: number }>(`/characters/${id}/vendor/buy`, { template_code, quantity }),
  vendorSell: (id: number, instance_id: number, quantity: number) => post<{ gold: number }>(`/characters/${id}/vendor/sell`, { instance_id, quantity }),
  repairQuote: (id: number) => apiFetch<RepairQuote>(`/characters/${id}/repair`),
  repair: (id: number, instance_id?: number) => post<{ cost: number; repaired: number[] }>(`/characters/${id}/repair`, { instance_id: instance_id ?? null }),
  market: (f: MarketFilters) => apiFetch<MarketPage>("/market", { query: f }),
  myListings: (id: number) => apiFetch<Listing[]>(`/characters/${id}/market/listings`),
  list: (id: number, instance_id: number, unit_price: number, duration_h: number) =>
    post<Listing & { fee: number }>(`/characters/${id}/market/listings`, { instance_id, unit_price, duration_h }),
  cancel: (id: number, listing: number) => apiFetch<{ status: string }>(`/characters/${id}/market/listings/${listing}/cancel`, { method: "POST" }),
  buy: (id: number, listing: number) => post<{ total: number; tax: number; placed: string }>(`/characters/${id}/market/listings/${listing}/buy`),
  summary: (days: number) => apiFetch<EconomySummary>("/admin/economy/summary", { query: { days } }),
};
