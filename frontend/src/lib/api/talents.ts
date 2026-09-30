import type { EffectData } from "@/components/effects/effect-text";

import { apiFetch, newIdempotencyKey } from "./client";

export interface TalentNodeView {
  code: string;
  tier: number;
  slot: string;
  max_rank: number;
  rank: number;
  required_points_in_tree: number;
  required_level: number;
  requires: string[];
  is_capstone: boolean;
  name: string;
  description: string | null;
  effects: EffectData[];
}

export interface TalentTreeView {
  code: string;
  name: string;
  focus: string;
  spent: number;
  nodes: TalentNodeView[];
}

export interface TalentsView {
  character_id: number;
  level: number;
  points_available: number;
  points_spent: number;
  points_remaining: number;
  total_max: number;
  per_tree_max: number;
  capstone_level: number;
  version: number;
  reset_quote: { gold: number; material_code: string | null; material_qty: number };
  trees: TalentTreeView[];
  labels: Record<string, string>;
}

export interface AbilityView {
  code: string;
  type: string;
  name: string;
  description: string | null;
  unlock_level: number;
  unlocked: boolean;
  target: string;
  tags: string[];
  cost: { resource: string; amount: number } | null;
  cooldown_s: number;
  effects: EffectData[];
  trigger: string | null;
}

export interface AbilitiesView {
  abilities: AbilityView[];
  awakening: { code: string; name: string; description: string | null; required_level: number; active: boolean; effects: EffectData[] } | null;
  labels: Record<string, string>;
}

export const talentApi = {
  view: (id: number) => apiFetch<TalentsView>(`/characters/${id}/talents`),
  allocate: (id: number, allocations: Record<string, number>, expected_version: number) =>
    apiFetch<TalentsView>(`/characters/${id}/talents`, { method: "POST", body: { allocations, expected_version } }),
  reset: (id: number) =>
    apiFetch(`/characters/${id}/talents/reset`, { method: "POST", idempotencyKey: newIdempotencyKey() }),
  abilities: (id: number) => apiFetch<AbilitiesView>(`/characters/${id}/abilities`),
};

/** Client-side mirror of the server rule for UI hints only (server re-validates). */
export function nodeLockReason(
  node: TalentNodeView,
  tree: TalentTreeView,
  pending: Record<string, number>,
  level: number,
): "points" | "level" | "prereq" | null {
  const rankOf = (code: string) => pending[code] ?? tree.nodes.find((n) => n.code === code)?.rank ?? 0;
  const lower = tree.nodes.filter((n) => n.tier < node.tier).reduce((s, n) => s + rankOf(n.code), 0);
  if (lower < node.required_points_in_tree) return "points";
  if (level < node.required_level) return "level";
  if (node.requires.some((r) => rankOf(r) < 1)) return "prereq";
  return null;
}
