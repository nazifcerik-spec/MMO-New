import type { CombatPreview } from "./afk-profile";
import { apiFetch } from "./client";

export interface Requirement {
  kind: "min_level" | "zone_cleared" | "class_stage" | "quest";
  value?: number;
  code?: string;
}

export interface ZoneCard {
  code: string;
  name: string;
  tier: number | null;
  tier_name: string | null;
  min_level: number;
  recommended_level: number;
  max_level: number;
  danger_rating: number;
  environment_tags: string[];
  eligible?: boolean;
  unmet?: Requirement[];
}

export interface ZoneDetail extends ZoneCard {
  description: string | null;
  rarity_band: string[];
  boss_chance_pct: number;
  loot_modifiers: Record<string, number>;
  profession_nodes: { profession_code: string; node_code: string; tier: number }[];
  enemies: { code: string; name: string; rank: string; archetype: string; damage_type: string }[];
  bosses: { code: string; name: string; archetype: string; damage_type: string }[];
  drops: { kind: string; tier: number | null; rarity: string | null }[];
  risk_profiles: { code: string; name: string; xp_loot_percent: number; death_risk_percent: number; rare_bonus_percent: number }[];
}

export type ZonePreview = CombatPreview & { zone: string; encounters: Record<string, number> };

export const worldApi = {
  zones: (characterId: number, after?: number) =>
    apiFetch<{ items: ZoneCard[]; next_cursor: number | null }>("/zones", {
      query: { character_id: characterId, limit: 50, ...(after !== undefined ? { after } : {}) },
    }),
  zone: (code: string, characterId: number) =>
    apiFetch<ZoneDetail>(`/zones/${encodeURIComponent(code)}`, { query: { character_id: characterId } }),
  preview: (characterId: number, code: string, boss: boolean) =>
    apiFetch<ZonePreview>(`/characters/${characterId}/zones/${encodeURIComponent(code)}/preview`, {
      method: "POST",
      body: { fights: 10, boss },
    }),
};
