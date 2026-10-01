import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CombatLog } from "@/features/combat/combat-log";
import { GameShell } from "@/features/shell/game-shell";

import { renderIntl } from "./render";

vi.mock("next/navigation", () => ({ usePathname: () => "/game/characters/7/inventory", useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));

const summary = {
  character_id: 7, name: "Aria", level: 120, level_cap: 1000, xp: 50, xp_to_next: 100, progress_percent: 50, class_title: "Guardian",
  title: { ref: "level:veteran", kind: "level", name: "Veteran", rarity: "bronze" }, gold: 1234, unspent_stat_points: 3, talent_points: 0,
  afk: { zone_code: "ironroot_forest", ends_at: "2030-01-01T02:00:00Z", claimable: true },
  next_goals: [{ kind: "afk_claim" }, { kind: "stat_points", points: 3 }, { kind: "level_title", level: 200, name: "Seasoned" }],
}; // prettier-ignore
const activity = [
  { type: "afk_claimed", at: "2026-01-01T00:00:00Z", zone_code: "ironroot_forest", xp: 5000, gold: 120, kills: 340, signals: [{ kind: "level_up", levels: 2 }, { kind: "rare_drops", count: 1 }] },
  { type: "achievement", at: "2025-12-31T00:00:00Z", name: "Boss Hunter", rarity: "silver" },
]; // prettier-ignore

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/activity") ? activity : summary), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <GameShell characterId={7}>
        <p>center</p>
      </GameShell>
    </QueryClientProvider>,
  );
}

describe("GameShell", () => {
  it("renders identity, resources, current nav item, goals and localized activity", async () => {
    renderShell();
    const bar = await screen.findByTestId("identity-bar");
    await waitFor(() => expect(bar).toHaveTextContent("Aria"));
    expect(bar).toHaveTextContent("Veteran");
    expect(screen.getByTestId("shell-gold")).toHaveTextContent("1,234 gold");
    expect(screen.getByTestId("nav-inventory")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("goal-afk_claim")).toHaveTextContent("ready to claim");
    const log = await screen.findByTestId("activity-log");
    await waitFor(() => expect(log).toHaveTextContent("AFK in ironroot_forest: 340 kills, +5,000 XP, +120 gold"));
    expect(log).toHaveTextContent("Level up ×2!");
    expect(log).toHaveTextContent("Achievement unlocked: Boss Hunter");
  });

  it("opens the mobile drawer as a dialog and closes it with Escape", async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId("mnav-more"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByTestId("dnav-settings")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the read-only offline banner when the browser is offline", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderShell();
    expect(await screen.findByTestId("offline-banner")).toHaveTextContent("read-only");
  });
});

describe("CombatLog", () => {
  it("summarizes first and localizes structured events on demand", () => {
    renderIntl(
      <CombatLog
        log={{
          actors: { c1: { side: "players", code: "warrior" }, e1: { side: "enemies", code: "meadow_wolf" } },
          labels: { "enemy.meadow_wolf.name": "Meadow Wolf" },
          events: [
            { t: 1, event_type: "HIT", actor_id: "c1", target_id: "e1", ability_code: null, amount: 40 },
            { t: 2, event_type: "CRIT", actor_id: "c1", target_id: "e1", ability_code: "cleave", amount: 120 },
            { t: 3, event_type: "DEATH", actor_id: "c1", target_id: "e1" },
            { t: 3, event_type: "END", outcome: "win" },
          ],
        }}
      />,
    );
    const log = screen.getByTestId("combat-log");
    expect(log).toHaveTextContent("Victory · 1 hits · 1 crits · 0 blocks · 0 dodges · 0 procs · 1 defeated");
    expect(log).toHaveTextContent("CRITICAL! You hit Meadow Wolf with cleave for 120");
    expect(log).toHaveTextContent("You defeat Meadow Wolf");
  });
});
