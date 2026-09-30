import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ItemTooltip } from "@/features/inventory/item-tooltip";
import type { ItemView } from "@/lib/api/inventory";

import { renderIntl } from "./render";

const ITEM: ItemView = {
  id: 1, template_code: "helm", template_revision_no: 2, name: "Ironwall Helm", description: null, category: "armor", slot: "head",
  tier: 2, rarity: "rare", min_level: 120, quantity: 1,
  affixes: [{ code: "sturdy", kind: "prefix", value: 4, effect: { effect_type: "STAT_PERCENT", params: { stat: "max_hp", percent: 4 } } }],
  unique_effect: null, sockets: 1, durability: 0, durability_max: 80, bound: true, upgrade_level: 0, location: "inventory",
  equipped_slot: null, requirements: { stats: { VIT: 86, STR: 28 } },
  effects: [{ effect_type: "STAT_FLAT", params: { stat: "armor", amount: 90 } }, { effect_type: "STAT_PERCENT", params: { stat: "max_hp", percent: 4 } }],
  bind_policy: "on_equip", tradeable: false, sellable: true, vendor_value: 120, sources: [{ kind: "drop", ref: null }],
  set_code: "ironwall_regalia", class_tags: [], weapon_family: null, armor_family: "plate",
  unmet: [{ kind: "stat", stat: "VIT", required: 86, have: 40 }], equippable: false,
}; // prettier-ignore

describe("ItemTooltip", () => {
  it("shows requirements pass/fail, marketability, durability and the equip delta", () => {
    renderIntl(
      <ItemTooltip item={ITEM} labels={{ "stat.armor.name": "Armor" }} preview={{ slot: "head", replaces: null, unmet: [], equippable: true, deltas: { armor: 90.5 } }} />,
    );
    expect(screen.getByTestId("tooltip-name")).toHaveTextContent("Ironwall Helm");
    expect(screen.getByText(/Requires 86 VIT/)).toHaveClass("text-bad");
    expect(screen.getByText(/Requires 28 STR/)).toHaveTextContent("✓");
    expect(screen.getByTestId("tooltip-market")).toHaveTextContent("Not tradeable · Sells for 120 copper");
    expect(screen.getByText(/Broken/)).toBeInTheDocument();
    expect(screen.getByTestId("tooltip-delta")).toHaveTextContent("+90.5 Armor");
  });

  it("renders in Turkish and Chinese", () => {
    const { unmount } = renderIntl(<ItemTooltip item={ITEM} labels={{}} />, "tr");
    expect(screen.getByTestId("tooltip-market")).toHaveTextContent("Takas edilemez");
    unmount();
    renderIntl(<ItemTooltip item={ITEM} labels={{}} />, "zh-CN");
    expect(screen.getByText(/稀有/)).toBeInTheDocument();
  });
});
