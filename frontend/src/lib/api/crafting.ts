import type { EffectData } from "@/components/effects/effect-text";
import { apiFetch, newIdempotencyKey } from "./client";

export interface RecipeView {
  code: string;
  name: string;
  profession: string;
  required_level: number;
  recipe_rarity: string;
  unlock: { kind: string; ref?: string };
  known: boolean;
  ingredients: { template_code: string; qty: number; name: string; have: number }[];
  output: { template_code: string; qty: number; name: string };
  tool_kind: string | null;
  tool_ok: boolean;
  workstation: string | null;
  craft_time_s: number;
  xp: number;
  quality_applies: boolean;
  fail_chance_pct: number;
  max_craftable: number;
  craftable: boolean;
}

export interface CraftJobView {
  id: number;
  recipe: string;
  quantity: number;
  started_at: string;
  ends_at: string;
  remaining_s: number;
  claimable: boolean;
}

export interface CraftClaim {
  successes: number;
  failures: number;
  outputs: Record<string, number>;
  output_template: string;
  profession_xp: { xp_gained: number; level_after: number };
  replayed: boolean;
}

export interface ImbueView {
  code: string;
  name: string;
  required_level: number;
  categories: string[];
  slots: string[];
  effects: EffectData[];
  gold_cost: number;
  materials: { template_code: string; qty: number }[];
}

const post = <T,>(path: string, body?: unknown, key: string = newIdempotencyKey()) =>
  apiFetch<T>(path, { method: "POST", body, idempotencyKey: key });

export const craftingApi = {
  recipes: (id: number, profession?: string) =>
    apiFetch<RecipeView[]>(`/characters/${id}/recipes`, { query: profession ? { profession } : {} }),
  learn: (id: number, instance_id: number) => post<{ recipe: string }>(`/characters/${id}/recipes/learn`, { instance_id }),
  jobs: (id: number) => apiFetch<CraftJobView[]>(`/characters/${id}/crafts`),
  start: (id: number, recipe_code: string, quantity: number) =>
    post<{ id: number; ends_at: string }>(`/characters/${id}/crafts`, { recipe_code, quantity }),
  cancel: (id: number, job: number) => post<{ job_id: number }>(`/characters/${id}/crafts/${job}/cancel`),
  claim: (id: number, job: number) => post<CraftClaim>(`/characters/${id}/crafts/${job}/claim`),
  imbues: () => apiFetch<ImbueView[]>("/content/imbues"),
  reroll: (id: number, item: number, affix_index: number) =>
    post<{ cost: { gold: number } }>(`/characters/${id}/items/${item}/reroll`, { affix_index }),
  imbue: (id: number, item: number, imbue_code: string) => post<{ cost: { gold: number } }>(`/characters/${id}/items/${item}/imbue`, { imbue_code }),
  salvage: (id: number, item: number) => post<{ event_id: number }>(`/characters/${id}/items/${item}/salvage`),
};
