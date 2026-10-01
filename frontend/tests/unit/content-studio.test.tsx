import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { BundlePublisher } from "@/features/admin/content/bundle-publisher";
import { EntityEditor } from "@/features/admin/content/entity-editor";

import { renderIntl } from "./render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }), usePathname: () => "/admin/content" }));

const entity = { code: "q1", status: "draft", revision_no: 0, name_key: "quest.q1.name", description_key: null, published_at: null, has_pending_changes: true, edit_version: 1, data: { quest_type: "kill" }, live_data: null };

function mock(stage = "review") {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      let body: unknown = entity;
      if (url.includes("/workflow") || url.includes("/review/")) body = { stage: url.includes("/approve") ? "approved" : stage, edit_version: 1, review: { status: "requested", note: null }, review_required: true };
      else if (url.includes("/references")) body = { total: 2, by_type: { quest: 1, achievement: 1 }, items: [{ entity_type: "quest", code: "q2", status: "draft", via: "draft" }], outgoing: [{ entity_type: "zone", code: "whispering_meadows" }] };
      else if (url.includes("/pending")) body = [{ entity_type: "base_class", code: "warrior", status: "published", new: false, updated_at: "2026-01-01" }, { entity_type: "ability", code: "cleave", status: "draft", new: true, updated_at: "2026-01-01" }];
      else if (url.includes("/releases")) body = { release_version: 42 };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderIntl(
    <QueryClientProvider client={qc}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("EntityEditor", () => {
  it("shows the workflow stepper and approves a pending review", async () => {
    const calls = mock("review");
    wrap(<EntityEditor type="quest" code="q1" />);
    fireEvent.click(await screen.findByTestId("editor-tab-workflow"));
    expect(await screen.findByTestId("workflow-stages")).toHaveTextContent("DraftValidationReviewPublishedArchived");
    expect(screen.getByTestId("workflow-stage")).toHaveTextContent("Review is required before publishing.");
    fireEvent.click(screen.getByTestId("approve"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/quest/q1/review/approve"))).toBe(true));
  });

  it("shows incoming/outgoing dependencies with the hard-delete protection note", async () => {
    mock();
    wrap(<EntityEditor type="quest" code="q1" />);
    fireEvent.click(await screen.findByTestId("editor-tab-references"));
    const refs = await screen.findByTestId("references");
    expect(refs).toHaveTextContent("Referenced by (2)");
    expect(refs).toHaveTextContent("quest: 1 · achievement: 1");
    expect(refs).toHaveTextContent("zone:whispering_meadows");
    expect(refs).toHaveTextContent("cannot be hard-deleted");
  });
});

describe("BundlePublisher", () => {
  it("publishes selected drafts together under one release", async () => {
    const calls = mock();
    wrap(<BundlePublisher />);
    fireEvent.click(await screen.findByLabelText("base_class:warrior"));
    fireEvent.click(screen.getByLabelText("ability:cleave"));
    fireEvent.change(screen.getByLabelText("Release label"), { target: { value: "warrior rework" } });
    fireEvent.click(screen.getByTestId("publish-bundle"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/admin/content/releases"))).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.url.endsWith("/releases"))!.init?.body));
    expect(body.items).toEqual([{ entity_type: "base_class", code: "warrior" }, { entity_type: "ability", code: "cleave" }]);
    expect(body.label).toBe("warrior rework");
  });
});
