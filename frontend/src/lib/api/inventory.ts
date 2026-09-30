import type { EffectData } from "@/components/effects/effect-text";

import { apiFetch } from "./client";

export interface Unmet {
  kind: "level" | "stat" | "class" | "race" | "weapon_proficiency" | "armor_proficiency" | "slot" | "binding" | "not_equippable";
  stat?: string;
  required?: number;
  have?: number;
  code?: string;
}

export interface ItemView {
  id: number;
  template_code: string;
  template_revision_no: number;
  name: string;
  description: string | null;
  category: string;
  slot: string | null;
  tier: number;
  rarity: string;
  min_level: number;
  quantity: number;
  affixes: { code: string; kind: string; value: number | null; effect: EffectData }[];
  unique_effect: { key: string; effects: EffectData[]; mastery_scaling?: boolean } | null;
  sockets: number;
  durability: number;
  durability_max: number;
  bound: boolean;
  upgrade_level: number;
  location: string;
  equipped_slot: string | null;
  requirements: { stats: Record<string, number> };
  effects: EffectData[];
  bind_policy: string;
  tradeable: boolean;
  sellable: boolean;
  vendor_value: number;
  sources: { kind: string; ref: string | null }[];
  set_code: string | null;
  class_tags: string[];
  weapon_family: string | null;
  armor_family: string | null;
  unmet?: Unmet[];
  equippable?: boolean;
}

export interface InventoryView {
  items: ItemView[];
  labels: Record<string, string>;
  next_after_id: number | null;
  used: number;
  capacity: number;
  mailbox: number;
  mailbox_capacity: number;
  mailbox_warn: boolean;
}

export interface EquipmentView {
  slots: { code: string; accepts: string[]; item: ItemView | null }[];
  labels: Record<string, string>;
  derived: Record<string, number>;
  primary: Record<string, number>;
}

export interface EquipPreview {
  slot: string | null;
  replaces: number | null;
  unmet: Unmet[];
  equippable: boolean;
  deltas: Record<string, number>;
}

export const inventoryApi = {
  inventory: (id: number, location: "inventory" | "mail" = "inventory", after_id?: number) =>
    apiFetch<InventoryView>(`/characters/${id}/inventory`, { query: { location, after_id } }),
  equipment: (id: number) => apiFetch<EquipmentView>(`/characters/${id}/equipment`),
  equip: (id: number, instance_id: number, slot?: string) =>
    apiFetch<EquipmentView & { slot: string; displaced: number[] }>(`/characters/${id}/equipment/equip`, { method: "POST", body: { instance_id, ...(slot ? { slot } : {}) } }),
  unequip: (id: number, slot: string) => apiFetch<EquipmentView>(`/characters/${id}/equipment/unequip`, { method: "POST", body: { slot } }),
  preview: (id: number, instanceId: number) => apiFetch<EquipPreview>(`/characters/${id}/items/${instanceId}/equip-preview`),
  claimMail: (id: number) => apiFetch<{ moved: number; remaining: number }>(`/characters/${id}/mailbox/claim`, { method: "POST" }),
  destroy: (id: number, instanceId: number) => apiFetch<void>(`/characters/${id}/items/${instanceId}`, { method: "DELETE" }),
};
