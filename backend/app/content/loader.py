"""Load canonical content data files (YAML) shipped with the backend."""

from functools import cache
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).parent / "data"


@cache
def load_yaml(relative: str) -> Any:
    with (DATA_DIR / relative).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def iter_yaml(subdir: str) -> list[tuple[str, Any]]:
    folder = DATA_DIR / subdir
    return [(p.name, load_yaml(f"{subdir}/{p.name}")) for p in sorted(folder.glob("*.yaml"))]
