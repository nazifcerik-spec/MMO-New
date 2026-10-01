"""Pure long-term goal rules: quest schema/graph checks, objective progress from aggregated events, achievement
thresholds, status rarity (presentation only) and prestige ranks."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RARITIES = ("bronze", "silver", "gold", "platinum", "mythic", "relic")
QUEST_TYPES = ("kill", "collect", "profession", "explore", "boss", "promotion", "tutorial")
CODE = r"^[a-z][a-z0-9_]{0,95}$"


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Objective(_S):
    """kill/boss: count in `zone` (or anywhere) · explore: finish an AFK session in `zone` · collect: hold
    `template_code` × count at turn-in (consumed) · profession: reach `level` in `profession` · level: reach
    character `level` · action: perform `action` (equip_item, start_afk, craft_item, trade) count times."""

    kind: Literal["kill", "boss", "explore", "collect", "profession", "level", "action"]
    count: int = Field(default=1, ge=1, le=10_000_000)
    zone: str | None = Field(default=None, pattern=CODE)
    template_code: str | None = Field(default=None, pattern=CODE)
    profession: str | None = Field(default=None, pattern=CODE)
    level: int | None = Field(default=None, ge=1, le=1000)
    action: Literal["equip_item", "start_afk", "craft_item", "trade"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Objective":
        need = {"explore": "zone", "collect": "template_code", "profession": "profession", "action": "action"}
        if self.kind in need and getattr(self, need[self.kind]) is None:
            raise ValueError(f"{self.kind} objectives need {need[self.kind]}")
        if self.kind in ("profession", "level") and self.level is None:
            raise ValueError(f"{self.kind} objectives need level")
        return self

    def target(self) -> int:
        return self.level if self.kind in ("profession", "level") and self.level else self.count


class ItemReward(_S):
    template_code: str = Field(pattern=CODE)
    qty: int = Field(default=1, ge=1, le=10_000)


class Rewards(_S):
    xp: int = Field(default=0, ge=0, le=10**12)
    gold: int = Field(default=0, ge=0, le=10**12)
    items: tuple[ItemReward, ...] = Field(default=(), max_length=8)
    title_code: str | None = Field(default=None, pattern=CODE)


class QuestData(_S):
    quest_type: Literal["kill", "collect", "profession", "explore", "boss", "promotion", "tutorial"]
    chain: str | None = Field(default=None, pattern=CODE)
    min_level: int = Field(default=1, ge=1, le=1000)
    prerequisites: tuple[str, ...] = Field(default=(), max_length=8)
    class_codes: tuple[str, ...] = Field(default=(), max_length=10)
    objectives: tuple[Objective, ...] = Field(min_length=1, max_length=6)
    rewards: Rewards = Rewards()
    repeatable: bool = False


class AchievementData(_S):
    counter: str = Field(pattern=CODE)
    threshold: int = Field(ge=1, le=10**15)
    status_rarity: Literal["bronze", "silver", "gold", "platinum", "mythic", "relic"]
    points: int = Field(default=10, ge=0, le=10_000)
    title_code: str | None = Field(default=None, pattern=CODE)
    category: str = Field(default="general", pattern=CODE)


class LevelRarity(_S):
    level: int = Field(ge=1, le=1000)
    rarity: str


class PrestigeRank(_S):
    points: int = Field(ge=0)
    rarity: str


class PrestigeConfig(_S):
    mastery_xp_per_point: int = Field(ge=1)
    ranks: tuple[PrestigeRank, ...] = Field(min_length=1)


class GoalsConfig(_S):
    promotion_quest_required: dict[str, bool]
    promotion_quests: dict[str, str]
    max_active_quests: int = Field(ge=1, le=200)
    level_title_rarity: tuple[LevelRarity, ...] = Field(min_length=1)
    class_stage_rarity: dict[str, str]
    race_title_rarity: str
    profession_title_rarity: str
    quest_title_rarity: str
    prestige: PrestigeConfig

    @model_validator(mode="after")
    def _check(self) -> "GoalsConfig":
        used = [r.rarity for r in self.level_title_rarity] + list(self.class_stage_rarity.values())
        used += [self.race_title_rarity, self.profession_title_rarity, self.quest_title_rarity]
        used += [r.rarity for r in self.prestige.ranks]
        if any(r not in RARITIES for r in used):
            raise ValueError("unknown status rarity")
        return self


def find_cycle(graph: dict[str, tuple[str, ...]]) -> list[str] | None:
    """Return one prerequisite cycle (as a path) if the quest graph has any."""
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                return [*stack[stack.index(nxt) :], nxt]
            if state.get(nxt) is None and (found := visit(nxt)):
                return found
        stack.pop()
        state[node] = 2
        return None

    for n in sorted(graph):
        if state.get(n) is None and (found := visit(n)):
            return found
    return None


def apply_event(objectives: list[dict[str, Any]], progress: list[int], event: str, data: dict[str, Any]) -> list[int]:
    """Advance objective counters for one aggregated event. Level-type objectives store the best value seen."""
    out = list(progress) + [0] * (len(objectives) - len(progress))
    for i, o in enumerate(objectives):
        kind = o["kind"]
        zone_ok = o.get("zone") in (None, data.get("zone_code"))
        if event == "afk_claimed" and zone_ok:
            if kind == "kill":
                out[i] += int(data.get("kills", 0))
            elif kind == "boss":
                out[i] += int(data.get("boss_kills", 0))
            elif kind == "explore" and data.get("zone_code") == o.get("zone"):
                out[i] = max(out[i], 1)
        if event == "level" and kind == "level":
            out[i] = max(out[i], int(data.get("level", 0)))
        if event == "profession_level" and kind == "profession" and o.get("profession") == data.get("profession"):
            out[i] = max(out[i], int(data.get("level", 0)))
        if event == "action" and kind == "action" and o.get("action") == data.get("action"):
            out[i] += int(data.get("count", 1))
    return [min(v, Objective.model_validate(o).target()) for v, o in zip(out, objectives, strict=True)]


def complete(objectives: list[dict[str, Any]], progress: list[int], *, collected: dict[str, int]) -> bool:
    for i, o in enumerate(objectives):
        obj = Objective.model_validate(o)
        if obj.kind == "collect":
            if collected.get(obj.template_code or "", 0) < obj.count:
                return False
        elif (progress[i] if i < len(progress) else 0) < obj.target():
            return False
    return True


def level_rarity(cfg: GoalsConfig, level: int) -> str:
    rarity = cfg.level_title_rarity[0].rarity
    for step in cfg.level_title_rarity:
        if level >= step.level:
            rarity = step.rarity
    return rarity


def prestige(cfg: GoalsConfig, achievement_points: int, mastery_xp: int) -> dict[str, Any]:
    points = achievement_points + mastery_xp // cfg.prestige.mastery_xp_per_point
    rank = cfg.prestige.ranks[0]
    nxt = None
    for r in cfg.prestige.ranks:
        if points >= r.points:
            rank = r
        elif nxt is None:
            nxt = r
    return {
        "points": points,
        "rarity": rank.rarity,
        "next": {"points": nxt.points, "rarity": nxt.rarity} if nxt else None,
    }
