import copy
import json
from pathlib import Path
from typing import Any

import pytest

from moj_discovery.vendor import plan_root
from tests.seal.test_self_review_binding import current_chain as current_chain
from tests.seal.test_self_review_binding import descendant_pack as descendant_pack
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


def test_sealed_stage_reads_authenticated_named_deliveries(descendant_pack: dict[str, Any]) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    matrix = json.loads((pack / "docs/registries/proof-coverage-matrix.v1.json").read_bytes())
    result = verify_proof_coverage_matrix(
        matrix,
        pack / "evidence",
        "SEALED",
        chain["copied_config"],
        artifacts=chain["artifacts"],
    )
    assert result["result"] == "PASS" and result["control_count"] == 18
    assert len(result["evidence"]) == 16
    assert all(Path(row["path"]).is_relative_to(pack / "evidence") for row in result["evidence"])


def test_registered_sealed_proof_argv_uses_copied_context(
    descendant_pack: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.seal.test_deterministic_seal import _current_self_review, _seal_current
    from tools import verify_proof_coverage as proof

    chain, pack = descendant_pack, descendant_pack["pack"]
    _current_self_review(chain)
    _attestation, paths = _seal_current(chain)
    registry = json.loads((pack / "docs/registries/review-command-registry.v1.json").read_bytes())
    row = next(row for row in registry["commands"] if row["command_id"] == "A_CHECK_EVIDENCE")
    argv = row["argv"][5:]
    values = {
        "--matrix": pack / "docs/registries/proof-coverage-matrix.v1.json",
        "--evidence-root": pack / "evidence",
        "--config": pack / "docs/configs/full-verifier-controller.v2.json",
        "--recorded-config": chain["config"].source_path,
        "--retained-manifest": pack / "evidence/retained-artifact-manifest.json",
        "--retained-root": pack / "evidence/retained",
        "--zip": paths[0],
        "--sidecar": paths[1],
        "--attestation": paths[2],
    }
    for flag, value in values.items():
        argv[argv.index(flag) + 1] = str(value)
    monkeypatch.setattr("sys.argv", argv)
    proof.main()
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "PASS" and len(result["evidence"]) == 16
    for flag in (
        "--config",
        "--recorded-config",
        "--retained-manifest",
        "--retained-root",
        "--zip",
        "--sidecar",
        "--attestation",
    ):
        incomplete = list(argv)
        index = incomplete.index(flag)
        del incomplete[index : index + 2]
        output = chain["directory"] / "must-not-exist.json"
        monkeypatch.setattr("sys.argv", [*incomplete, "--output", str(output)])
        with pytest.raises(ValueError, match="^E_PROOF_COVERAGE$"):
            proof.main()
        assert not output.exists()


def test_sealed_proof_rejects_unbound_matrix_and_named_copy_tamper(
    descendant_pack: dict[str, Any],
) -> None:
    chain, pack = descendant_pack, descendant_pack["pack"]
    matrix = json.loads((pack / "docs/registries/proof-coverage-matrix.v1.json").read_bytes())
    changed = copy.deepcopy(matrix)
    next(entry for entry in changed["entries"] if entry["stage"] == "CANDIDATE")["stage"] = "SEALED"
    assert changed != matrix
    with pytest.raises(ValueError, match="^E_PROOF_COVERAGE$"):
        verify_proof_coverage_matrix(
            changed,
            pack / "evidence",
            "SEALED",
            chain["copied_config"],
            artifacts=chain["artifacts"],
        )
    entry = next(entry for entry in matrix["entries"] if entry["stage"] == "CANDIDATE")
    path = pack / entry["sealed_evidence_path"]
    raw = path.read_bytes()
    for damage in ("changed", "missing"):
        if damage == "changed":
            path.write_bytes(raw + b"\n")
        else:
            path.unlink()
        try:
            with pytest.raises(ValueError, match="^E_PROOF_COVERAGE$"):
                verify_proof_coverage_matrix(
                    matrix,
                    pack / "evidence",
                    "SEALED",
                    chain["copied_config"],
                    artifacts=chain["artifacts"],
                )
        finally:
            path.write_bytes(raw)
