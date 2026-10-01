"""Launch item catalog generator (Phase 19): deterministic, token-named, validator-ready template rows.

Pure: callers pass the catalog config, item rules, generator curves and reference data. Output rows are
`{code, data, l10n: {name: {locale: text}}, line, kind}`; nothing is written here. The same inputs always
produce the same codes, names and stats (no RNG; rotation/offset arithmetic only)."""

import re
import statistics
from collections import Counter
from typing import Any

from app.game_engine.item_generator import GeneratorConfig, curve_key
from app.game_engine.items import RARITY_ORDER, ItemRules, suggested_requirements

TIERS = tuple(range(11))
LOCALES = ("en", "tr", "zh-CN", "es")
STACK = {"consumable": 50, "material": 999, "recipe": 20, "quest_key_token": 99}


def tier_counts(count: int, offset: int) -> dict[int, int]:
    """Spread `count` over T0..T10 evenly; the remainder rotates by `offset` so lines cover different tiers."""
    base, rem = divmod(count, len(TIERS))
    return {t: base + (1 if (t - offset) % len(TIERS) < rem else 0) for t in TIERS}


def _tok(tokens: list[str]) -> dict[str, str]:
    return dict(zip(LOCALES, tokens, strict=True))


def _name(pattern: dict[str, str], parts: dict[str, dict[str, str]]) -> dict[str, str]:
    out = {}
    for loc in LOCALES:
        text = pattern[loc].format(**{k: v.get(loc, "") for k, v in parts.items()})
        text = re.sub(r"\s+", " ", text).strip()
        out[loc] = text.replace(" :", ":")
    return out


class _Line:
    """Assigns tiers, levels, rarities and distinct epithets inside one catalog line."""

    def __init__(self, cfg: dict[str, Any], rules: ItemRules, index: int, count: int) -> None:
        self.cfg, self.rules, self.index = cfg, rules, index
        self.per_tier = tier_counts(count, index)
        self.epithets = list(cfg["epithets"])

    def slots(self, equippable: bool) -> list[dict[str, Any]]:
        out = []
        for t in TIERS:
            n = self.per_tier[t]
            gate = self.rules.gate(t)
            band = [r for r in gate.rarities if equippable or r != "relic"] or ["mythic"]
            span = gate.max_level - gate.min_level
            for k in range(n):
                level = gate.min_level + (span * k // (n - 1) if n > 1 else span // 2)
                rarity = band[(k + self.index) % len(band)]
                ep = self.epithets[(self.index * 7 + t * 3 + k * 5) % len(self.epithets)]
                out.append({"tier": t, "k": k, "level": level, "rarity": rarity, "epithet": ep})
        return out


def _vendor(gen: GeneratorConfig, level: int, rarity: str, scale: float = 1.0) -> int:
    v = gen.vendor_value
    return max(1, int((v.base + v.per_level * level) * (RARITY_ORDER.index(rarity) + 1) ** v.rarity_pow * scale))


def _unique(
    cfg: dict[str, Any], category: str, tier: int, rarity: str, profession: str | None
) -> dict[str, Any] | None:
    if RARITY_ORDER.index(rarity) < RARITY_ORDER.index("legendary"):
        return None
    u = cfg["unique_effects"][category]
    value = round(u["base"] + u["per_tier"] * tier, 2)
    if category == "profession_tool":
        effect = {
            "effect_type": "PROFESSION_YIELD_MOD",
            "params": {"profession": profession, "kind": u["profession_kind"], "percent": value},
        }
    elif u.get("percent"):
        effect = {"effect_type": "STAT_PERCENT", "params": {"stat": u["stat"], "percent": value}}
    else:
        effect = {"effect_type": "STAT_FLAT", "params": {"stat": u["stat"], "amount": value}}
    return {
        "key": f"{category}_t{tier}_{rarity}",
        "effects": [effect],
        "mastery_scaling": rarity in ("mythic", "relic"),
    }


def _equipment(
    cfg: dict[str, Any],
    rules: ItemRules,
    gen: GeneratorConfig,
    *,
    code_prefix: str,
    line_index: int,
    count: int,
    category: str,
    slot: str,
    weapon_family: str | None,
    weapon_kind: str | None,
    armor_family: str | None,
    profile: str | None,
    tags: list[str],
    pool: list[str],
    material: str,
    noun: dict[str, str],
    family_word: dict[str, str],
    salvage_line: str,
    tool: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    line = _Line(cfg, rules, line_index, count)
    rows = []
    for s in line.slots(equippable=True):
        t, rarity, level = s["tier"], s["rarity"], s["level"]
        mult = gen.rarity_multipliers.get(rarity, 1.0) * gen.slot_multipliers.get(slot, 1.0)
        curve = [] if category == "profession_tool" else gen.curves[curve_key(category, weapon_kind, armor_family)]
        reqs = suggested_requirements(rules, profile, level, t) if profile else {}
        unique = _unique(cfg, category, t, rarity, tool["profession"] if tool else None)
        effects: list[dict[str, Any]] = []
        if tool:
            effects = [_yield_mod(tool["profession"], k, tool[k] * (t + 1)) for k in ("speed", "yield")]
        relic = rarity == "relic"
        fixed = [dict(e) for e in (unique or {}).get("effects", [])] + (
            [{"effect_type": "STAT_PERCENT", "params": {"stat": "max_hp", "percent": 5}}] if relic else []
        )
        epithet = cfg["epithets"][s["epithet"]]
        code = f"{code_prefix}_t{t}_{s['epithet']}"
        rows.append(
            {
                "code": code,
                "kind": category,
                "line": code_prefix,
                "l10n": {
                    "name": _name(
                        cfg["patterns"]["equipment"],
                        {
                            "epithet": _tok(epithet),
                            "material": _tok(cfg["materials"][material][t]),
                            "family": family_word,
                            "noun": noun,
                        },
                    )
                },
                "data": {
                    "category": category,
                    "subcategory": tool["kind"] if tool else None,
                    "slot": slot,
                    "family": weapon_family or armor_family or (tool["kind"] if tool else category),
                    "weapon_family": weapon_family,
                    "armor_family": armor_family,
                    "tier": t,
                    "min_level": level,
                    "rarity": rarity,
                    "requirement_profile": profile,
                    "requirements": {"stats": {k: v for k, v in reqs.items() if v > 0}},
                    "base_stats": [
                        {"stat": c.stat, "amount": round((c.base + c.per_level * level) * mult, 2)} for c in curve
                    ],
                    "effects": effects,
                    "affix_rules": {"pool": [], "fixed": fixed} if relic else {"pool": list(pool)},
                    "unique_effect": unique,
                    "class_tags": list(tags)[:4],
                    "durability": {"max": gen.durability.base + gen.durability.per_tier * t},
                    "vendor_value": _vendor(gen, level, rarity),
                    "salvage": [{"template_code": f"{salvage_line}_t{t}_{{ep}}", "min_qty": 1, "max_qty": 1 + t // 2}],
                    "sources": [{"kind": "drop"}, {"kind": "craft"}] if not relic else [{"kind": "drop"}],
                    "bind_policy": "on_equip" if RARITY_ORDER.index(rarity) >= RARITY_ORDER.index("epic") else "none",
                    "icon": f"items/{weapon_family or armor_family or (tool['kind'] if tool else category)}_{slot}.svg",
                },
            }
        )
    return rows


def _stackables(
    cfg: dict[str, Any],
    rules: ItemRules,
    gen: GeneratorConfig,
    *,
    category: str,
    lines: dict[str, dict[str, Any]],
    start_index: int,
    pattern: str,
) -> list[dict[str, Any]]:
    rows = []
    for li, (code, spec) in enumerate(lines.items()):
        line = _Line(cfg, rules, start_index + li, spec["count"])
        for s in line.slots(equippable=False):
            t, rarity, level = s["tier"], s["rarity"], s["level"]
            name = _name(
                cfg["patterns"][pattern],
                {
                    "grade": _tok(cfg["grades"][t]),
                    "epithet": _tok(cfg["epithets"][s["epithet"]]),
                    "noun": _tok(spec["noun"]),
                },
            )
            data: dict[str, Any] = {
                "category": category,
                "subcategory": spec.get("subcategory", code),
                "family": code,
                "tier": t,
                "min_level": level,
                "rarity": rarity,
                "stack_size": STACK.get(category, 1),
                "vendor_value": _vendor(gen, level, rarity, 0.2),
                "sources": [{"kind": "drop"}],
                "icon": f"items/{code}.svg",
            }
            if category == "consumable":
                data["effects"] = _consumable_effects(spec["subcategory"], t)
                data["sources"] = [{"kind": "craft"}, {"kind": "vendor"}]
            elif category == "material":
                data["sources"] = [{"kind": "drop"}, {"kind": "craft" if spec["profession"] in _CRAFTED else "drop"}][
                    :1
                ]
            elif category == "recipe":
                data["sources"] = [{"kind": "drop"}, {"kind": "vendor"}]
            elif category == "quest_key_token":
                data.update({"bind_policy": "on_pickup", "tradeable": False, "sellable": False, "vendor_value": 0})
                data["sources"] = [{"kind": "quest"}]
            elif category == "cosmetic_collectible":
                data.update(
                    {
                        "stack_size": 1,
                        "bind_policy": "account",
                        "tradeable": False,
                        "vendor_value": 0,
                        "sellable": False,
                    }
                )
                data["sources"] = [{"kind": "event"}, {"kind": "drop"}]
            rows.append(
                {
                    "code": f"{code}_t{t}_{s['epithet']}",
                    "kind": category,
                    "line": code,
                    "l10n": {"name": name},
                    "data": data,
                }
            )
    return rows


def _yield_mod(profession: str, kind: str, percent: float) -> dict[str, Any]:
    params = {"profession": profession, "kind": kind, "percent": round(percent, 2)}
    return {"effect_type": "PROFESSION_YIELD_MOD", "params": params}


_CRAFTED = {"blacksmithing", "leatherworking", "tailoring"}


def _consumable_effects(sub: str, t: int) -> list[dict[str, Any]]:
    if sub == "potion":
        return [{"effect_type": "HEAL", "params": {"percent_of_power": 60 + 25 * t}}]
    if sub == "elixir":
        return [
            {
                "effect_type": "BUFF",
                "params": {
                    "duration_s": 1800,
                    "effects": [{"effect_type": "STAT_PERCENT", "params": {"stat": "attack_power", "percent": 3 + t}}],
                },
            }
        ]
    if sub == "food":
        return [
            {
                "effect_type": "BUFF",
                "params": {
                    "duration_s": 3600,
                    "effects": [{"effect_type": "STAT_PERCENT", "params": {"stat": "max_hp", "percent": 2 + t}}],
                },
            }
        ]
    return [{"effect_type": "SHIELD", "params": {"percent_max_hp": 5 + t, "duration_s": 12}}]


def generate(
    cfg: dict[str, Any],
    rules: ItemRules,
    gen: GeneratorConfig,
    *,
    weapon_families: dict[str, dict[str, Any]],
    armor_families: dict[str, dict[str, Any]],
    professions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    idx = 0
    # materials first: equipment salvage outputs point at them
    rows += _stackables(
        cfg, rules, gen, category="material", lines=cfg["material_lines"], start_index=idx, pattern="graded"
    )
    idx += len(cfg["material_lines"])
    wl = cfg["weapon_lines"]
    for code, spec in wl["families"].items():
        fam = weapon_families[code]
        rows += _equipment(
            cfg, rules, gen, code_prefix=f"wpn_{code}", line_index=idx, count=wl["per_family"], category="weapon",
            slot="main_hand", weapon_family=code, weapon_kind=fam["kind"], armor_family=None, profile=spec["profile"],
            tags=spec["tags"], pool=wl["pool"], material=wl["material"], noun=_tok_l10n(fam["l10n"]), family_word={},
            salvage_line="ingot",
        )  # fmt: skip
        idx += 1
    al = cfg["armor_lines"]
    for fam_code, spec in al["families"].items():
        word = _tok(cfg["armor_family_words"][fam_code]) if fam_code in cfg["armor_family_words"] else {}
        for slot in al["slots"]:
            rows += _equipment(
                cfg, rules, gen, code_prefix=f"arm_{fam_code}_{slot}", line_index=idx, count=al["per_line"],
                category="armor", slot=slot, weapon_family=None, weapon_kind=None, armor_family=fam_code,
                profile=spec["profile"], tags=spec["tags"], pool=al["pool"], material=spec["material"],
                noun=_tok(cfg["slot_nouns"][slot]), family_word=word,
                salvage_line={"metal": "ingot", "hide": "leather", "fabric": "bolt"}[spec["material"]],
            )  # fmt: skip
            idx += 1
    for extra in al["extra"]:
        fam_code = extra["family"]
        rows += _equipment(
            cfg, rules, gen, code_prefix=f"arm_{fam_code or 'cloak'}_{extra['slot']}", line_index=idx,
            count=extra["count"], category="armor", slot=extra["slot"], weapon_family=None, weapon_kind=None,
            armor_family=fam_code, profile=extra["profile"], tags=extra["tags"], pool=al["pool"],
            material=extra["material"], noun=_tok(cfg["slot_nouns"][extra["slot"]]), family_word={},
            salvage_line={"metal": "ingot", "hide": "leather", "fabric": "bolt"}[extra["material"]],
        )  # fmt: skip
        idx += 1
    acc = cfg["accessory_lines"]
    for slot, count in acc["slots"].items():
        before = len(rows)
        rows += _equipment(
            cfg, rules, gen, code_prefix=f"acc_{slot}", line_index=idx, count=count, category="accessory", slot=slot,
            weapon_family=None, weapon_kind=None, armor_family=None, profile=None, tags=[], pool=acc["pool"],
            material=acc["material"], noun=_tok(cfg["slot_nouns"][slot]), family_word={}, salvage_line="gem",
        )  # fmt: skip
        for i, r in enumerate(rows[before:]):
            r["data"]["class_tags"] = [acc["tag_cycle"][(i + idx) % len(acc["tag_cycle"])]]
            r["data"]["durability"] = {"max": 0}
        idx += 1
    tl = cfg["tool_lines"]
    for p in professions:
        rows += _equipment(
            cfg, rules, gen, code_prefix=f"tool_{p['code']}", line_index=idx, count=tl["per_profession"],
            category="profession_tool", slot="tool", weapon_family=None, weapon_kind=None, armor_family=None,
            profile=None, tags=[], pool=tl["pool"], material=tl["material"], noun=_tok(tl["nouns"][p["tool"]]),
            family_word={}, salvage_line="component",
            tool={"profession": p["code"], "kind": p["tool"], "speed": tl["speed_per_tier"],
                  "yield": tl["yield_per_tier"]},
        )  # fmt: skip
        idx += 1
    rows += _stackables(
        cfg, rules, gen, category="consumable", lines=cfg["consumable_lines"], start_index=idx, pattern="graded"
    )
    idx += len(cfg["consumable_lines"])
    rows += _stackables(
        cfg, rules, gen, category="recipe", lines=cfg["recipe_lines"], start_index=idx, pattern="recipe"
    )
    idx += len(cfg["recipe_lines"])
    rows += _stackables(
        cfg, rules, gen, category="quest_key_token", lines=cfg["quest_lines"], start_index=idx, pattern="graded"
    )
    idx += len(cfg["quest_lines"])
    rows += _stackables(
        cfg, rules, gen, category="cosmetic_collectible", lines=cfg["cosmetic_lines"], start_index=idx, pattern="graded"
    )
    _link_salvage(rows)
    return rows


def _tok_l10n(l10n: dict[str, str]) -> dict[str, str]:
    return {loc: l10n.get(loc, l10n["en"]) for loc in LOCALES}


def _link_salvage(rows: list[dict[str, Any]]) -> None:
    """Point each equipment salvage placeholder at the first material of that line and tier."""
    first: dict[tuple[str, int], str] = {}
    for r in rows:
        if r["kind"] == "material":
            first.setdefault((r["line"], r["data"]["tier"]), r["code"])
    for r in rows:
        for s in r["data"].get("salvage", []):
            line, tier = s["template_code"].split("_t")[0], r["data"]["tier"]
            s["template_code"] = first[(line, tier)]


# --------------------------------------------------------------------------- report helpers
def power(cfg: dict[str, Any], data: dict[str, Any]) -> float:
    w = cfg["stat_weights"]
    return round(sum(float(s["amount"]) * float(w.get(s["stat"], 1.0)) for s in data.get("base_stats", [])), 2)


def outliers(
    cfg: dict[str, Any], rows: list[dict[str, Any]], slot_multipliers: dict[str, float]
) -> list[dict[str, Any]]:
    """Per (category, family, tier): items whose slot-normalized power is outside `outlier_band` × the median."""
    lo, hi = cfg["outlier_band"]
    groups: dict[tuple[str, str, int], list[tuple[str, float]]] = {}
    for r in rows:
        d = r["data"]
        p = power(cfg, d) / slot_multipliers.get(d.get("slot") or "", 1.0)
        if p > 0:
            groups.setdefault((r["kind"], d.get("family") or "", d["tier"]), []).append((r["code"], round(p, 2)))
    out = []
    for (cat, family, tier), items in sorted(groups.items()):
        med = statistics.median(p for _, p in items)
        for code, p in items:
            ratio = p / med if med else 1.0
            if not lo <= ratio <= hi:
                out.append(
                    {"code": code, "category": cat, "family": family, "tier": tier, "power": p, "median": med,
                     "ratio": round(ratio, 2)}
                )  # fmt: skip
    return out


def distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = {loc: Counter(r["l10n"]["name"][loc] for r in rows) for loc in LOCALES}
    return {
        "total": len(rows),
        "by_category": dict(Counter(r["kind"] for r in rows)),
        "by_tier": dict(sorted(Counter(r["data"]["tier"] for r in rows).items())),
        "by_rarity": {
            k: v
            for k, v in sorted(
                Counter(r["data"]["rarity"] for r in rows).items(), key=lambda kv: RARITY_ORDER.index(kv[0])
            )
        },
        "by_class_tag": dict(sorted(Counter(t for r in rows for t in r["data"].get("class_tags", [])).items())),
        "tier_by_category": {
            cat: dict(sorted(Counter(r["data"]["tier"] for r in rows if r["kind"] == cat).items()))
            for cat in dict(Counter(r["kind"] for r in rows))
        },
        "duplicate_names": {loc: sum(1 for c in n.values() if c > 1) for loc, n in names.items()},
        "duplicate_codes": sum(1 for c in Counter(r["code"] for r in rows).values() if c > 1),
    }
