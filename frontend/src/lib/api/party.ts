import { apiFetch, newIdempotencyKey } from "./client";

export type PartyRole = "tank" | "healer" | "support" | "dps";

export interface PartyMemberView {
  character_id: number;
  name: string;
  level: number;
  class_code: string | null;
  role: PartyRole;
  online: boolean;
  afk: { zone_code: string; ends_at: string; group: boolean } | null;
  leader: boolean;
}

export interface PartyView {
  invites: { id: number; party_id: number; from: string; expires_at: string }[];
  role_options: PartyRole[];
  max_size: number;
  party: null | {
    id: number;
    leader_character_id: number;
    max_size: number;
    pending_invites: number;
    members: PartyMemberView[];
    composition_bonuses: string[];
  };
}

export interface ChatMessage {
  id: number;
  character_id: number;
  name: string;
  body: string;
  at: string;
}

const base = (id: number) => `/characters/${id}/party`;

export const partyApi = {
  view: (id: number) => apiFetch<PartyView>(base(id)),
  create: (id: number, role?: PartyRole) => apiFetch<{ party_id: number }>(base(id), { method: "POST", body: { role: role ?? null } }),
  invite: (id: number, character_name: string) => apiFetch<{ invite_id: number }>(`${base(id)}/invites`, { method: "POST", body: { character_name } }),
  accept: (id: number, invite: number, role?: PartyRole) => apiFetch<{ party_id: number }>(`${base(id)}/invites/${invite}/accept`, { method: "POST", body: { role: role ?? null } }),
  decline: (id: number, invite: number) => apiFetch<void>(`${base(id)}/invites/${invite}/decline`, { method: "POST" }),
  leave: (id: number) => apiFetch<void>(`${base(id)}/leave`, { method: "POST" }),
  kick: (id: number, character_id: number) => apiFetch<void>(`${base(id)}/kick`, { method: "POST", body: { character_id } }),
  leader: (id: number, character_id: number) => apiFetch<void>(`${base(id)}/leader`, { method: "POST", body: { character_id } }),
  role: (id: number, role: PartyRole) => apiFetch<{ role: PartyRole }>(`${base(id)}/role`, { method: "POST", body: { role } }),
  chat: (id: number, after_id?: number) => apiFetch<ChatMessage[]>(`${base(id)}/chat`, { query: { after_id } }),
  send: (id: number, body: string) => apiFetch<{ id: number }>(`${base(id)}/chat`, { method: "POST", body: { body }, idempotencyKey: newIdempotencyKey() }),
  groupAfk: (id: number, zone_code: string, duration_s: number) =>
    apiFetch<{ group_id: string; sessions: Record<string, number> }>(`${base(id)}/afk`, { method: "POST", body: { zone_code, duration_s }, idempotencyKey: newIdempotencyKey() }),
};
