import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { BalanceLab } from "@/features/admin/balance/balance-lab";

import { renderIntl } from "./render";

const s = (mean: number) => ({ mean, min: mean - 1, max: mean + 1, stdev: 0.5 });

function mock() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/simulate")
        ? { zone: "ironroot_forest", metrics: { kills_per_hour: s(120), death_probability: s(0.02) }, combat: { dps: 230, win_rate: 1 }, profession: null, per_iteration: [{ iteration: 0, seed: 11, xp_per_hour: 1000 }] }
        : url.includes("/check")
          ? { level: 100, warnings: [{ section: "support", subject: "bard", message: "solo kill speed 49% of pure DPS" }], sections: { support: [{ class: "bard", category: "support", vs_dps_pct: 49 }, { class: "warrior", category: "combat", vs_dps_pct: 100 }] } }
          : { window_days: 30, min_bucket: 3, sessions: { started: 10, completion_rate: 0.8 }, zones: { whispering_meadows: 7, other: 3 }, profession_usage: { gathering: {}, crafting: {} }, funnel: [{ step: "registered", count: 10, drop_off_pct: 0 }, { step: "created_character", count: 8, drop_off_pct: 20 }] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("BalanceLab", () => {
  it("runs a simulation, shows checker warnings with a band chart and aggregate telemetry", async () => {
    const calls = mock();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderIntl(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <BalanceLab />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/never change balance/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("run-sim"));
    expect(await screen.findByTestId("sim-result")).toHaveTextContent("Kills / hour");
    const body = JSON.parse(String(calls.find((c) => c.url.includes("/simulate"))!.init?.body));
    expect(body.base_class).toBe("warrior");
    fireEvent.click(screen.getByTestId("run-check"));
    expect(await screen.findByTestId("check-result")).toHaveTextContent("bard: solo kill speed 49% of pure DPS");
    await waitFor(() => expect(screen.getByTestId("telemetry")).toHaveTextContent("Onboarding funnel"));
    fireEvent.click(screen.getAllByText("Table view")[0]);
    expect(screen.getAllByRole("table").length).toBeGreaterThan(0);
  });
});
