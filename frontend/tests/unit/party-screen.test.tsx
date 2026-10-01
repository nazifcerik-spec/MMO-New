import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { PartyScreen } from "@/features/party/party-screen";

import { renderIntl } from "./render";

const member = (id: number, over: Record<string, unknown> = {}) => ({
  character_id: id, name: `Hero${id}`, level: 30, class_code: "warrior", role: "tank", online: true, afk: null, leader: false, ...over,
}); // prettier-ignore

function mock(leaderId: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.includes("/chat")
        ? [{ id: 1, character_id: 2, name: "Hero2", body: "hi", at: "2030-01-01T00:00:00Z" }]
        : url.includes("/zones")
          ? { items: [], next_cursor: null }
          : {
              invites: [],
              role_options: ["tank", "dps"],
              max_size: 5,
              party: {
                id: 1, leader_character_id: leaderId, max_size: 5, pending_invites: 0,
                members: [member(1, { leader: leaderId === 1 }), member(2, { role: "healer", class_code: "cleric", online: false, afk: { zone_code: "whispering_meadows", ends_at: "2030-01-01T02:00:00Z", group: true } })],
                composition_bonuses: ["frontline_and_mender"],
              },
            }; // prettier-ignore
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <PartyScreen characterId={1} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("PartyScreen", () => {
  it("shows members with role/online/AFK state, composition bonus, chat and leader-only controls", async () => {
    mock(1);
    renderScreen();
    const list = await screen.findByTestId("party-members");
    expect(list).toHaveTextContent("Hero2");
    expect(list).toHaveTextContent("Healer");
    expect(list).toHaveTextContent("AFK in whispering_meadows");
    expect(screen.getByTestId("composition")).toHaveTextContent("Frontline & Mender");
    expect(await screen.findByText("hi")).toBeInTheDocument();
    expect(screen.getByTestId("group-afk")).toBeInTheDocument();
    expect(screen.getByTestId("invite")).toBeInTheDocument();
  });

  it("hides leader controls for regular members", async () => {
    mock(2);
    renderScreen();
    await screen.findByTestId("party-members");
    expect(screen.queryByTestId("group-afk")).toBeNull();
    expect(screen.queryByTestId("invite")).toBeNull();
  });
});
