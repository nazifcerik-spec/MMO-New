import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { EffectListEditor, defaultParams } from "@/features/admin/items/effect-editor";
import { ItemStudio } from "@/features/admin/items/item-studio";
import { requirementPercent, type EffectDef, type Meta, type RegistryEntry } from "@/lib/api/admin-items";

import { renderIntl } from "./render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const EFFECT_REF = { $ref: "#/$defs/Effect" };
const DEFS = { Effect: { type: "object", properties: { effect_type: { type: "string" }, params: { type: "object" } } } };
const REGISTRY: RegistryEntry[] = [
  {
    effect_type: "STAT_FLAT",
    schema_version: 1,
    category: "stat",
    description: "Add a flat amount",
    params_schema: { type: "object", properties: { stat: { type: "string", title: "Stat" }, amount: { type: "number", title: "Amount", minimum: -100000, maximum: 100000 } }, required: ["stat", "amount"] },
  },
  {
    effect_type: "PROC_CHANCE",
    schema_version: 1,
    category: "trigger",
    description: "Chance on event",
    params_schema: {
      $defs: DEFS,
      type: "object",
      properties: {
        chance_percent: { type: "number", exclusiveMinimum: 0, maximum: 100, title: "Chance Percent" },
        trigger: { type: "string", enum: ["on_hit", "on_crit"], default: "on_hit", title: "Trigger" },
        effects: { type: "array", items: EFFECT_REF, title: "Effects" },
      },
      required: ["chance_percent", "effects"],
    },
  },
];
const META = { primary_stats: ["STR", "DEX", "INT", "VIT", "WIS", "SPI", "LUK"], derived_stats: ["attack_power", "armor"], damage_types: ["physical"], base_stat_value: 5, points_per_level: 3 } as unknown as Meta;

function Harness({ initial }: { initial: EffectDef[] }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <EffectListEditor value={v} onChange={setV} registry={REGISTRY} meta={META} testId="ed" />
      <pre data-testid="out">{JSON.stringify(v)}</pre>
    </>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("effect editor (schema-driven)", () => {
  it("builds defaults from the registry schema", () => {
    expect(defaultParams(REGISTRY[1])).toEqual({ chance_percent: 1, effects: [] });
  });

  it("adds effects, edits typed params, switches type and nests effect lists", () => {
    renderIntl(<Harness initial={[]} />);
    fireEvent.click(screen.getByTestId("add-effect"));
    fireEvent.change(screen.getByLabelText("Stat"), { target: { value: "STR" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "12" } });
    expect(JSON.parse(screen.getByTestId("out").textContent!)).toEqual([{ effect_type: "STAT_FLAT", params: { stat: "STR", amount: 12 } }]);
    fireEvent.change(screen.getByLabelText("Effect type"), { target: { value: "PROC_CHANCE" } });
    expect(screen.getByLabelText("Trigger")).toHaveValue("on_hit");
    fireEvent.click(screen.getAllByRole("button", { name: "+ effect" })[0]); // nested list add
    const out = JSON.parse(screen.getByTestId("out").textContent!);
    expect(out[0].effect_type).toBe("PROC_CHANCE");
    expect(out[0].params.effects[0].effect_type).toBe("STAT_FLAT");
  });

  it("advanced JSON mode rejects malformed input", () => {
    renderIntl(<Harness initial={[{ effect_type: "STAT_FLAT", params: { stat: "STR", amount: 1 } }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Advanced: raw JSON" }));
    const area = screen.getByRole("textbox", { name: "Advanced: raw JSON" });
    fireEvent.change(area, { target: { value: "{not json" } });
    fireEvent.blur(area);
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid JSON");
    fireEvent.change(area, { target: { value: '[{"effect_type":"STAT_FLAT","params":{"stat":"DEX","amount":3}}]' } });
    fireEvent.blur(area);
    expect(JSON.parse(screen.getByTestId("out").textContent!)[0].params.stat).toBe("DEX");
  });
});

describe("requirement budget estimate", () => {
  it("matches the server formula", () => {
    const r = requirementPercent(META, 100, { STR: 150, VIT: 60 });
    expect(r.budget).toBe(332);
    expect(Math.round(r.percent)).toBe(63);
  });
});

describe("ItemStudio list", () => {
  it("filters server-side and shows the quick inspector", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        const body = url.includes("/meta")
          ? { categories: ["weapon", "armor"], slots_by_category: { weapon: ["main_hand"] }, rarities: ["common", "rare"], class_tags: ["slayer"], weapon_families: [{ code: "sword" }], armor_families: ["plate"] }
          : url.includes("/admin/items/axe")
            ? { code: "axe", status: "published", revision_no: 2, edit_version: 1, has_pending_changes: false, issues: [], data: { category: "weapon", slot: "main_hand", tier: 1, min_level: 50, rarity: "rare", base_stats: [{ stat: "attack_power", amount: 55 }] }, requirement_budget: { percent: 20 }, texts: { name: { en: { value: "Axe", status: "published" }, tr: { value: "Balta", status: "draft" }, "zh-CN": { value: "", status: "missing" }, es: { value: "", status: "missing" } } } }
            : { items: [{ code: "axe", name: "Axe", category: "weapon", slot: "main_hand", family: "axe", tier: 1, min_level: 50, rarity: "rare", status: "published", revision_no: 2, has_pending_changes: false, class_tags: [], translations: { en: "published", tr: "draft", "zh-CN": "missing", es: "missing" }, updated_at: "" }], total: 1, offset: 0, limit: 100 };
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderIntl(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <ItemStudio />
        </ToastProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("studio-total")).toHaveTextContent("1 items"));
    fireEvent.change(screen.getByTestId("filter-rarity"), { target: { value: "rare" } });
    await waitFor(() => expect(calls.some((u) => u.includes("rarity=rare"))).toBe(true));
    fireEvent.click(await screen.findByTestId("row-axe"));
    expect(await screen.findByTestId("quick-inspector")).toHaveTextContent("T1 · Lv50");
    expect(screen.getByTestId("inspector-validation")).toHaveTextContent("No validation issues.");
  });
});
