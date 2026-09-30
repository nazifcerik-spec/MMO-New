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
const TACTICS = {
  max_rules: 6,
  max_conditions: 4,
  max_core_actives: 5,
  max_ultimates: 1,
  decision_encounters: ["boss", "arena"],
  condition_kinds: ["HP_PERCENT", "TARGET_TYPE", "ENEMY_COUNT", "COOLDOWN_READY"],
  ops: ["lt", "gte"],
  tags: ["aoe", "defensive"],
  abilities: [
    { code: "shield_slam", name: "Shield Slam", type: "ACTIVE", tags: [], cooldown_s: 0 },
    { code: "whirlwind", name: "Whirlwind", type: "ACTIVE", tags: ["aoe"], cooldown_s: 8 },
  ],
  template: [
    { use: { tag: "defensive" }, when: [{ kind: "HP_PERCENT", op: "lt", value: 35 }] },
    { use: { tag: "aoe" }, when: [{ kind: "ENEMY_COUNT", op: "gte", value: 3 }] },
  ],
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
  default_mode: "HYBRID",
  tactics: TACTICS,
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

  it("builds priority rules, previews the unsaved draft and saves tactics", async () => {
    const calls = mockFetch();
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Show advanced settings" }));
    expect(screen.getByTestId("tactics-editor")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tactics-template"));
    expect(screen.getAllByTestId(/^tactic-rule-/)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Move rule 2 up" }));
    expect(screen.getByLabelText("Rule 1: use")).toHaveValue("tag:aoe");
    fireEvent.change(screen.getByLabelText("Rule 1: use"), { target: { value: "ability:whirlwind" } });
    fireEvent.click(screen.getByRole("button", { name: "+ rule" }));
    expect(screen.getByText("Always use Shield Slam when ready.")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tactics-preview"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("preview"))).toBe(true));
    const sent = JSON.parse(String(calls.find((c) => c.url.includes("preview"))!.init?.body));
    expect(sent.enemies).toBe(3);
    expect(sent.tactics[0]).toEqual({ use: { ability: "whirlwind" }, when: [{ kind: "ENEMY_COUNT", op: "gte", value: 3 }] });
    expect(sent.tactics).toHaveLength(3);
    expect(await screen.findByTestId("tactic-uses-0")).toHaveTextContent("12");
    fireEvent.click(screen.getByTestId("tactics-save"));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT")).toBe(true));
    const put = JSON.parse(String(calls.find((c) => c.init?.method === "PUT")!.init?.body));
    expect(put.tactics).toHaveLength(3);
    expect(put.expected_version).toBe(2);
  });

  it("caps the number of rules", async () => {
    mockFetch();
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Show advanced settings" }));
    const add = screen.getByRole("button", { name: "+ rule" });
    for (let i = 0; i < 6; i++) fireEvent.click(add);
    expect(screen.getAllByTestId(/^tactic-rule-/)).toHaveLength(6);
    expect(add).toBeDisabled();
  });
});
