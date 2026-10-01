import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { MarketScreen } from "@/features/economy/market-screen";

import { renderIntl } from "./render";

const listing = (id: number, seller: number) => ({
  id, template_code: "militia_axe", name: "Militia Axe", category: "weapon", tier: 1, rarity: "fine", quantity: 1,
  unit_price: 400, total_price: 400, status: "active", expires_at: "2030-01-01T00:00:00Z", seller_character_id: seller, instance_id: id + 100,
}); // prettier-ignore

function mock() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.includes("/buy")
        ? { total: 400, tax: 20, placed: "inventory" }
        : { items: [listing(1, 7), listing(2, 9)], next_cursor: null, tax_pct: 5, listing_fee_pct: 1, durations_h: [12, 24, 48, 72] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("MarketScreen", () => {
  it("shows tax info, hides buy on own listings and buys with an idempotency key after confirm", async () => {
    const calls = mock();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderIntl(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MarketScreen characterId={9} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("listing-1")).toHaveTextContent("400 each");
    expect(screen.getByText("Sales tax 5% · listing fee 1%")).toBeInTheDocument();
    expect(screen.queryByTestId("buy-2")).toBeNull();
    fireEvent.click(screen.getByTestId("buy-1"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/market/listings/1/buy"))).toBe(true));
    const post = calls.find((c) => c.url.includes("/buy"))!;
    expect(new Headers(post.init?.headers).get("Idempotency-Key")).toBeTruthy();
  });
});
