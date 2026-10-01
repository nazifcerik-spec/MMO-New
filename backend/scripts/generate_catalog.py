"""Launch catalog CLI: dry-run report (default), or --commit [--publish] into the configured database.

python -m scripts.generate_catalog                 # validate + write docs/content/ITEM_CATALOG_REPORT.md
python -m scripts.generate_catalog --commit --publish
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.db.session import get_sessionmaker
from app.services import catalog, plugins  # noqa: F401  (registers content types)

REPORT = Path(__file__).resolve().parents[2] / "docs" / "content" / "ITEM_CATALOG_REPORT.md"


async def main(commit: bool, publish: bool) -> int:
    async with get_sessionmaker()() as db:
        summary = await catalog.dry_run(db)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(catalog.report_markdown(summary), encoding="utf-8")
        print(json.dumps({k: summary[k] for k in ("matches_targets", "errors", "warnings", "issue_codes")}, indent=1))
        if summary["errors"]:
            return 1
        if commit:
            print(json.dumps(await catalog.commit(db, publish=publish, actor_id=None))[:400])
            await db.commit()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.commit, a.publish)))
