import { apiFetch, newIdempotencyKey } from "./client";

export interface AfkSessionView {
  id: number;
  status: "running" | "resolved" | "claimed" | "cancelled";
  zone_code: string;
  zone_name: string;
  risk_level: string;
  started_at: string;
  ends_at: string;
  stopped_at: string | null;
  server_now: string;
  remaining_s: number;
  elapsed_s: number;
  claimable: boolean;
  build: Record<string, string | number | null>;
  player_stats: Record<string, number | null>;
  efficiency: { from_s: number; to_s: number; percent: number }[];
  content_version: number;
}

export interface AfkDrop {
  kind: string;
  ref: string | null;
  tier: number | null;
  category: string | null;
  rarity: string | null;
  qty: number;
}

export interface AfkSignal {
  kind: "level_up" | "xp_progress" | "boss_kills" | "rare_drops" | "gold" | "pity_progress";
  levels?: number;
  level?: number;
  percent?: number;
  count?: number;
  amount?: number;
}

export interface AfkClaim {
  session_id: number;
  zone_code: string;
  risk_level: string;
  result: {
    elapsed_s: number;
    fights: number;
    wins: number;
    deaths: number;
    kills: number;
    boss_kills: number;
    xp: number;
    gold: number;
    death_gold_cost: number;
    durability_loss_pct: number;
    potions_used: number;
    avg_efficiency_pct: number;
    drops: AfkDrop[];
    timeline: { xp: number; kills: number; deaths: number }[];
  };
  xp: { level_before: number; level_after: number; levels_gained: number };
  gold: number;
  loot_pending: AfkDrop[];
  signals: AfkSignal[];
  replayed: boolean;
}

export const afkApi = {
  current: (id: number) => apiFetch<{ session: AfkSessionView | null; server_now: string }>(`/characters/${id}/afk`),
  start: (id: number, body: { zone_code: string; duration_s: number; risk_level?: string }) =>
    apiFetch<AfkSessionView>(`/characters/${id}/afk/start`, { method: "POST", body, idempotencyKey: newIdempotencyKey() }),
  stop: (id: number) => apiFetch<AfkSessionView>(`/characters/${id}/afk/stop`, { method: "POST" }),
  claim: (id: number, key: string) => apiFetch<AfkClaim>(`/characters/${id}/afk/claim`, { method: "POST", idempotencyKey: key }),
};

/** Countdown helper using the server clock offset (never trusts the client clock for authority). */
export function remainingSeconds(view: AfkSessionView, clientNowMs: number, fetchedAtMs: number): number {
  const elapsedSinceFetch = Math.max(0, (clientNowMs - fetchedAtMs) / 1000);
  return Math.max(0, Math.round(view.remaining_s - elapsedSinceFetch));
}

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}
