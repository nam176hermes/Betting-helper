import pytest

from tools.verify_proof_coverage import verify_proof_coverage_matrix


def test_every_proof_matrix_row_has_passing_evidence() -> None:
    row = {
        "requirement_id": "R1", "implementation_symbol": "module.py::symbol",
        "test_file": "tests/test_module.py", "vector_ids": ["V1"], "command_id": "TEST_R1",
        "evidence_artifact": "evidence/R1.json", "release_gate": "CANDIDATE",
        "stage": "CANDIDATE", "evidence_owner": "V636-P07-T01",
        "verification_kind": "EXECUTED_RUNTIME_EVIDENCE",
    }
    matrix = {"entries": [{**row, "requirement_id": f"R{index}"} for index in range(18)]}
    assert verify_proof_coverage_matrix(matrix)["control_count"] == 18
    matrix["entries"][0]["vector_ids"] = []
    with pytest.raises(ValueError, match="E_PROOF_COVERAGE"):
        verify_proof_coverage_matrix(matrix)
