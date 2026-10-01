import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { GoalsScreen } from "@/features/goals/goals-screen";

import { renderIntl } from "./render";

const quest = (code: string, over: Record<string, unknown> = {}) => ({
  code, name: code, type: "kill", chain: null, min_level: 1, prerequisites: [], repeatable: false, status: null,
  objectives: [{ kind: "kill", zone: "whispering_meadows", count: 50 }], rewards: { xp: 1000, gold: 100 }, progress: [0], ...over,
}); // prettier-ignore

function mock() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/titles/select")
        ? { selected: "earned:slayer" }
        : url.includes("/titles")
          ? { selected: "level:novice", titles: [{ ref: "level:novice", kind: "level", name: "Novice", rarity: "bronze" }, { ref: "earned:slayer", kind: "achievement", name: "Slayer", rarity: "gold" }] }
          : url.includes("/accept")
            ? { status: "active" }
            : { available: [quest("meadow_cull")], active: [quest("first_steps", { status: "active", progress: [20] })], completed: [], locked: [] };
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
        <GoalsScreen characterId={4} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("GoalsScreen", () => {
  it("shows objective progress and accepts a quest", async () => {
    const calls = mock();
    renderScreen();
    expect(await screen.findByTestId("quest-first_steps")).toHaveTextContent("Defeat enemies in whispering_meadows — 20/50");
    fireEvent.click(screen.getByTestId("accept-meadow_cull"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/quests/meadow_cull/accept"))).toBe(true));
  });

  it("lets the player pick a displayed title with status rarity labels", async () => {
    const calls = mock();
    renderScreen();
    fireEvent.click(screen.getByTestId("goals-tab-titles"));
    const picker = await screen.findByTestId("title-picker");
    expect(picker).toHaveTextContent("Achievement · Gold");
    fireEvent.click(screen.getByLabelText(/Slayer/));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/titles/select"))).toBe(true));
    const post = calls.find((c) => c.url.includes("/titles/select"))!;
    expect(JSON.parse(String(post.init?.body))).toEqual({ ref: "earned:slayer" });
  });
});
