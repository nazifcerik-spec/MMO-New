"""Atomically mark a phase complete in .claude/state.json. Usage: phase_done.py <phase> <next|done> [check...]"""

import json
import os
import sys
import tempfile
from datetime import UTC, datetime

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "state.json")
phase, nxt, *checks = sys.argv[1:]
state = json.load(open(path))
if phase not in state["completed_phases"]:
    state["completed_phases"].append(phase)
state["current_phase"] = nxt
state["last_quality_gate"] = {"phase": phase, "result": "pass", "checks": checks}
state["last_updated_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f:
    json.dump(state, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
print(f"phase {phase} done -> {nxt}")
