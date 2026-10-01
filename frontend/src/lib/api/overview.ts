import { apiFetch } from "./client";
import type { StatusRarity } from "./goals";

export type NextGoal =
  | { kind: "afk_claim" }
  | { kind: "stat_points" | "talent_points"; points: number }
  | { kind: "class_stage_ready"; stage: string; name: string }
  | { kind: "class_stage"; stage: string; name: string; level: number }
  | { kind: "level_title"; level: number; name: string }
  | { kind: "item_tier"; level: number; tier: number }
  | { kind: "zone_unlock"; level: number; name: string }
  | { kind: "profession_rank"; profession: string; level: number; rank: string };

export interface Summary {
  character_id: number;
  name: string;
  level: number;
  level_cap: number;
  xp: number;
  xp_to_next: number | null;
  progress_percent: number;
  class_title: string;
  title: { ref: string; kind: string; name: string; rarity: StatusRarity } | null;
  gold: number;
  unspent_stat_points: number;
  talent_points: number;
  afk: { zone_code: string; ends_at: string; claimable: boolean } | null;
  next_goals: NextGoal[];
}

export type ActivityItem = { type: string; at: string } & Record<string, unknown>;

export const overviewApi = {
  summary: (id: number) => apiFetch<Summary>(`/characters/${id}/summary`),
  activity: (id: number) => apiFetch<ActivityItem[]>(`/characters/${id}/activity`),
};
