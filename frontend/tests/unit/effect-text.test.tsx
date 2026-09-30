import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EffectList } from "@/components/effects/effect-text";

import { renderIntl } from "./render";

const ORC = [
  { effect_type: "STAT_PERCENT", params: { stat: "STR", percent: 5 } },
  {
    effect_type: "THRESHOLD_TRIGGER",
    params: {
      condition: { metric: "self_hp_pct", op: "lt", value: 35 },
      effects: [{ effect_type: "DAMAGE_MULTIPLIER", params: { percent: 6 } }],
    },
  },
  { effect_type: "STAT_FLAT", params: { stat: "healing_received", amount: -2 } },
];

describe("EffectList", () => {
  it("renders structured effects in English", () => {
    renderIntl(<EffectList effects={ORC} labels={{ "stat.str.name": "Strength", "stat.healing_received.name": "Healing Received" }} />);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["• Strength +5%", "• When HP < 35%: Damage +6%", "• Healing Received −2"]);
  });

  it("renders in Turkish with localized stat labels", () => {
    renderIntl(<EffectList effects={ORC.slice(0, 2)} labels={{ "stat.str.name": "Güç" }} />, "tr");
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["• Güç %+5", "• Can < %35 olduğunda: Hasar %+6"]);
  });

  it("degrades gracefully for unknown effect types", () => {
    renderIntl(<EffectList effects={[{ effect_type: "FUTURE_THING", params: {} }]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("Future Thing");
  });
});
