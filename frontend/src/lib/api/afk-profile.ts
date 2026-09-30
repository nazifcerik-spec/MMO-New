import { apiFetch } from "./client";

export type CombatMode = "PASSIVE_ONLY" | "ACTIVE_TACTICS" | "HYBRID";

export interface LootFilter {
  min_rarity: string;
  categories: string[];
  min_tier: number;
  class_tags: string[];
  keep_materials: boolean;
  auto_salvage: boolean;
}

export interface AfkProfile {
  preset_code: string | null;
  mode: CombatMode;
  stance: string;
  target_priority: string;
  potion_threshold_pct: number;
  risk_level: string;
  passive_profile_code: string | null;
  loot_filter: LootFilter;
  tactics: unknown[];
  version: number;
}

export interface AfkOptions {
  stances: { code: string; name: string; description: string }[];
  target_priorities: { code: string; name: string }[];
  risk_levels: { code: string; name: string; enemy_power_percent: number }[];
  presets: { code: string; name: string; stance: string; risk_level: string; potion_threshold_pct: number }[];
  passive_profiles: { code: string; name: string; description: string | null }[];
  rarities: string[];
  modes: CombatMode[];
}

export interface CombatPreview {
  fights: number;
  win_rate: number;
  death_rate: number;
  avg_duration_s: number;
  avg_damage_taken: number;
  avg_damage_dealt: number;
  avg_potions_used: number;
  dps: number;
  mode: CombatMode;
  boss: boolean;
  rules: { index: number; ability: string | null; tag: string | null; name: string | null; uses: number }[];
  fallback_basic_attacks: number;
}

export type ProfileUpdate = Partial<Omit<AfkProfile, "version" | "tactics">> & { expected_version: number };

export const afkApi = {
  get: (id: number) => apiFetch<{ profile: AfkProfile; options: AfkOptions }>(`/characters/${id}/afk-profile`),
  update: (id: number, body: ProfileUpdate) =>
    apiFetch<AfkProfile>(`/characters/${id}/afk-profile`, { method: "PUT", body }),
  preview: (id: number, body: { fights: number; potions?: number; boss: boolean }) =>
    apiFetch<CombatPreview>(`/characters/${id}/combat/preview`, { method: "POST", body }),
};

/** Percent formatter for rates in [0, 1]. */
export const pct = (rate: number) => `${Math.round(rate * 100)}%`;
