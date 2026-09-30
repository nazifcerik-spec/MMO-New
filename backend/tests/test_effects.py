import pytest

from app.game_engine.effects import EffectValidationError, registry_schema, validate_effect, validate_effects

REQUIRED_TYPES = {
    "STAT_FLAT",
    "STAT_PERCENT",
    "DAMAGE_MULTIPLIER",
    "DAMAGE_REDUCTION",
    "HEAL_MULTIPLIER",
    "SHIELD",
    "RESOURCE_GAIN",
    "PROC_CHANCE",
    "THRESHOLD_TRIGGER",
    "EVERY_N_HITS",
    "DOT",
    "HOT",
    "AURA",
    "DEBUFF",
    "COOLDOWN_MOD",
    "LOOT_MODIFIER",
    "PROFESSION_YIELD_MOD",
}


def test_registry_contains_phase_required_types() -> None:
    codes = {e["effect_type"] for e in registry_schema()}
    assert REQUIRED_TYPES <= codes
    assert all("properties" in e["params_schema"] for e in registry_schema())


def test_valid_nested_effects() -> None:
    validate_effects(
        [
            {"effect_type": "STAT_PERCENT", "params": {"stat": "INT", "percent": 4}},
            {
                "effect_type": "THRESHOLD_TRIGGER",
                "params": {
                    "condition": {"metric": "self_hp_pct", "op": "lt", "value": 35},
                    "effects": [{"effect_type": "DAMAGE_MULTIPLIER", "params": {"percent": 6}}],
                },
            },
            {
                "effect_type": "EVERY_N_HITS",
                "params": {
                    "n": 5,
                    "effects": [{"effect_type": "SHIELD", "params": {"percent_max_hp": 6, "duration_s": 8}}],
                },
            },
        ]
    )


@pytest.mark.parametrize(
    "raw,fragment",
    [
        ({"effect_type": "EXEC_PYTHON", "params": {"code": "import os"}}, "unknown effect_type"),
        (
            {"effect_type": "STAT_FLAT", "schema_version": 9, "params": {"stat": "STR", "amount": 1}},
            "unknown effect_type",
        ),
        ({"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": 1, "script": "x"}}, "Extra inputs"),
        ({"effect_type": "STAT_FLAT", "params": {"stat": "CHARISMA", "amount": 1}}, "unknown stat"),
        (
            {"effect_type": "DOT", "params": {"percent_of_power": 5, "duration_s": 5, "damage_type": "psychic"}},
            "damage type",
        ),
        ({"effect_type": "PROC_CHANCE", "params": {"chance_percent": 150, "effects": []}}, "chance_percent"),
        ({"effect_type": "DAMAGE_REDUCTION", "params": {"percent": 95}}, "percent"),
        ({"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": "1; DROP TABLE users"}}, "amount"),
    ],
)
def test_invalid_effects_rejected(raw: dict, fragment: str) -> None:
    with pytest.raises(EffectValidationError) as ei:
        validate_effect(raw)
    assert fragment.lower() in str(ei.value).lower()


def test_nested_invalid_reports_path() -> None:
    with pytest.raises(EffectValidationError) as ei:
        validate_effect(
            {
                "effect_type": "AURA",
                "params": {"effects": [{"effect_type": "STAT_FLAT", "params": {"stat": "NOPE", "amount": 1}}]},
            }
        )
    assert "params.effects[0]" in ei.value.path


def test_nesting_depth_limited() -> None:
    inner: dict = {"effect_type": "STAT_FLAT", "params": {"stat": "STR", "amount": 1}}
    for _ in range(5):
        inner = {"effect_type": "AURA", "params": {"effects": [inner]}}
    with pytest.raises(EffectValidationError, match="nesting"):
        validate_effect(inner)
