import { describe, expect, it } from "vitest";

import { nodeLockReason, type TalentTreeView } from "@/lib/api/talents";

const node = (code: string, tier: number, req: number, requires: string[] = [], level = 1, rank = 0) => ({
  code,
  tier,
  slot: code,
  max_rank: 5,
  rank,
  required_points_in_tree: req,
  required_level: level,
  requires,
  is_capstone: tier === 6,
  name: code,
  description: null,
  effects: [],
});

const tree: TalentTreeView = {
  code: "t",
  name: "T",
  focus: "",
  spent: 0,
  nodes: [node("n1", 1, 0), node("n3", 2, 5, ["n1"]), node("cap", 6, 24, ["n3"], 850)],
};

describe("nodeLockReason", () => {
  it("locks higher tiers until enough points are spent below", () => {
    expect(nodeLockReason(tree.nodes[0], tree, {}, 100)).toBeNull();
    expect(nodeLockReason(tree.nodes[1], tree, {}, 100)).toBe("points");
    expect(nodeLockReason(tree.nodes[1], tree, { n1: 5 }, 100)).toBeNull();
  });
  it("checks level for capstones", () => {
    const full = { ...tree, nodes: [node("n1", 1, 0, [], 1, 25), node("n3", 2, 5, ["n1"], 1, 1), tree.nodes[2]] };
    expect(nodeLockReason(full.nodes[2], full, {}, 849)).toBe("level");
    expect(nodeLockReason(full.nodes[2], full, {}, 850)).toBeNull();
  });
});
