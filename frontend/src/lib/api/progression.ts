import { apiFetch, newIdempotencyKey } from "./client";

export const PRIMARY_STATS = ["STR", "DEX", "INT", "VIT", "WIS", "SPI", "LUK"] as const;
export type PrimaryStat = (typeof PRIMARY_STATS)[number];

export interface BreakdownRow {
  source: string;
  ref: string;
  flat: number;
  percent: number;
}

export interface StatLine {
  code: string;
  raw: number;
  effective: number;
  percent_bonus: number;
  final: number;
  breakdown: BreakdownRow[];
}

export interface ProgressionView {
  character_id: number;
  level: number;
  level_cap: number;
  xp: number;
  xp_to_next: number | null;
  progress_percent: number;
  unspent_stat_points: number;
  mastery_xp: number;
  title_code: string;
  next_title: { code: string; level: number } | null;
  next_breakpoint: number | null;
  breakpoints: number[];
  allocation: Record<PrimaryStat, number>;
  version: number;
  stats: { level: number; primary: Record<string, StatLine>; derived: Record<string, StatLine> };
  labels: Record<string, string>;
}

export interface StatProfile {
  code: string;
  name: string;
  description: string;
}

export const progressionApi = {
  get: (id: number) => apiFetch<ProgressionView>(`/characters/${id}/progression`),
  allocate: (id: number, points: Partial<Record<PrimaryStat, number>>, expected_version: number) =>
    apiFetch<{ allocation: Record<string, number>; unspent_stat_points: number; version: number }>(
      `/characters/${id}/stats/allocate`,
      { method: "POST", body: { points, expected_version }, idempotencyKey: newIdempotencyKey() },
    ),
  profiles: () => apiFetch<StatProfile[]>("/content/stat-profiles"),
  auto: (id: number, profile_code: string, expected_version: number) =>
    apiFetch(`/characters/${id}/stats/auto`, {
      method: "POST",
      body: { profile_code, expected_version },
      idempotencyKey: newIdempotencyKey(),
    }),
  respecQuote: (id: number) =>
    apiFetch<{ points_refunded: number; gold_cost: number }>(`/characters/${id}/stats/respec-quote`),
  respec: (id: number) =>
    apiFetch(`/characters/${id}/stats/respec`, { method: "POST", idempotencyKey: newIdempotencyKey() }),
};
