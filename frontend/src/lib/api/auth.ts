import { apiFetch } from "./client";

export interface Me {
  id: number;
  email: string;
  roles: string[];
  permissions: string[];
  is_staff: boolean;
  locale: string;
}

export interface Character {
  id: number;
  name: string;
  race_id: number;
  base_class_id: number;
  level: number;
  xp: number;
  unspent_stat_points: number;
  created_at: string;
  last_level_up_at: string | null;
}

export interface OptionCard {
  id: number;
  code: string;
  name: string;
  description?: string;
  [key: string]: unknown;
}

export interface CharacterOptions {
  races: OptionCard[];
  base_classes: OptionCard[];
}

export const authApi = {
  me: () => apiFetch<Me>("/auth/me"),
  login: (email: string, password: string) => apiFetch<Me>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, locale: string) =>
    apiFetch<Me>("/auth/register", { method: "POST", body: { email, password, locale } }),
  logout: () => apiFetch<void>("/auth/logout", { method: "POST" }),
};

export const characterApi = {
  list: () => apiFetch<Character[]>("/characters"),
  options: () => apiFetch<CharacterOptions>("/content/character-options"),
  nameCheck: (name: string) =>
    apiFetch<{ name: string; available: boolean; valid: boolean; error_code: string | null }>(
      "/characters/name-check",
      { query: { name } },
    ),
  create: (body: { name: string; race_id: number; base_class_id: number }) =>
    apiFetch<Character>("/characters", { method: "POST", body }),
  remove: (id: number) => apiFetch<void>(`/characters/${id}`, { method: "DELETE" }),
};
