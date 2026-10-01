"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { STATUS_RARITY_TEXT } from "@/lib/api/goals";
import { overviewApi } from "@/lib/api/overview";
import { useOnline } from "@/lib/hooks/use-online";

import { ActivityLog } from "./activity-log";
import { NextGoals } from "./next-goals";

const NAV = [
  { key: "character", path: "" },
  { key: "adventure", path: "/zones" },
  { key: "afk", path: "/afk" },
  { key: "inventory", path: "/inventory" },
  { key: "equipment", path: "/inventory#equipment" },
  { key: "skills", path: "/talents" },
  { key: "class", path: "/class" },
  { key: "professions", path: "/professions" },
  { key: "crafting", path: "/professions#crafting" },
  { key: "market", path: "/market" },
  { key: "party", path: "/party" },
  { key: "collections", path: "/goals" },
  { key: "settings", path: "/settings" },
] as const;
const MOBILE_PRIMARY = ["character", "adventure", "afk", "inventory"] as const;

/** Main game shell: identity bar, desktop side nav, context center, desktop activity column, mobile bottom nav. */
export function GameShell({ characterId, children }: { characterId: number; children: React.ReactNode }) {
  const t = useTranslations("shell");
  const f = useFormatter();
  const online = useOnline();
  const pathname = usePathname();
  const base = `/game/characters/${characterId}`;
  const s = useQuery({ queryKey: ["summary", characterId], queryFn: () => overviewApi.summary(characterId), refetchInterval: 30_000 });
  const [drawer, setDrawer] = useState(false);
  const href = (p: string) => `${base}${p}`;
  const isCurrent = (p: string) => (p === "" ? pathname === base : !p.includes("#") && pathname.startsWith(`${base}${p}`));
  const sum = s.data;

  const navLinks = (testPrefix: string, onClick?: () => void) =>
    NAV.map((n) => (
      <li key={n.key}>
        <Link href={href(n.path)} onClick={onClick} aria-current={isCurrent(n.path) ? "page" : undefined} data-testid={`${testPrefix}-${n.key}`} className={`block rounded px-2 py-1 hover:bg-bg ${isCurrent(n.path) ? "bg-bg font-semibold text-accent" : ""}`}>
          {t(`nav.${n.key}`)}
        </Link>
      </li>
    ));

  return (
    <div className="pb-16 lg:pb-0" data-testid="game-shell">
      {!online ? (
        <p role="status" className="mb-2 rounded border border-legendary bg-panel p-2 text-sm text-legendary" data-testid="offline-banner">
          {t("offline")}
        </p>
      ) : null}
      <header className="mb-3 rounded border border-border bg-panel p-2" aria-label={t("identity")} data-testid="identity-bar">
        {sum ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="font-mono font-bold">{sum.name}</span>
            {sum.title ? <span className={`text-xs ${STATUS_RARITY_TEXT[sum.title.rarity]}`}>{sum.title.name}</span> : null}
            <span className="text-xs text-muted">{sum.class_title}</span>
            <span className="text-xs">{t("level", { level: sum.level })}</span>
            <span className="flex min-w-32 flex-1 items-center gap-2">
              <span className="h-2 flex-1 rounded bg-border" role="progressbar" aria-label={t("xp")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(sum.progress_percent)}>
                <span className="block h-2 rounded bg-accent" style={{ width: `${Math.min(100, sum.progress_percent)}%` }} />
              </span>
              <span className="text-xs text-muted">{sum.progress_percent}%</span>
            </span>
            <span className="text-xs text-legendary" data-testid="shell-gold">
              {t("gold", { gold: f.number(sum.gold) })}
            </span>
            {sum.unspent_stat_points ? <span className="rounded bg-accent px-1 text-xs text-bg">{t("statPoints", { n: sum.unspent_stat_points })}</span> : null}
            {sum.afk ? (
              <Link href={href("")} className={`text-xs underline ${sum.afk.claimable ? "font-semibold text-good" : "text-accent"}`} data-testid="shell-afk">
                {sum.afk.claimable ? t("afkReady") : t("afkRunning", { at: f.dateTime(new Date(sum.afk.ends_at), { timeStyle: "short" }) })}
              </Link>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted">…</p>
        )}
      </header>
      <div className="grid gap-4 lg:grid-cols-[11rem_minmax(0,1fr)_17rem]">
        <nav aria-label={t("gameNav")} className="hidden lg:block">
          <ul className="space-y-0.5 text-sm">{navLinks("nav")}</ul>
        </nav>
        <div className="@container min-w-0">{children}</div>
        <aside aria-label={t("sidebar")} className="hidden space-y-3 lg:block">
          {sum ? <NextGoals characterId={characterId} goals={sum.next_goals} /> : null}
          <ActivityLog characterId={characterId} />
        </aside>
      </div>
      <nav aria-label={t("mobileNav")} className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-panel lg:hidden">
        <ul className="grid grid-cols-5 text-center text-xs">
          {MOBILE_PRIMARY.map((k) => {
            const n = NAV.find((x) => x.key === k)!;
            return (
              <li key={k}>
                <Link href={href(n.path)} aria-current={isCurrent(n.path) ? "page" : undefined} data-testid={`mnav-${k}`} className={`block px-1 py-3 ${isCurrent(n.path) ? "font-semibold text-accent" : ""}`}>
                  {t(`nav.${k}`)}
                </Link>
              </li>
            );
          })}
          <li>
            <button type="button" className="w-full px-1 py-3" aria-expanded={drawer} aria-controls="game-drawer" data-testid="mnav-more" onClick={() => setDrawer(true)}>
              {t("more")}
            </button>
          </li>
        </ul>
      </nav>
      {drawer ? <Drawer onClose={() => setDrawer(false)} title={t("more")}>
        <ul className="space-y-0.5 text-sm">{navLinks("dnav", () => setDrawer(false))}</ul>
        {sum ? <NextGoals characterId={characterId} goals={sum.next_goals} compact /> : null}
        <ActivityLog characterId={characterId} />
      </Drawer> : null}
    </div>
  );
}

function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const t = useTranslations("shell");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-30 lg:hidden">
      <button type="button" aria-label={t("close")} className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div id="game-drawer" ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className="absolute inset-x-0 bottom-0 max-h-[85dvh] space-y-3 overflow-y-auto rounded-t border-t border-border bg-bg p-3 outline-none" data-testid="game-drawer">
        <div className="flex items-center">
          <h2 className="font-semibold">{title}</h2>
          <button type="button" className="ml-auto text-sm underline" onClick={onClose}>
            {t("close")}
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
