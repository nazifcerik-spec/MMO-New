import pytest
import yaml

from app.content.loader import DATA_DIR
from app.game_engine import progression as prog
from app.game_engine.stat_calculator import Contribution, compute_stat_sheet, contribution_from_effects


@pytest.fixture(scope="module")
def cfg() -> prog.ProgressionConfig:
    raw = yaml.safe_load((DATA_DIR / "balance/progression.yaml").read_text())["data"]
    return prog.ProgressionConfig.model_validate(raw)


def test_canonical_constants(cfg: prog.ProgressionConfig) -> None:
    assert cfg.level_cap == 1000
    assert cfg.stat_points_per_level == 3
    assert cfg.breakpoints == [100, 300, 600, 850, 1000]
    assert prog.total_points_for_level(cfg, 1000) == 2997
    assert [t.code for t in cfg.titles] == [
        "novice",
        "veteran",
        "seasoned",
        "elite",
        "heroic",
        "legendary",
        "champion",
        "mythic",
        "ancient",
        "ascendant",
        "immortal",
        "exalted",
        "eternal",
    ]


def test_xp_curve_matches_968_hour_target(cfg: prog.ProgressionConfig) -> None:
    hours = sum(prog.hours_for_level(s, lv) for s in cfg.xp_curve.segments for lv in range(s.from_level, s.to_level))
    assert hours == pytest.approx(968, abs=0.01)
    seg_hours = {
        (s.from_level, s.to_level): sum(prog.hours_for_level(s, lv) for lv in range(s.from_level, s.to_level))
        for s in cfg.xp_curve.segments
    }
    assert seg_hours[(1, 100)] == pytest.approx(8) and seg_hours[(900, 1000)] == pytest.approx(233)
    t = cfg.xp_table
    assert all(t[i] <= t[i + 1] for i in range(1, 999)), "XP per level must be non-decreasing"
    assert prog.xp_to_next(cfg, 1000) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 0),
        (300, 300),
        (301, 300.7),
        (600, 510),
        (700, 555),
        (900, 645),
        (1000, 670),
    ],
)
def test_soft_caps(cfg: prog.ProgressionConfig, raw: float, expected: float) -> None:
    assert prog.effective_stat(cfg, raw) == pytest.approx(expected)


def test_multi_level_gain_and_breakpoints(cfg: prog.ProgressionConfig) -> None:
    need = sum(cfg.xp_table[1:301])
    r = prog.apply_xp(cfg, 1, 0, need + 5)
    assert (r.level, r.xp, r.levels_gained, r.stat_points_gained) == (301, 5, 300, 900)
    assert r.breakpoints_crossed == (100, 300)


def test_hard_cap_1000(cfg: prog.ProgressionConfig) -> None:
    r = prog.apply_xp(cfg, 999, 0, cfg.xp_table[999] + 12345)
    assert r.level == 1000 and r.xp == 0 and r.overflow_xp == 12345
    r2 = prog.apply_xp(cfg, 1000, 0, 500)
    assert r2.level == 1000 and r2.levels_gained == 0 and r2.overflow_xp == 500
    with pytest.raises(ValueError):
        prog.apply_xp(cfg, 1, 0, -1)


def test_titles_and_next_breakpoint(cfg: prog.ProgressionConfig) -> None:
    assert prog.title_for_level(cfg, 1) == "novice"
    assert prog.title_for_level(cfg, 849) == "ancient"
    assert prog.title_for_level(cfg, 850) == "ascendant"
    assert prog.title_for_level(cfg, 1000) == "eternal"
    assert prog.next_breakpoint(cfg, 300) == 600
    assert prog.next_breakpoint(cfg, 1000) is None


def test_distribution_is_exact_and_deterministic() -> None:
    w = prog.resolve_profile_weights(
        {"VIT": 45, "main": 30, "utility": 15, "LUK": 10}, {"main": "STR", "utility": "DEX"}
    )
    a = prog.distribute_points(37, w)
    assert sum(a.values()) == 37 and a == prog.distribute_points(37, w)
    split = prog.resolve_profile_weights({"main": 50, "DEX|LUK": 25}, {"main": "DEX"})
    assert split["DEX"] == pytest.approx(62.5) and split["LUK"] == pytest.approx(12.5)
    with pytest.raises(ValueError):
        prog.resolve_profile_weights({"main": 1}, {})


def test_respec_cost_bands_and_discount(cfg: prog.ProgressionConfig) -> None:
    assert prog.respec_cost(cfg, 50, 100) == 0
    assert prog.respec_cost(cfg, 150, 100) == 200
    assert prog.respec_cost(cfg, 450, 100) == 2000
    assert prog.respec_cost(cfg, 700, 100) == 12000
    # Human-style discount on the first 300 points only
    assert prog.respec_cost(cfg, 700, 400, discount_percent=50, discount_limit_points=300) == 100 * 120 + 300 * 60


def test_stat_sheet_breakdown_by_source(cfg: prog.ProgressionConfig) -> None:
    race = contribution_from_effects(
        "race",
        "dwarf",
        [
            {"effect_type": "STAT_PERCENT", "params": {"stat": "VIT", "percent": 5}},
            {"effect_type": "STAT_PERCENT", "params": {"stat": "block_efficiency", "percent": 5}},
            {"effect_type": "DAMAGE_MULTIPLIER", "params": {"percent": 6}},  # combat-time; ignored here
        ],
    )
    gear = Contribution("equipment", "iron_helm", flat={"VIT": 20, "armor": 50})
    sheet = compute_stat_sheet(cfg, 10, [Contribution("allocated", "allocated", {"VIT": 27}), race, gear])
    vit = sheet.primary["VIT"]
    assert vit.raw == 5 + 27 + 20 and vit.final == pytest.approx(52 * 1.05)
    assert [b["source"] for b in vit.breakdown] == ["base", "race", "allocated", "equipment"]
    hp = cfg.derived["max_hp"]
    expected_hp = hp.base + hp.per_level * 10 + 14 * vit.final + 2 * sheet.primary["STR"].final
    assert sheet.value("max_hp") == pytest.approx(expected_hp)
    assert sheet.derived["armor"].breakdown[-1]["source"] == "equipment"
    with pytest.raises(ValueError):
        compute_stat_sheet(cfg, 1, [Contribution("hacked", "x")])


def test_derived_caps(cfg: prog.ProgressionConfig) -> None:
    sheet = compute_stat_sheet(cfg, 1, [Contribution("buff", "x", percent={"dodge": 5000})])
    assert sheet.value("dodge") == cfg.caps["dodge"]
