import copy
import json
from pathlib import Path

import pytest

from moj_discovery.vendor import plan_root
from tools.verify_proof_coverage import verify_proof_coverage_matrix

ROOT = Path(__file__).parents[2]
PLAN = plan_root(ROOT)


def test_every_promised_control_has_mechanical_proof() -> None:
    matrix = json.loads((PLAN / "docs/registries/proof-coverage-matrix.v1.json").read_text())
    assert verify_proof_coverage_matrix(matrix) == {"result": "PASS", "control_count": 18}
    changed = copy.deepcopy(matrix)
    changed["entries"][0]["test_file"] = ""
    with pytest.raises(ValueError, match="E_PROOF_COVERAGE"):
        verify_proof_coverage_matrix(changed)


def test_current_stage_cannot_pass_without_complete_validation_inputs() -> None:
    matrix = json.loads((PLAN / "docs/registries/proof-coverage-matrix.v1.json").read_text())
    with pytest.raises(ValueError, match="E_PROOF_COVERAGE"):
        verify_proof_coverage_matrix(matrix, stage="CANDIDATE")
    with pytest.raises(ValueError, match="E_PROOF_COVERAGE"):
        verify_proof_coverage_matrix(matrix, Path("/missing"), "CANDIDATE")
