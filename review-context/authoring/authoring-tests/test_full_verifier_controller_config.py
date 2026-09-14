from __future__ import annotations

import json
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "pack/docs/configs/full-verifier-controller.v1.json"


def test_full_verifier_controller_binding_is_complete_and_normative() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert set(config) == {
        "schema_version",
        "production_authority",
        "accepted_authoring_ancestor",
        "current_checkout_root",
        "governed_source_pack",
        "evidence_root",
        "external_authoring_tests",
        "external_authoring_source_sha256",
        "external_authoring_command",
        "uv_cache",
        "pnpm_store",
        "chrome",
        "receipts",
    }
    assert config["schema_version"] == "full-verifier-controller/v1"
    assert config["production_authority"] == "NONE"
    assert re.fullmatch(r"[0-9a-f]{40}", config["accepted_authoring_ancestor"])
    assert set(config["chrome"]) == {"path", "sha256"}
    assert re.fullmatch(r"[0-9a-f]{64}", config["chrome"]["sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", config["external_authoring_source_sha256"])
    assert set(config["external_authoring_command"]) == {"cwd", "argv"}
    assert config["external_authoring_command"]["argv"][5] == "--offline"
    assert "--confcutdir" in config["external_authoring_command"]["argv"]
    argv = config["external_authoring_command"]["argv"]
    python_index = argv.index("python")
    assert argv[python_index + 1 : python_index + 3] == ["-I", "-B"]
    assert argv[argv.index("-c") + 1] == "/dev/null"
    assert set(config["receipts"]) == {
        "authoring_repository",
        "candidate_command_evidence",
        "proof_coverage_evidence",
        "candidate_issuance_evidence",
        "candidate_qualification",
    }
    assert all(Path(value).is_absolute() for value in (
        config["current_checkout_root"],
        config["governed_source_pack"],
        config["evidence_root"],
        config["external_authoring_tests"],
        config["external_authoring_command"]["cwd"],
        config["uv_cache"],
        config["pnpm_store"],
        config["chrome"]["path"],
        *config["receipts"].values(),
    ))
    # The legacy v1 locator remains bound to its historical source pack.
    spec = importlib.util.spec_from_file_location("part_b_inputs", ROOT / "authoring-tools/prepare_part_b_review_inputs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert CONFIG_PATH.read_bytes() == module.predecessor(ROOT)["pack/docs/configs/full-verifier-controller.v1.json"]
    current = json.loads((ROOT / "pack/docs/configs/full-verifier-controller.v2.json").read_text())
    assert Path(current["governed_source_pack"]).resolve() == (ROOT / "pack").resolve()
    assert all(
        Path(value).is_relative_to(Path(config["evidence_root"]))
        for value in config["receipts"].values()
    )

    mapping = json.loads(
        (ROOT / "pack/docs/registries/normative-source-map.v1.json").read_text(
            encoding="utf-8"
        )
    )
    pairs = {
        (entry["plan_source"], entry["vendor_relative"])
        for entry in mapping["plan_entries"]
    }
    relative = "docs/configs/full-verifier-controller.v1.json"
    assert (relative, relative) in pairs


def test_candidate_receipt_lifecycle_is_acyclic() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    receipts = config["receipts"]
    assert receipts["candidate_command_evidence"] != receipts["candidate_qualification"]
    assert Path(receipts["authoring_repository"]).name == (
        "authoring-repository-receipt.json"
    )
