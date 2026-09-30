import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AfkProfileEditor } from "@/features/afk/afk-profile-editor";

import { renderIntl } from "./render";

const PROFILE = {
  preset_code: null,
  mode: "HYBRID",
  stance: "efficient",
  target_priority: "lowest_hp",
  potion_threshold_pct: 40,
  risk_level: "balanced",
  passive_profile_code: "warrior_bulwark",
  loot_filter: { min_rarity: "common", categories: [], min_tier: 0, class_tags: [], keep_materials: true, auto_salvage: false },
  tactics: [],
  version: 2,
};
const OPTIONS = {
  stances: [
    { code: "efficient", name: "Efficient", description: "Balanced" },
    { code: "guarded", name: "Guarded", description: "Safer" },
  ],
  target_priorities: [{ code: "lowest_hp", name: "Lowest HP" }],
  risk_levels: [
    { code: "safe", name: "Safe", enemy_power_percent: 80 },
    { code: "balanced", name: "Balanced", enemy_power_percent: 100 },
  ],
  presets: [{ code: "safe_farmer", name: "Safe Farmer", stance: "guarded", risk_level: "safe", potion_threshold_pct: 55 }],
  passive_profiles: [{ code: "warrior_bulwark", name: "Bulwark", description: "Block counters" }],
  rarities: ["common", "rare"],
  modes: ["PASSIVE_ONLY", "ACTIVE_TACTICS", "HYBRID"],
};
const PREVIEW = {
  fights: 10,
  win_rate: 0.9,
  death_rate: 0.1,
  avg_duration_s: 42.5,
  avg_damage_taken: 100,
  avg_damage_dealt: 500,
  avg_potions_used: 0.5,
  dps: 11.7,
  mode: "HYBRID",
  boss: false,
  rules: [{ index: 0, ability: "shield_slam", tag: null, name: "Shield Slam", uses: 12 }],
  fallback_basic_attacks: 30,
};

function mockFetch() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("preview")
        ? PREVIEW
        : init?.method === "PUT"
          ? { ...PROFILE, ...JSON.parse(String(init.body)), version: 3 }
          : { profile: PROFILE, options: OPTIONS };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <AfkProfileEditor characterId={5} />
    </QueryClientProvider>,
  );
}

describe("AfkProfileEditor", () => {
  it("applies a preset with the current version", async () => {
    const calls = mockFetch();
    renderEditor();
    fireEvent.click(await screen.findByTestId("preset-safe_farmer"));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(JSON.parse(String(put.init?.body))).toEqual({ preset_code: "safe_farmer", expected_version: 2 });
  });

  it("edits advanced settings, blocks preview until saved, then shows results", async () => {
    const calls = mockFetch();
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Show advanced settings" }));
    fireEvent.change(screen.getByLabelText("Stance"), { target: { value: "guarded" } });
    fireEvent.click(screen.getByLabelText("Auto-salvage the rest"));
    expect(screen.getByTestId("afk-run-preview")).toBeDisabled();
    fireEvent.click(screen.getByTestId("afk-save"));
    await waitFor(() => expect(screen.getByTestId("afk-run-preview")).toBeEnabled());
    const put = calls.find((c) => c.init?.method === "PUT")!;
    const body = JSON.parse(String(put.init?.body));
    expect(body.stance).toBe("guarded");
    expect(body.loot_filter.auto_salvage).toBe(true);
    fireEvent.click(screen.getByTestId("afk-run-preview"));
    expect(await screen.findByTestId("preview-win-rate")).toHaveTextContent("90%");
    expect(screen.getByText("Shield Slam — 12 uses")).toBeInTheDocument();
  });

  it("renders in Chinese without missing keys", async () => {
    mockFetch();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderIntl(
      <QueryClientProvider client={qc}>
        <AfkProfileEditor characterId={5} />
      </QueryClientProvider>,
      "zh-CN",
    );
    expect(await screen.findByText("预设")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "显示高级设置" })).toBeInTheDocument();
  });
});
