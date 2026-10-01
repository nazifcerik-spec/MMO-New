"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/lib/api/errors";
import { partyApi, type PartyRole, type PartyView } from "@/lib/api/party";
import { worldApi } from "@/lib/api/world";

/** Party management, minimal chat and leader-started group AFK (each member keeps an own snapshot). */
export function PartyScreen({ characterId }: { characterId: number }) {
  const t = useTranslations("party");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const key = ["party", characterId];
  const q = useQuery({ queryKey: key, queryFn: () => partyApi.view(characterId), refetchInterval: 15_000 });
  const [role, setRole] = useState<PartyRole | "">("");
  const run = (fn: () => Promise<unknown>, ok?: string) =>
    fn()
      .then(() => {
        if (ok) toast("success", ok);
        qc.invalidateQueries({ queryKey: key });
      })
      .catch((e) => toast("error", errorMessage(e)));
  if (q.isLoading) return <p>{tc("loading")}</p>;
  if (!q.data) return <p role="alert">{tc("error")}</p>;
  const v = q.data;
  const roleSelect = (
    <select aria-label={t("role")} className="rounded border border-border bg-bg px-1 text-sm" value={role} onChange={(e) => setRole(e.target.value as PartyRole | "")}>
      <option value="">{t("defaultRole")}</option>
      {v.role_options.map((r) => (
        <option key={r} value={r}>
          {t(`roles.${r}`)}
        </option>
      ))}
    </select>
  );
  return (
    <div className="space-y-3">
      {v.invites.length ? (
        <section aria-label={t("invites")} className="rounded border border-border bg-panel p-2 text-sm" data-testid="party-invites">
          {v.invites.map((i) => (
            <p key={i.id} className="flex flex-wrap items-center gap-2">
              {t("invitedBy", { name: i.from })} {roleSelect}
              <button type="button" data-testid={`accept-${i.id}`} className="rounded bg-accent px-2 text-xs font-semibold text-bg" onClick={() => run(() => partyApi.accept(characterId, i.id, role || undefined), t("joined"))}>
                {t("accept")}
              </button>
              <button type="button" className="text-xs underline" onClick={() => run(() => partyApi.decline(characterId, i.id))}>
                {t("decline")}
              </button>
            </p>
          ))}
        </section>
      ) : null}
      {v.party ? (
        <PartyPanel characterId={characterId} view={v} run={run} />
      ) : (
        <section className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">{t("noParty", { max: v.max_size })}</span>
          {roleSelect}
          <button type="button" data-testid="create-party" className="rounded bg-accent px-2 py-0.5 text-xs font-semibold text-bg" onClick={() => run(() => partyApi.create(characterId, role || undefined), t("created"))}>
            {t("create")}
          </button>
        </section>
      )}
    </div>
  );
}

function PartyPanel({ characterId, view, run }: { characterId: number; view: PartyView; run: (fn: () => Promise<unknown>, ok?: string) => void }) {
  const t = useTranslations("party");
  const f = useFormatter();
  const p = view.party!;
  const isLeader = p.leader_character_id === characterId;
  const [invitee, setInvitee] = useState("");
  return (
    <div className="grid gap-3 @3xl:grid-cols-2">
      <section aria-label={t("members")} className="space-y-2 rounded border border-border bg-panel p-3">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold">{t("members")} ({p.members.length}/{p.max_size})</h2>
          <button type="button" data-testid="leave-party" className="ml-auto text-xs text-bad underline" onClick={() => window.confirm(t("leaveConfirm")) && run(() => partyApi.leave(characterId))}>
            {t("leave")}
          </button>
        </div>
        <ul className="space-y-1 text-sm" data-testid="party-members">
          {p.members.map((m) => (
            <li key={m.character_id} className="flex flex-wrap items-center gap-2">
              <span aria-label={m.online ? t("online") : t("offline")} className={`inline-block h-2 w-2 rounded-full ${m.online ? "bg-good" : "bg-muted"}`} />
              <span className="font-semibold">{m.name}</span>
              {m.leader ? <span className="text-xs text-legendary">{t("leader")}</span> : null}
              <span className="text-xs text-muted">
                Lv {m.level} · {m.class_code} · {t(`roles.${m.role}`)}
              </span>
              {m.afk ? <span className="text-xs text-accent">{t("afkUntil", { zone: m.afk.zone_code, at: f.dateTime(new Date(m.afk.ends_at), { timeStyle: "short" }) })}</span> : null}
              {isLeader && !m.leader ? (
                <span className="ml-auto flex gap-2 text-xs">
                  <button type="button" className="underline" onClick={() => run(() => partyApi.leader(characterId, m.character_id))}>
                    {t("promote")}
                  </button>
                  <button type="button" className="text-bad underline" onClick={() => run(() => partyApi.kick(characterId, m.character_id))}>
                    {t("kick")}
                  </button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        <p className="text-xs" data-testid="composition">
          {p.composition_bonuses.length ? t("bonuses", { list: p.composition_bonuses.map((b) => t(`bonus.${b}`)).join(", ") }) : t("noBonuses")}
        </p>
        <label className="flex items-center gap-1 text-xs">
          {t("myRole")}
          <select className="rounded border border-border bg-bg px-1" value={p.members.find((m) => m.character_id === characterId)?.role} onChange={(e) => run(() => partyApi.role(characterId, e.target.value as PartyRole))}>
            {view.role_options.map((r) => (
              <option key={r} value={r}>
                {t(`roles.${r}`)}
              </option>
            ))}
          </select>
        </label>
        {isLeader ? (
          <>
            <form
              className="flex gap-1 text-xs"
              onSubmit={(e) => {
                e.preventDefault();
                if (invitee.trim()) run(() => partyApi.invite(characterId, invitee.trim()), t("invited"));
                setInvitee("");
              }}
            >
              <input aria-label={t("inviteName")} placeholder={t("inviteName")} value={invitee} onChange={(e) => setInvitee(e.target.value)} maxLength={32} className="rounded border border-border bg-bg px-1" />
              <button type="submit" data-testid="invite" className="underline">
                {t("invite")}
              </button>
            </form>
            <GroupAfk characterId={characterId} run={run} />
          </>
        ) : null}
      </section>
      <PartyChat characterId={characterId} />
    </div>
  );
}

function GroupAfk({ characterId, run }: { characterId: number; run: (fn: () => Promise<unknown>, ok?: string) => void }) {
  const t = useTranslations("party");
  const zones = useQuery({ queryKey: ["zones", characterId], queryFn: () => worldApi.zones(characterId) });
  const eligible = (zones.data?.items ?? []).filter((z) => z.eligible !== false);
  const [zone, setZone] = useState("");
  const [hours, setHours] = useState(1);
  const code = zone || eligible[0]?.code || "";
  return (
    <div className="space-y-1 border-t border-border pt-2 text-xs" data-testid="group-afk">
      <p className="font-semibold">{t("groupAfk")}</p>
      <div className="flex flex-wrap items-center gap-1">
        <select aria-label={t("zone")} className="rounded border border-border bg-bg px-1" value={code} onChange={(e) => setZone(e.target.value)}>
          {eligible.map((z) => (
            <option key={z.code} value={z.code}>
              {z.name}
            </option>
          ))}
        </select>
        <select aria-label={t("hours")} className="rounded border border-border bg-bg px-1" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          {[1, 2, 3].map((h) => (
            <option key={h} value={h}>
              {t("hoursN", { h })}
            </option>
          ))}
        </select>
        <button type="button" data-testid="start-group-afk" disabled={!code} className="rounded bg-accent px-2 font-semibold text-bg disabled:opacity-50" onClick={() => run(() => partyApi.groupAfk(characterId, code, hours * 3600), t("groupStarted"))}>
          {t("start")}
        </button>
      </div>
      <p className="text-muted">{t("groupHint")}</p>
    </div>
  );
}

function PartyChat({ characterId }: { characterId: number }) {
  const t = useTranslations("party");
  const toast = useToast();
  const errorMessage = useErrorMessage();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["party-chat", characterId], queryFn: () => partyApi.chat(characterId), refetchInterval: 10_000 });
  const [body, setBody] = useState("");
  const send = useMutation({
    mutationFn: (text: string) => partyApi.send(characterId, text),
    onSuccess: () => {
      setBody("");
      qc.invalidateQueries({ queryKey: ["party-chat", characterId] });
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <section aria-label={t("chat")} className="flex flex-col gap-2 rounded border border-border bg-panel p-3">
      <h2 className="font-semibold">{t("chat")}</h2>
      <ol className="max-h-64 space-y-0.5 overflow-y-auto text-sm" aria-live="polite" data-testid="party-chat">
        {(q.data ?? []).map((m) => (
          <li key={m.id} className="break-words">
            <span className="font-semibold">{m.name}:</span> {m.body}
          </li>
        ))}
      </ol>
      <form
        className="flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          if (body.trim()) send.mutate(body);
        }}
      >
        <input aria-label={t("message")} value={body} maxLength={300} onChange={(e) => setBody(e.target.value)} className="min-w-0 flex-1 rounded border border-border bg-bg px-1 text-sm" />
        <button type="submit" data-testid="send-chat" disabled={send.isPending} className="rounded bg-accent px-2 text-xs font-semibold text-bg">
          {t("send")}
        </button>
      </form>
    </section>
  );
}
