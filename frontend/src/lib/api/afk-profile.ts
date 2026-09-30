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

export interface TacticCondition {
  kind: string;
  op?: string;
  value?: number;
  target_type?: "boss" | "elite" | "normal";
  code?: string;
}

export interface TacticRule {
  use: { ability?: string; tag?: string };
  when: TacticCondition[];
}

export interface TacticsOptions {
  max_rules: number;
  max_conditions: number;
  max_core_actives: number;
  max_ultimates: number;
  decision_encounters: string[];
  condition_kinds: string[];
  ops: string[];
  tags: string[];
  abilities: { code: string; name: string; type: string; tags: string[]; cooldown_s: number }[];
  template: TacticRule[];
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
  tactics: TacticRule[];
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
  default_mode: CombatMode;
  tactics: TacticsOptions;
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
  draft: boolean;
  rules: { index: number; ability: string | null; tag: string | null; name: string | null; uses: number }[];
  fallback_basic_attacks: number;
}

export type ProfileUpdate = Partial<Omit<AfkProfile, "version">> & { expected_version: number };

export const afkApi = {
  get: (id: number) => apiFetch<{ profile: AfkProfile; options: AfkOptions }>(`/characters/${id}/afk-profile`),
  update: (id: number, body: ProfileUpdate) =>
    apiFetch<AfkProfile>(`/characters/${id}/afk-profile`, { method: "PUT", body }),
  preview: (id: number, body: { fights: number; potions?: number; boss: boolean; enemies?: number; tactics?: TacticRule[] }) =>
    apiFetch<CombatPreview>(`/characters/${id}/combat/preview`, { method: "POST", body }),
};

/** Percent formatter for rates in [0, 1]. */
export const pct = (rate: number) => `${Math.round(rate * 100)}%`;

/** Conditions whose value is a percentage / count / seconds; TARGET_TYPE uses target_type; BUFF/DEBUFF use presence. */
export const PRESENCE_KINDS = new Set(["BUFF_PRESENT", "DEBUFF_PRESENT"]);
export const CODE_KINDS = new Set(["BUFF_PRESENT", "DEBUFF_PRESENT", "STACK_COUNT"]);
export const NO_VALUE_KINDS = new Set(["TARGET_TYPE", "COOLDOWN_READY"]);

export function defaultCondition(kind: string): TacticCondition {
  if (kind === "TARGET_TYPE") return { kind, target_type: "boss" };
  if (kind === "COOLDOWN_READY") return { kind };
  if (kind === "EVERY_N_ACTIONS") return { kind, value: 3 };
  if (PRESENCE_KINDS.has(kind)) return { kind, op: "eq", value: 0 };
  if (kind === "ENEMY_COUNT") return { kind, op: "gte", value: 3 };
  return { kind, op: "lt", value: 50 };
}

/** Normalise a rule for the API (drops empty fields). Server re-validates everything. */
export function cleanRule(rule: TacticRule): TacticRule {
  return {
    use: rule.use.ability ? { ability: rule.use.ability } : { tag: rule.use.tag },
    when: rule.when.map((c) => Object.fromEntries(Object.entries(c).filter(([, v]) => v !== undefined && v !== "")) as TacticCondition),
  };
}
