import { apiFetch, newIdempotencyKey } from "./client";

export interface ClassStage {
  stage: string;
  name: string;
  min_level: number;
  requires_quest: string | null;
  completed_at: string | null;
  unlocked: boolean;
}

export interface ClassCard {
  id: number;
  code: string;
  name: string;
  description: string | null;
  role: string;
  category: "combat" | "support";
  category_name: string;
  stat_weights: { primary: string; secondary: string; utility: string };
  resources: string[];
  weapons: string[];
  armor: string[];
  trait_name: string;
  trait_description: string;
  effects: { effect_type: string; params: Record<string, unknown> }[];
  solo_accord: { conversion_percent: number } | null;
  branches: { code: string; name: string; role: string; specializations: { code: string; name: string; role: string }[] }[];
  labels: Record<string, string>;
}

export interface ClassView {
  character_id: number;
  level: number;
  base_class: ClassCard;
  class_title: string;
  branch_code: string | null;
  specialization_code: string | null;
  stages: ClassStage[];
  can_promote: boolean;
  can_specialize: boolean;
  path_change: { branch_change_gold: number; spec_change_gold: number; free: boolean; cooldown_ready_at: string | null };
}

export const classApi = {
  view: (id: number) => apiFetch<ClassView>(`/characters/${id}/class`),
  promote: (id: number, branch_code: string) =>
    apiFetch<ClassView>(`/characters/${id}/class/promote`, { method: "POST", body: { branch_code } }),
  specialize: (id: number, specialization_code: string) =>
    apiFetch<ClassView>(`/characters/${id}/class/specialize`, { method: "POST", body: { specialization_code } }),
  changePath: (id: number, body: { branch_code?: string; specialization_code?: string }) =>
    apiFetch<ClassView>(`/characters/${id}/class/change-path`, {
      method: "POST",
      body,
      idempotencyKey: newIdempotencyKey(),
    }),
};
