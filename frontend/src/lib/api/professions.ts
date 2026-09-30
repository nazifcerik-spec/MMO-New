import { apiFetch, newIdempotencyKey } from "./client";

export interface ProfessionCard {
  code: string;
  name: string;
  type: "gathering" | "crafting" | "service";
  tool_kind: string;
  stats: string[];
  title: string;
  specializations: { code: string; name: string }[];
  level: number;
  xp: number;
  xp_to_next: number | null;
  rank: string;
  rank_name: string;
  licensed: boolean;
  specialization_code: string | null;
  level_cap_now: number;
  stat_bonuses: { speed: number; quality: number };
  modifiers: Record<"yield" | "speed" | "quality" | "rare_find" | "xp", number>;
  swap_cost_gold: number;
  title_earned: boolean;
}

export interface ProfessionsView {
  professions: ProfessionCard[];
  licenses: { active: number; max: number; free_remaining: number; cooldown_until: string | null };
  specialization_level: number;
  level_cap: number;
  unlicensed_level_cap: number;
}

export const professionApi = {
  view: (id: number) => apiFetch<ProfessionsView>(`/characters/${id}/professions`),
  license: (id: number, code: string, active: boolean) =>
    apiFetch<{ cost_gold: number }>(`/characters/${id}/professions/${code}/license`, { method: "POST", body: { active }, idempotencyKey: newIdempotencyKey() }),
  specialize: (id: number, code: string, specialization_code: string) =>
    apiFetch<{ cost_gold: number }>(`/characters/${id}/professions/${code}/specialize`, {
      method: "POST",
      body: { specialization_code },
      idempotencyKey: newIdempotencyKey(),
    }),
};
