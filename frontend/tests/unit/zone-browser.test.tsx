import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ZoneBrowser } from "@/features/world/zone-browser";

import { renderIntl } from "./render";

const card = (code: string, name: string, eligible: boolean) => ({
  code,
  name,
  tier: 0,
  tier_name: "Tier 0",
  min_level: eligible ? 1 : 100,
  recommended_level: 20,
  max_level: 199,
  danger_rating: 2,
  environment_tags: [],
  eligible,
  unmet: eligible ? [] : [{ kind: "min_level", value: 100 }],
});

const DETAIL = {
  ...card("meadows", "Meadows", true),
  description: null,
  rarity_band: ["common"],
  boss_chance_pct: 2,
  loot_modifiers: {},
  profession_nodes: [],
  enemies: [{ code: "wolf", name: "Wolf", rank: "elite", archetype: "brute", damage_type: "physical" }],
  bosses: [{ code: "greymane", name: "Greymane", archetype: "brute", damage_type: "physical" }],
  drops: [
    { kind: "gold", tier: null, rarity: null },
    { kind: "item_pool", tier: 0, rarity: "rare" },
  ],
  risk_profiles: [{ code: "elite_hunt", name: "Elite Hunt", xp_loot_percent: 135, death_risk_percent: 260, rare_bonus_percent: 25 }],
};

function mockFetch() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/preview")
        ? { zone: "meadows", win_rate: 0.8, death_rate: 0.1, avg_duration_s: 30, dps: 12, rules: [], encounters: { meadows_pack: 10 } }
        : url.includes("/zones/")
          ? DETAIL
          : { items: [card("meadows", "Meadows", true), card("forest", "Forest", false)], next_cursor: null };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("ZoneBrowser", () => {
  it("shows eligibility, detail and runs a zone preview", async () => {
    const calls = mockFetch();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderIntl(
      <QueryClientProvider client={qc}>
        <ZoneBrowser characterId={3} />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("zone-locked-forest")).toHaveTextContent("Locked: Level 100");
    fireEvent.click(screen.getByTestId("zone-meadows"));
    expect(await screen.findByTestId("boss-greymane")).toHaveTextContent("Greymane");
    expect(screen.getByText("Wolf")).toBeInTheDocument();
    expect(screen.getByText(/T0 Rare items/)).toBeInTheDocument();
    expect(screen.getByText("135% +25% rare")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("zone-preview"));
    expect(await screen.findByTestId("zone-win-rate")).toHaveTextContent("80%");
    await waitFor(() => expect(calls.some((c) => c.url.includes("/zones/meadows/preview"))).toBe(true));
    expect(calls[0].url).toContain("character_id=3");
  });
});
