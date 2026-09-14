import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location(
        "one_ready", ROOT / "authoring-tools/prepare_one_ready_inputs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_amendment_is_explicit_and_preserves_historical_commands():
    m = tool()
    original = m.predecessor(ROOT)
    built = m.build(original)
    registry = "pack/docs/registries/task-command-registry.v1.json"
    before = json.loads(original[registry])["commands"]
    after = json.loads(built[registry])["commands"]
    for row in before:
        if row["command_id"] in {"VERIFY_V636_MIG0_T06", "ISSUE_V636_P00_T05"}:
            assert next(r for r in after if r["command_id"] == row["command_id"]) == row
    assert {r["command_id"] for r in after} - {r["command_id"] for r in before} == {
        "VALIDATE_CURRENT_DECLARATION", "VALIDATE_CURRENT_DESCENDANT_MIGRATION", "ISSUE_CURRENT_PHASE_PROOFS"
    }
    contract = json.loads(built[m.CONTRACT])
    assert contract["adopted_source"]["qualification"] == "NOT_INFERRED"
    assert contract["production_authority"] == "NONE"
    assert "runtime/src/moj_discovery/canonical.py" in contract["approved_files"]
    assert len(contract["phases"]) == 9
    assert not any("receipt" in name for name in built)
    owned = {row["path"] for row in json.loads(built["pack/docs/registries/artifact-ownership.v1.json"])["entries"]}
    assert "pack/BOOTSTRAP.md" in owned
    logs = {path for path in owned if path.startswith(m.EVIDENCE + "/command-logs/")}
    assert len(logs) == 104
    tasks = json.loads(built["pack/docs/tasks/task-manifest.v6.3.6.json"])["tasks"]
    retention = next(t for t in tasks if t["task_id"] == "V636-P09-T01")["inputs"]
    assert logs | {m.EVIDENCE + "/CURRENT_INPUTS.json"} <= set(retention)
    command_io = json.loads(built["pack/docs/registries/command-io.v1.json"])["commands"]
    assembly = next(row for row in command_io if row["command_id"] == "VERIFY_V636_P09_T01")
    assert set(retention) <= set(assembly["inputs"])
    assert m.EVIDENCE + "/bootstrap/authoring-repository-receipt.json" not in assembly["inputs"]
    assert m.EVIDENCE + "/bootstrap/authoring-repository-receipt.json" not in retention
    assert m.EVIDENCE + "/bootstrap/authoring-repository-receipt-descendant-source-v2.json" in retention
    assert "/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json" in retention
    assert "runtime/vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json" in owned


def test_materialization_rejects_unknown_bytes_and_parent_alias(tmp_path):
    m = tool()
    original = m.predecessor(ROOT)
    built = m.build(original)
    for name, data in original.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    m.materialize(tmp_path, original, built)
    m.materialize(tmp_path, original, built)
    p = tmp_path / m.CONTRACT
    p.write_text("{}")
    with pytest.raises(ValueError, match="E_ONE_READY_DRIFT"):
        m.materialize(tmp_path, original, built)
    assert p.read_text() == "{}"


def test_current_migration_and_review_references_name_actual_producers():
    m = tool()
    docs = m.build(m.predecessor(ROOT))
    tasks = json.loads(docs["pack/docs/tasks/task-manifest.v6.3.6.json"])["tasks"]
    migration = next(t for t in tasks if t["task_id"] == "V636-MIG0-T08")
    obsolete = {
        m.EVIDENCE + "/bootstrap/authoring-repository-receipt.json",
        m.EVIDENCE + "/bootstrap/authoring-repository-receipt-descendant-source-v1.json",
    }
    assert not obsolete.intersection(migration["outputs"] + migration["exact_files"])
    assert m.EVIDENCE + "/bootstrap/authoring-repository-receipt-descendant-source-v2.json" in migration["outputs"]
    release = next(t for t in tasks if t["task_id"] == "V636-P05-T09")
    assert "runtime/tests/release/test_descendant_repository_qualification.py::test_descendant_uses_actual_eighteen_requirement_matrix" in release["exact_symbols"]
    assert "runtime/tests/release/test_descendant_repository_qualification.py::test_descendant_record_recursively_validates_full_and_supplemental_proofs" in release["exact_symbols"]


@pytest.mark.parametrize("ordinal", range(1, 5))
def test_sealing_uses_the_qualified_evidence_producer_python(ordinal):
    m = tool()
    original = m.predecessor(ROOT)
    registry = "pack/docs/registries/task-command-registry.v1.json"
    command_id = f"VERIFY_V636_P09_T0{ordinal}"
    before = next(row for row in json.loads(original[registry])["commands"]
                  if row["command_id"] == command_id)
    after = next(row for row in json.loads(m.build(original)[registry])["commands"]
                 if row["command_id"] == command_id)
    assert after["argv"][:5] == ["uv", "run", "--frozen", "--offline", "python"]
    assert after["argv"][5:] == [token.replace(m.OLD_EVIDENCE, m.EVIDENCE)
                                 .replace(m.OLD_REVIEW_HOST + "/", m.REVIEW_HOST + "/")
                                 for token in before["argv"][1:]]
    assert after["cwd"] == m.RUNTIME
    assert after["network"] == after["provider_access"] == "DENY"


def test_current_host_launch_paths_preserve_legacy_and_reject_other_roots():
    m = tool()
    original = m.predecessor(ROOT)
    built = m.build(original)
    name = "pack/docs/schemas/review-launch-authorization.schema.json"
    before = json.loads(original[name])["$defs"]
    after = json.loads(built[name])["$defs"]
    assert after["LegacyReviewLaunchAuthorization"] == before["LegacyReviewLaunchAuthorization"]
    props = after["DescendantReviewLaunchAuthorization"]["properties"]
    for field, config_field in (("workspace_root", "workspace_root"), ("allowed_output_root", "output_root")):
        validator = Draft202012Validator(props[field])
        for role in ("a", "b"):
            config = json.loads((ROOT / f"pack/docs/configs/review-{role}.v2.json").read_bytes())
            assert validator.is_valid(config[config_field])
            for bad in (config[config_field] + "/escape", config[config_field] + "/../review-a", "/tmp/review-a"):
                assert not validator.is_valid(bad)


def test_current_security_scope_preserves_vectors_and_declares_both_compiler_owners():
    m = tool()
    original = m.predecessor(ROOT)
    built = m.build(original)
    inherited = "pack/docs/registries/inherited-baseline-qualification.v1.json"
    before, after = json.loads(original[inherited]), json.loads(built[inherited])
    changed = next(row for row in after["typescript_files"] if row["path"].endswith("capability-reachability.bootstrap.test.ts"))
    assert changed["modification_owner"] == "V636-P05-T09"
    changed["modification_owner"] = None
    for path in ("runtime/tests/bootstrap/test_capability_reachability.py",
                 "runtime/tests/bootstrap/test_schema_format_checker.py"):
        row = next(row for row in after["python_files"] if row["path"] == path)
        assert row["modification_owner"] == "V636-P05-T09"
        row["modification_owner"] = None
    row = next(row for row in after["source_consumers"]
               if row["path"] == "runtime/src/moj_discovery/governance.py")
    assert row["modification_owners"].pop() == "V636-P05-T09"
    assert row["qualification_owner"] == "V636-P05-T09"
    row["qualification_owner"] = "V636-P05-T02"
    assert before == after  # All named tests, source hashes and vector modes remain intact.
    contract = json.loads(built[m.CONTRACT])
    assert contract["security_surface_contract"] == m.SECURITY_CONTRACT
    assert "STATIC_PACKAGE_BOUNDARY_ONLY" in built[m.SECURITY_CONTRACT].decode()
    source = "runtime/extension/test/security/current-surface.ts"
    compiled = "runtime/extension/.test-build/test/security/current-surface.js"
    owned = {row["path"]: row for row in json.loads(built["pack/docs/registries/artifact-ownership.v1.json"])["entries"]}
    assert owned[compiled]["source"] == {"path": source}
    assert owned[compiled]["creation_owner"] == "V636-P04-T03"
    for path in (source, compiled):
        assert owned[path]["modifying_tasks"] == ["V636-P05-T09"]
        assert owned[path]["qualification_owner"] == "V636-P05-T09"
    commands = {row["command_id"]: row for row in json.loads(built["pack/docs/registries/command-io.v1.json"])["commands"]}
    for command in ("COMPILE_V636_P04_T03", "COMPILE_ALL_TESTS"):
        assert source in commands[command]["inputs"]
        assert compiled in commands[command]["outputs"]
    for command in ("TEST_SECURITY_TS", "QUALIFY_INHERITED_BOOTSTRAP_TS", "QUALIFY_INHERITED_BOOTSTRAP_PY"):
        assert {compiled, m.SECURITY_CONTRACT, "runtime/tools/verify_live_package.py", "runtime/contracts/live_readonly/v1/package-policy.json"} <= set(commands[command]["inputs"])


def test_current_delivery_preserves_old_host_and_declares_verification_repair():
    m = tool()
    built = m.build(m.predecessor(ROOT))
    for role in ("a", "b"):
        cfg = json.loads(built[f"pack/docs/configs/review-{role}.v2.json"])
        assert cfg["workspace_root"] == m.REVIEW_HOST + f"/workspaces/review-{role}"
        assert cfg["output_root"] == m.REVIEW_HOST + f"/results/review-{role}"
        assert all(m.OLD_REVIEW_HOST + "/" not in value for value in cfg["input_roots"])
        assert cfg["network"] == "DENY"
    approved = json.loads(built[m.CONTRACT])["approved_files"]
    for path in ("tools/verify_repair_evidence.py", "tools/verify_full_repair_qualification.py",
                 "tests/repairs/test_clock_validation_batch.py"):
        assert "runtime/" + path in approved


def test_eight_hour_scoped_launch_preserves_legacy_expiry():
    m = tool()
    original = m.predecessor(ROOT)
    built = m.build(original)
    key = "pack/docs/schemas/review-launch-authorization.schema.json"
    old = json.loads(original[key])["$defs"]
    new = json.loads(built[key])["$defs"]
    assert new["LegacyReviewLaunchAuthorization"] == old["LegacyReviewLaunchAuthorization"]
    field = new["DescendantReviewLaunchAuthorization"]["properties"]["maximum_duration_seconds"]
    check = Draft202012Validator(field)
    assert check.is_valid(14400) and check.is_valid(28800)
    for bad in [True, 0, 14401, 28801, 57600]:
        assert not check.is_valid(bad)
    cfg = json.loads(built["pack/docs/configs/review-aggregation.v2.json"])
    assert cfg["maximum_launch_age_seconds"] == 28800
    assert cfg["maximum_aggregate_delay_seconds"] == 3600
    amendment = json.loads(built[m.CONTRACT])["scoped_review"]["lifetime_amendment"]
    assert amendment["new_v3_launch_seconds"] == 28800
    assert amendment["existing_authorizations_extended"] is False


def test_review_repair_registers_bootstrap_collection_and_dependency_regressions():
    m = tool()
    built = m.build(m.predecessor(ROOT))
    cfg = json.loads(built["pack/docs/configs/full-verifier-controller.v2.json"])
    assert m.AUTHORING + "/plan-input/bootstrap/test_bootstrap_tools.py" in cfg["external_authoring_command"]["argv"]
    registry = json.loads(built["pack/docs/registries/task-command-registry.v1.json"])["commands"]
    command = next(row for row in registry if row["command_id"] == "TEST_V636_P05_T05")
    assert "tests/review/test_descendant_namespace_projection.py" in command["argv"]
