import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProgressionPanel } from "@/features/progression/progression-panel";

import { renderIntl } from "./render";

const line = (code: string, v: number) => ({
  code,
  raw: v,
  effective: v,
  percent_bonus: 0,
  final: v,
  breakdown: [{ source: "base", ref: "base", flat: 5, percent: 0 }],
});

const VIEW = {
  character_id: 7,
  level: 12,
  level_cap: 1000,
  xp: 50,
  xp_to_next: 200,
  progress_percent: 25,
  unspent_stat_points: 2,
  mastery_xp: 0,
  title_code: "novice",
  next_title: { code: "veteran", level: 100 },
  next_breakpoint: 100,
  breakpoints: [100, 300, 600, 850, 1000],
  allocation: { STR: 0, DEX: 0, INT: 0, VIT: 0, WIS: 0, SPI: 0, LUK: 0 },
  version: 3,
  stats: {
    level: 12,
    primary: Object.fromEntries(["STR", "DEX", "INT", "VIT", "WIS", "SPI", "LUK"].map((s) => [s, line(s, 5)])),
    derived: { max_hp: line("max_hp", 314) },
  },
  labels: { "title.level.novice.name": "Novice", "title.level.veteran.name": "Veteran", "stat.max_hp.name": "Max HP" },
};

function mockFetch() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("stat-profiles")
        ? []
        : url.includes("respec-quote")
          ? { points_refunded: 0, gold_cost: 0 }
          : url.includes("allocate")
            ? { allocation: {}, unspent_stat_points: 0, version: 4 }
            : VIEW;
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
      <ProgressionPanel characterId={7} />
    </QueryClientProvider>,
  );
}

describe("ProgressionPanel", () => {
  it("shows title, xp and next goals", async () => {
    mockFetch();
    renderPanel();
    expect(await screen.findByTestId("level-heading")).toHaveTextContent("[Novice] Level 12 / 1000");
    expect(screen.getByTestId("xp-text")).toHaveTextContent("50 / 200 XP (25.0%)");
    expect(screen.getByText("Next title: Veteran at Lv 100")).toBeInTheDocument();
    expect(screen.getByTestId("derived-max_hp")).toHaveTextContent("314");
  });

  it("limits pending allocation to unspent points and sends an idempotency key", async () => {
    const calls = mockFetch();
    renderPanel();
    await screen.findByTestId("level-heading");
    const inc = screen.getAllByRole("button", { name: /^Increase/ });
    fireEvent.click(inc[0]);
    fireEvent.click(inc[0]);
    expect(inc[0]).toBeDisabled();
    expect(screen.getByTestId("unspent")).toHaveTextContent("0");
    fireEvent.click(screen.getByRole("button", { name: "Allocate" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/stats/allocate"))).toBe(true));
    const post = calls.find((c) => c.url.includes("/stats/allocate"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ points: { STR: 2 }, expected_version: 3 });
    expect(new Headers(post.init?.headers).get("Idempotency-Key")).toMatch(/[0-9a-f-]{36}/);
  });
});
