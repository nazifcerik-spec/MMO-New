"""Balance simulator / checker CLI (runs in a rolled-back sandbox; never changes data).

python -m scripts.simulate --class warrior --level 120 --iterations 5 [--spec iron_bastion] [--csv out.csv]
python -m scripts.simulate --check --level 100 --sections support racial items
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.db.session import dispose_engine, get_sessionmaker
from app.services import (
    plugins,  # noqa: F401
    simulator,
)


async def main(a: argparse.Namespace) -> dict:  # type: ignore[type-arg]
    async with get_sessionmaker()() as db:
        if a.check:
            out = await simulator.check(db, level=a.level, sections=tuple(a.sections), fights=a.fights)
        else:
            params = simulator.SimParams(
                level=a.level, base_class=a.cls, race=a.race, specialization=a.spec, talent_build=a.talents,
                gear_tier=a.gear_tier, gear_budget_pct=a.gear_budget, zone=a.zone, risk=a.risk, duration_s=a.duration,
                iterations=a.iterations, fights=a.fights or 10, seed=a.seed, profession_node=a.node,
            )  # fmt: skip
            out = await simulator.run(db, params)
        await db.rollback()
    await dispose_engine()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sections", nargs="+", default=["support", "racial", "items"])
    ap.add_argument("--level", type=int, default=100)
    ap.add_argument("--class", dest="cls", default="warrior")
    ap.add_argument("--race", default="human")
    ap.add_argument("--spec")
    ap.add_argument("--talents", default="auto")
    ap.add_argument("--gear-tier", type=int)
    ap.add_argument("--gear-budget", type=float, default=100)
    ap.add_argument("--zone")
    ap.add_argument("--risk", default="balanced")
    ap.add_argument("--duration", type=int, default=10800)
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--fights", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--node")
    ap.add_argument("--csv")
    args = ap.parse_args()
    result = asyncio.run(main(args))
    if args.csv and not args.check:
        Path(args.csv).write_text(simulator.to_csv(result), encoding="utf-8")
    print(json.dumps(result, indent=1, default=str))
