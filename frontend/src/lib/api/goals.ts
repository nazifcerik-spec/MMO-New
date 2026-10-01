import { apiFetch, newIdempotencyKey } from "./client";

export type StatusRarity = "bronze" | "silver" | "gold" | "platinum" | "mythic" | "relic";

export interface Objective {
  kind: "kill" | "boss" | "explore" | "collect" | "profession" | "level" | "action";
  count?: number;
  zone?: string | null;
  template_code?: string | null;
  profession?: string | null;
  level?: number | null;
  action?: string | null;
}

export interface QuestView {
  code: string;
  name: string;
  type: string;
  chain: string | null;
  min_level: number;
  prerequisites: string[];
  objectives: Objective[];
  rewards: { xp?: number; gold?: number; items?: { template_code: string; qty: number }[]; title_code?: string | null };
  repeatable: boolean;
  progress: number[];
  status: "active" | "completed" | "claimed" | "abandoned" | null;
}

export interface QuestLog {
  available: QuestView[];
  active: QuestView[];
  completed: QuestView[];
  locked: QuestView[];
}

export interface AchievementsView {
  achievements: { code: string; name: string; category: string; counter: string; threshold: number; value: number; rarity: StatusRarity; points: number; title_code: string | null; unlocked_at: string | null }[];
  counters: Record<string, number>;
  points: number;
  prestige: { points: number; rarity: StatusRarity; next: { points: number; rarity: StatusRarity } | null };
}

export interface TitlesView {
  selected: string;
  titles: { ref: string; kind: string; name: string; rarity: StatusRarity }[];
}

export interface CollectionsView {
  total: number;
  owned: number;
  groups: Record<string, { template_code: string; name: string; tier: number; rarity: string; owned: boolean }[]>;
}

const c = (id: number) => `/characters/${id}`;

export const goalsApi = {
  quests: (id: number) => apiFetch<QuestLog>(`${c(id)}/quests`),
  accept: (id: number, code: string) => apiFetch<{ status: string }>(`${c(id)}/quests/${code}/accept`, { method: "POST" }),
  abandon: (id: number, code: string) => apiFetch<void>(`${c(id)}/quests/${code}/abandon`, { method: "POST" }),
  claim: (id: number, code: string) => apiFetch<{ gold: number; title: string | null }>(`${c(id)}/quests/${code}/claim`, { method: "POST", idempotencyKey: newIdempotencyKey() }),
  achievements: (id: number) => apiFetch<AchievementsView>(`${c(id)}/achievements`),
  titles: (id: number) => apiFetch<TitlesView>(`${c(id)}/titles`),
  selectTitle: (id: number, ref: string) => apiFetch<{ selected: string }>(`${c(id)}/titles/select`, { method: "POST", body: { ref } }),
  collections: (id: number) => apiFetch<CollectionsView>(`${c(id)}/collections`),
};

export const STATUS_RARITY_TEXT: Record<StatusRarity, string> = {
  bronze: "text-[#b08d57]",
  silver: "text-muted",
  gold: "text-legendary",
  platinum: "text-accent",
  mythic: "text-epic",
  relic: "text-bad font-bold",
};
