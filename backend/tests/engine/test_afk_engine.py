"""Phase 13: player-day efficiency slicing (pure)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.content.loader import load_yaml
from app.game_engine.afk import AfkBalance, day_slices, efficiency_at, efficiency_segments, over_level_pct, used_by_day

CFG = AfkBalance.model_validate(load_yaml("balance/afk.yaml")["data"])
H = 3600


def _pcts(segs):  # type: ignore[no-untyped-def]
    return [(round((s.end_s - s.start_s) / H, 3), s.percent) for s in segs]


def test_fresh_day_is_full_efficiency() -> None:
    start = datetime(2026, 5, 1, 10, tzinfo=UTC)
    assert _pcts(efficiency_segments(CFG, start, 3 * H, {})) == [(3.0, 100)]


def test_band_crossing_is_sliced() -> None:
    start = datetime(2026, 5, 1, 10, tzinfo=UTC)
    day = start.date()
    assert _pcts(efficiency_segments(CFG, start, 3 * H, {day: 8 * H})) == [(1.0, 100), (2.0, 80)]
    assert _pcts(efficiency_segments(CFG, start, 3 * H, {day: 11.5 * H})) == [(0.5, 80), (2.5, 50)]
    assert _pcts(efficiency_segments(CFG, start, 3 * H, {day: 23 * H})) == [(1.0, 25), (2.0, 25)]


def test_player_day_boundary_resets_bands() -> None:
    start = datetime(2026, 5, 1, 23, tzinfo=UTC)
    segs = efficiency_segments(CFG, start, 3 * H, {start.date(): 11 * H})
    assert _pcts(segs) == [(1.0, 80), (2.0, 100)]
    assert [d for d, _ in day_slices(CFG, start, 3 * H)] == [start.date(), datetime(2026, 5, 2).date()]
    assert efficiency_at(segs, 0) == 80 and efficiency_at(segs, 1.5 * H) == 100
    used = used_by_day(segs, 1.5 * H)
    assert used == {start.date(): H, datetime(2026, 5, 2).date(): 0.5 * H}


def test_three_hour_cap_is_schema_enforced() -> None:
    with pytest.raises(ValidationError):
        AfkBalance.model_validate({**CFG.model_dump(), "max_session_seconds": 10_801})


def test_over_level_penalty() -> None:
    assert over_level_pct(CFG, 60, 49) == 100
    assert over_level_pct(CFG, 80, 49) == 100 - 11 * 3
    assert over_level_pct(CFG, 900, 49) == CFG.over_level.min_pct
