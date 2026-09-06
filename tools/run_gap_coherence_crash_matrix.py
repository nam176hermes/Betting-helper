"""Run every registered GAP_GENERATION_COHERENCE vector in a killable child."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.run_loopback_ack_crash_matrix import run_family


def run_gap_coherence_crash_matrix(
    pack: Path,
    workspace: Path,
    *,
    observation_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_family(pack, workspace, "GAP_GENERATION_COHERENCE", observation_input)
