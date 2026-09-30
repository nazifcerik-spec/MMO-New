import pytest
import yaml

from app.content.loader import DATA_DIR
from app.game_engine.talents import (
    NodeDef,
    TalentConfig,
    points_for_level,
    reset_quote,
    scale_effect,
    validate_allocation,
    validate_tree_graph,
)


@pytest.fixture(scope="module")
def cfg() -> TalentConfig:
    return TalentConfig.model_validate(yaml.safe_load((DATA_DIR / "balance/talents.yaml").read_text())["data"])


def _tree(cfg: TalentConfig, tree: str = "t") -> dict[str, NodeDef]:
    nodes = {
        f"{tree}_{s.slot}": NodeDef(
            f"{tree}_{s.slot}",
            tree,
            s.tier,
            s.max_rank,
            cfg.tier_points[s.tier],
            1,
            False,
            tuple(f"{tree}_{r}" for r in s.requires),
        )
        for s in cfg.layout
    }
    nodes[f"{tree}_cap"] = NodeDef(f"{tree}_cap", tree, 6, 1, 24, 850, True, (f"{tree}_n9",))
    return nodes


def test_canonical_budget(cfg: TalentConfig) -> None:
    assert (cfg.points.total_max, cfg.points.per_tree_max) == (45, 25)
    assert (cfg.capstone.required_points_in_tree, cfg.capstone.required_level) == (24, 850)
    assert points_for_level(cfg, 9) == 0 and points_for_level(cfg, 10) == 1
    assert points_for_level(cfg, 1000) == 45 and points_for_level(cfg, 978) == 45 and points_for_level(cfg, 977) == 44


def full_tree(tree: str = "t") -> dict[str, int]:
    return {f"{tree}_n1": 5, f"{tree}_n2": 3, f"{tree}_n3": 5, f"{tree}_n4": 3, f"{tree}_n5": 5, f"{tree}_n6": 3}


def test_valid_pure_build_with_capstone(cfg: TalentConfig) -> None:
    nodes = {**_tree(cfg, "a"), **_tree(cfg, "b"), **_tree(cfg, "c")}
    alloc = {
        "a_n1": 5,
        "a_n2": 3,
        "a_n3": 5,
        "a_n4": 3,
        "a_n5": 5,
        "a_n7": 2,
        "a_n9": 1,
        "a_cap": 1,
        "b_n1": 5,
        "b_n2": 3,
        "b_n3": 5,
        "b_n4": 2,
        "c_n1": 5,
    }
    assert sum(alloc.values()) == 45 and sum(v for k, v in alloc.items() if k.startswith("a_")) == 25
    assert validate_allocation(nodes, alloc, 1000, cfg) == []
    assert ("level_locked", "a_cap") in validate_allocation(nodes, alloc, 849, cfg)


@pytest.mark.parametrize(
    "alloc,code",
    [
        ({"t_n3": 1}, "tier_locked"),
        ({"t_n1": 6}, "rank_out_of_range"),
        ({"t_n1": 5, "t_n4": 1}, "prerequisite_missing"),
        ({"x_n1": 1}, "unknown_node"),
    ],
)
def test_invalid_allocations(cfg: TalentConfig, alloc: dict[str, int], code: str) -> None:
    errors = [e[0] for e in validate_allocation(_tree(cfg), alloc, 1000, cfg)]
    assert code in errors


def test_budget_and_tree_cap(cfg: TalentConfig) -> None:
    nodes = _tree(cfg)
    assert "not_enough_points" in [e[0] for e in validate_allocation(nodes, {"t_n1": 5}, 50, cfg)]
    over = {**full_tree(), "t_n7": 3, "t_n8": 3, "t_n9": 3}
    assert "tree_cap" in [e[0] for e in validate_allocation(nodes, over, 1000, cfg)]


def test_two_capstones_impossible(cfg: TalentConfig) -> None:
    nodes = {**_tree(cfg, "a"), **_tree(cfg, "b")}
    alloc = {"a_cap": 1, "b_cap": 1}
    assert "multiple_capstones" in [e[0] for e in validate_allocation(nodes, alloc, 1000, cfg)]


def test_graph_validation(cfg: TalentConfig) -> None:
    ok = list(_tree(cfg).values())
    assert validate_tree_graph(ok, cfg) == []
    cyc = [NodeDef("a", "t", 1, 1, 0, 1, False, ("b",)), NodeDef("b", "t", 1, 1, 0, 1, False, ("a",))]
    assert "circular_dependency" in [p[0] for p in validate_tree_graph(cyc, cfg)]
    unreachable = [*ok, NodeDef("late", "t", 2, 1, 0, 1, False, ("t_n9",))]
    assert "unreachable_node" in [p[0] for p in validate_tree_graph(unreachable, cfg)]
    dup = [*ok, NodeDef("t_cap2", "t", 6, 1, 24, 850, True, ())]
    assert "duplicate_capstone" in [p[0] for p in validate_tree_graph(dup, cfg)]
    weak_cap = [*ok[:-1], NodeDef("t_cap", "t", 6, 1, 10, 100, True, ())]
    assert "capstone_rule" in [p[0] for p in validate_tree_graph(weak_cap, cfg)]
    foreign = [*ok, NodeDef("z", "other", 1, 1, 0, 1, False, ("t_n1",))]
    assert "foreign_prerequisite" in [p[0] for p in validate_tree_graph(foreign, cfg)]


def test_scale_effect_and_reset_costs(cfg: TalentConfig) -> None:
    e = {
        "effect_type": "PROC_CHANCE",
        "params": {
            "chance_percent": 40,
            "effects": [{"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": 2}}],
        },
    }
    s = scale_effect(e, 3)
    assert s["params"]["chance_percent"] == 100 and s["params"]["effects"][0]["params"]["amount"] == 6
    assert reset_quote(cfg, 299, 20)["gold"] == 0
    assert reset_quote(cfg, 450, 20) == {"gold": 800, "material_code": None, "material_qty": 0}
    assert reset_quote(cfg, 700, 21) == {"gold": 4200, "material_code": "talent_reset_crystal", "material_qty": 3}
