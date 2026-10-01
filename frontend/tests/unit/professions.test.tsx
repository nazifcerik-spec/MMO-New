import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { ProfessionsScreen } from "@/features/professions/professions-screen";

import { renderIntl } from "./render";

const card = (code: string, over: Record<string, unknown> = {}) => ({
  code, name: code, type: "gathering", tool_kind: "pickaxe", stats: ["STR", "VIT"], title: `GM ${code}`,
  specializations: [{ code: `${code}_a`, name: "Alpha" }, { code: `${code}_b`, name: "Beta" }],
  level: 1, xp: 0, xp_to_next: 66, rank: "apprentice", rank_name: "Apprentice", licensed: false, specialization_code: null,
  level_cap_now: 199, stat_bonuses: { speed: 1, quality: 0.6 }, modifiers: { yield: 0, speed: 8, quality: 0, rare_find: 0, xp: 0 },
  swap_cost_gold: 0, title_earned: false, ...over,
}); // prettier-ignore

const recipe = {
  code: "smelt_iron_ingot", name: "Smelt Iron Ingot", profession: "blacksmithing", required_level: 1, recipe_rarity: "common",
  unlock: { kind: "auto" }, known: true, ingredients: [{ template_code: "copper_ore", qty: 3, name: "Copper Ore", have: 9 }],
  output: { template_code: "iron_ingot", qty: 1, name: "Iron Ingot" }, tool_kind: null, tool_ok: true, workstation: "forge",
  craft_time_s: 20, xp: 8, quality_applies: false, fail_chance_pct: 0, max_craftable: 3, craftable: true,
}; // prettier-ignore

function mock(licensedCount: number) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/license")
        ? { cost_gold: 0 }
        : url.includes("/recipes")
          ? [recipe]
          : url.includes("/crafts")
            ? init?.method === "POST"
              ? { id: 5, ends_at: "2030-01-01T00:00:00Z" }
              : [{ id: 3, recipe: "smelt_iron_ingot", quantity: 2, started_at: "", ends_at: "", remaining_s: 0, claimable: true }]
            : url.includes("/zones")
              ? { items: [], next_cursor: null }
              : {
            professions: [card("blacksmithing", { type: "crafting" }), card("mining", { licensed: true, level: 250, level_cap_now: 500, rank: "expert", rank_name: "Expert" }), card("fishing")],
            licenses: { active: licensedCount, max: 3, free_remaining: 2, cooldown_until: null },
            specialization_level: 200,
            level_cap: 500,
            unlicensed_level_cap: 199,
          };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ProfessionsScreen characterId={9} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ProfessionsScreen", () => {
  it("shows ranks, caps, modifiers and specialization only when licensed at 200+", async () => {
    mock(1);
    renderScreen();
    expect(await screen.findByTestId("prof-level-mining")).toHaveTextContent("Expert · Lv 250/500");
    expect(screen.getByTestId("prof-level-fishing")).toHaveTextContent("Lv 1/199");
    expect(screen.getByTestId("spec-mining")).toBeInTheDocument();
    expect(screen.queryByTestId("spec-fishing")).toBeNull();
    expect(screen.getByTestId("profession-mining")).toHaveTextContent("+8% speed");
  });

  it("activates a license with an idempotency key and disables when all slots are used", async () => {
    const calls = mock(1);
    renderScreen();
    fireEvent.click(await screen.findByTestId("license-fishing"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/fishing/license"))).toBe(true));
    const post = calls.find((c) => c.url.includes("/license"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ active: true });
    expect(new Headers(post.init?.headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("lists recipes with material counts, starts crafts idempotently and offers claim for finished jobs", async () => {
    const calls = mock(1);
    renderScreen();
    const row = await screen.findByTestId("recipe-smelt_iron_ingot");
    expect(row).toHaveTextContent("Copper Ore 9/3");
    expect(await screen.findByTestId("claim-craft-3")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("craft-smelt_iron_ingot"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/crafts") && c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.url.endsWith("/crafts") && c.init?.method === "POST")!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ recipe_code: "smelt_iron_ingot", quantity: 1 });
    expect(new Headers(post.init?.headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("blocks new licenses at the cap", async () => {
    mock(3);
    renderScreen();
    expect(await screen.findByTestId("license-fishing")).toBeDisabled();
    expect(screen.getByTestId("license-summary")).toHaveTextContent("Specialist Licenses: 3/3");
  });
});
