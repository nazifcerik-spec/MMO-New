import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AfkSessionPanel } from "@/features/afk/afk-session-panel";
import { formatDuration, remainingSeconds, type AfkSessionView } from "@/lib/api/afk";

import { renderIntl } from "./render";

const SESSION: AfkSessionView = {
  id: 9,
  status: "running",
  zone_code: "meadows",
  zone_name: "Meadows",
  risk_level: "balanced",
  started_at: "2026-01-01T10:00:00Z",
  ends_at: "2026-01-01T13:00:00Z",
  stopped_at: null,
  server_now: "2026-01-01T13:00:01Z",
  remaining_s: 0,
  elapsed_s: 10800,
  claimable: true,
  build: { level: 30, class: "paladin", branch: null, specialization: null, stance: "guarded" },
  player_stats: { max_hp: 800 },
  efficiency: [{ from_s: 0, to_s: 10800, percent: 100 }],
  content_version: 3,
};

const CLAIM = {
  session_id: 9,
  zone_code: "meadows",
  risk_level: "balanced",
  result: {
    elapsed_s: 10800, fights: 180, wins: 178, deaths: 2, kills: 520, boss_kills: 1, xp: 12345, gold: 900,
    death_gold_cost: 10, durability_loss_pct: 10, potions_used: 0, avg_efficiency_pct: 100,
    drops: [{ kind: "item_pool", ref: null, tier: 0, category: null, rarity: "common", qty: 3 }], timeline: [],
  },
  xp: { level_before: 30, level_after: 31, levels_gained: 1 },
  gold: 900,
  loot_pending: [{ kind: "item_pool", ref: null, tier: 0, category: null, rarity: "common", qty: 3 }],
  signals: [{ kind: "level_up", levels: 1, level: 31 }, { kind: "pity_progress", percent: 12 }],
  replayed: false,
}; // prettier-ignore

function mockFetch(session: AfkSessionView | null) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/afk/claim")
        ? CLAIM
        : url.includes("/zones")
          ? { items: [{ code: "meadows", name: "Meadows", tier_name: "Tier 0", eligible: true }], next_cursor: null }
          : url.includes("/afk/start")
            ? SESSION
            : { session, server_now: SESSION.server_now };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <AfkSessionPanel characterId={4} />
    </QueryClientProvider>,
  );
}

describe("AFK session helpers", () => {
  it("formats durations and counts down from the server remaining time", () => {
    expect(formatDuration(10800)).toBe("3:00:00");
    expect(formatDuration(65)).toBe("0:01:05");
    expect(remainingSeconds({ ...SESSION, remaining_s: 100 }, 5000, 1000)).toBe(96);
    expect(remainingSeconds({ ...SESSION, remaining_s: 3 }, 60_000, 0)).toBe(0);
  });
});

describe("AfkSessionPanel", () => {
  it("starts a session with an idempotency key and capped duration", async () => {
    const calls = mockFetch(null);
    renderPanel();
    await screen.findByRole("option", { name: /Meadows/ });
    fireEvent.click(screen.getByTestId("afk-start"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/afk/start"))).toBe(true));
    const post = calls.find((c) => c.url.includes("/afk/start"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ zone_code: "meadows", duration_s: 10800 });
    expect(new Headers(post.init?.headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("claims and shows localized progress signals", async () => {
    mockFetch(SESSION);
    renderPanel();
    expect(await screen.findByTestId("afk-countdown")).toHaveTextContent("Finished!");
    expect(screen.getByTestId("afk-snapshot")).toHaveTextContent("Lv 30 paladin");
    fireEvent.click(screen.getByTestId("afk-claim"));
    expect(await screen.findByTestId("signal-level_up")).toHaveTextContent("Level up! +1 → Lv 31");
    expect(screen.getByTestId("summary-xp")).toHaveTextContent("12,345");
    expect(screen.getByText("3× T0 Common item")).toBeInTheDocument();
  });
});
