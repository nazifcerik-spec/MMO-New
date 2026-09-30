"""Pure talent rules: point budget, allocation validation, tree-graph validation, rank scaling."""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TalentPointsCfg(_S):
    total_max: int = Field(ge=1, le=100)
    per_tree_max: int = Field(ge=1, le=100)
    first_level: int = Field(ge=1, le=1000)
    every_levels: int = Field(ge=1, le=1000)


class CapstoneCfg(_S):
    required_points_in_tree: int = Field(ge=0)
    required_level: int = Field(ge=1, le=1000)


class ResetBand(_S):
    min_level: int = Field(ge=1)
    gold_per_point: int = Field(ge=0)
    material_code: str | None = None
    material_per_10_points: int = Field(ge=0, default=0)


class ResetCfg(_S):
    free_below_level: int = Field(ge=1)
    bands: list[ResetBand]


class LayoutSlot(_S):
    slot: str
    tier: int = Field(ge=1, le=5)
    focus: int = Field(ge=0, le=4)
    max_rank: int = Field(ge=1, le=10)
    requires: list[str] = Field(default_factory=list)


class TalentConfig(_S):
    points: TalentPointsCfg
    capstone: CapstoneCfg
    layout: list[LayoutSlot]
    tier_points: dict[int, int]
    reset: ResetCfg
    trees_per_class: int = 3


def points_for_level(cfg: TalentConfig, level: int) -> int:
    p = cfg.points
    if level < p.first_level:
        return 0
    return min(p.total_max, 1 + (level - p.first_level) // p.every_levels)


@dataclass(frozen=True, slots=True)
class NodeDef:
    code: str
    tree: str
    tier: int
    max_rank: int
    required_points_in_tree: int
    required_level: int
    is_capstone: bool
    requires: tuple[str, ...] = field(default_factory=tuple)


def validate_tree_graph(nodes: list[NodeDef], cfg: TalentConfig) -> list[tuple[str, str, str]]:
    """Returns (code, node, message) problems: cycles, missing/foreign prerequisites, unreachable nodes,
    duplicate capstone, capstone rule mismatch, insufficient capacity for the capstone."""
    problems: list[tuple[str, str, str]] = []
    by_code = {n.code: n for n in nodes}
    trees: dict[str, list[NodeDef]] = defaultdict(list)
    for n in nodes:
        trees[n.tree].append(n)
    for n in nodes:
        for r in n.requires:
            req = by_code.get(r)
            if req is None:
                problems.append(("missing_prerequisite", n.code, f"requires unknown node {r}"))
            elif req.tree != n.tree:
                problems.append(("foreign_prerequisite", n.code, f"requires node {r} from another tree"))
            elif req.tier > n.tier:
                problems.append(("unreachable_node", n.code, f"requires higher-tier node {r}"))
    # cycles (DFS)
    state: dict[str, int] = {}

    def visit(code: str, stack: list[str]) -> None:
        state[code] = 1
        for r in by_code[code].requires:
            if r not in by_code:
                continue
            if state.get(r) == 1:
                problems.append(("circular_dependency", code, " -> ".join([*stack, code, r])))
            elif state.get(r) is None:
                visit(r, [*stack, code])
        state[code] = 2

    for code in by_code:
        if code not in state:
            visit(code, [])
    for tree, tnodes in trees.items():
        caps = [n for n in tnodes if n.is_capstone]
        if len(caps) > 1:
            problems.append(("duplicate_capstone", tree, f"{len(caps)} capstones"))
        for c in caps:
            if (
                c.required_points_in_tree < cfg.capstone.required_points_in_tree
                or c.required_level < cfg.capstone.required_level
            ):
                problems.append(("capstone_rule", c.code, "capstone must need 24 tree points and Lv850"))
        for n in tnodes:
            lower = sum(m.max_rank for m in tnodes if m.tier < n.tier)
            if n.required_points_in_tree > lower:
                problems.append(("unreachable_node", n.code, "not enough ranks in lower tiers"))
        non_cap = sum(n.max_rank for n in tnodes if not n.is_capstone)
        if caps and non_cap < cfg.capstone.required_points_in_tree:
            problems.append(("insufficient_capacity", tree, "tree cannot reach its capstone"))
    return problems


def validate_allocation(
    nodes: dict[str, NodeDef], alloc: dict[str, int], level: int, cfg: TalentConfig
) -> list[tuple[str, str]]:
    """(code, detail) errors; empty list = valid."""
    errors: list[tuple[str, str]] = []
    per_tree: dict[str, int] = defaultdict(int)
    for code, rank in alloc.items():
        n = nodes.get(code)
        if n is None:
            errors.append(("unknown_node", code))
            continue
        if not 0 <= rank <= n.max_rank:
            errors.append(("rank_out_of_range", code))
        per_tree[n.tree] += max(rank, 0)
    if errors:
        return errors
    total = sum(per_tree.values())
    available = points_for_level(cfg, level)
    if total > available:
        errors.append(("not_enough_points", f"{total}>{available}"))
    if total > cfg.points.total_max:
        errors.append(("total_cap", str(total)))
    for tree, spent in per_tree.items():
        if spent > cfg.points.per_tree_max:
            errors.append(("tree_cap", tree))
    capstones = 0
    for code, rank in alloc.items():
        if rank <= 0:
            continue
        n = nodes[code]
        lower = sum(r for c, r in alloc.items() if nodes[c].tree == n.tree and nodes[c].tier < n.tier)
        if lower < n.required_points_in_tree:
            errors.append(("tier_locked", code))
        if level < n.required_level:
            errors.append(("level_locked", code))
        for req in n.requires:
            if alloc.get(req, 0) < 1:
                errors.append(("prerequisite_missing", code))
        if n.is_capstone:
            capstones += 1
    if capstones > 1:
        errors.append(("multiple_capstones", str(capstones)))
    return errors


SCALABLE_KEYS = (
    "amount",
    "percent",
    "chance_percent",
    "percent_max_hp",
    "percent_of_power",
    "flat",
    "percent_per_step",
    "max_percent",
)


def scale_effect(effect: dict[str, Any], rank: int) -> dict[str, Any]:
    """Multiply numeric magnitude params by rank (recursively for nested effects)."""
    params = dict(effect.get("params", {}))
    for key in SCALABLE_KEYS:
        if isinstance(params.get(key), (int, float)) and not isinstance(params.get(key), bool):
            value = params[key] * rank
            if key == "chance_percent":
                value = min(value, 100.0)
            params[key] = value
    for nested_key in ("effects", "per_stack"):
        if isinstance(params.get(nested_key), list):
            params[nested_key] = [scale_effect(e, rank) for e in params[nested_key]]
    return {**effect, "params": params}


def reset_quote(cfg: TalentConfig, level: int, points: int) -> dict[str, Any]:
    if level < cfg.reset.free_below_level or points == 0:
        return {"gold": 0, "material_code": None, "material_qty": 0}
    band = None
    for b in cfg.reset.bands:
        if level >= b.min_level:
            band = b
    if band is None:
        return {"gold": 0, "material_code": None, "material_qty": 0}
    qty = math.ceil(points / 10) * band.material_per_10_points if band.material_code else 0
    return {"gold": points * band.gold_per_point, "material_code": band.material_code, "material_qty": qty}
