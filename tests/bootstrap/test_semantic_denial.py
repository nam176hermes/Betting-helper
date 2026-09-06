import ast
import copy
import inspect
import json
import shutil
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

import moj_discovery.universal_denial as denial_module
from moj_discovery.governance import validate_semantic_vector_file
from moj_discovery.universal_denial import (
    SIDE_EFFECT_STAGES,
    DenialReceiptIdentity,
    UniversalDenialContractError,
    UniversalDenialEngine,
    run_synthetic_side_effect_boundary,
    validate_universal_denial_vectors,
)

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")
D0_SCHEMA = "urn:hybrid-discovery:v6.2:d0-evidence:v1"
E0_SCHEMA = "urn:hybrid-discovery:v6.2:e0-evidence:v1"
RECEIPT_SCHEMA = "urn:hybrid-discovery:v6.2:meta-records:v1#UniversalDenialReceipt"
TEST_IDENTITY = DenialReceiptIdentity(
    receipt_id="denial-receipt:9999999999999999999999999999999999999999999999999999999999999999",
    attempt_id="99999999-9999-4999-8999-999999999999",
    input_class="RAW_OBSERVATION",
)


def _vectors(name: str) -> dict[str, object]:
    value = json.loads((VENDOR / "vectors" / name).read_text())
    assert isinstance(value, dict)
    return value


def _valid_record(vector_name: str, case_id: str) -> dict[str, object]:
    data = _vectors(vector_name)
    records: list[object] = []
    for key in ("valid_records", "semantic_bases"):
        collection = data.get(key, [])
        assert isinstance(collection, list)
        records.extend(collection)
    typed_records: list[dict[str, object]] = []
    for entry in records:
        assert isinstance(entry, dict)
        typed_records.append(entry)
    matches = [entry for entry in typed_records if entry["case_id"] == case_id]
    assert len(matches) == 1
    record = matches[0]["record"]
    assert isinstance(record, dict)
    return copy.deepcopy(record)


def _encode(record: object) -> bytes:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()


def _dom_record() -> dict[str, object]:
    return _valid_record("e0-evidence-v1.json", "E0-VALID-DOM-OBSERVATION")


def _provider_call_receipt() -> dict[str, object]:
    return _valid_record("d0-evidence-v1.json", "D0-VALID-PROVIDER-CALL-RECEIPT")


def test_evidence_counterexamples_are_closed() -> None:
    for name in ("e0-evidence-v1.json", "d0-evidence-v1.json"):
        validate_semantic_vector_file(name)


def test_all_declared_universal_denial_vectors_execute() -> None:
    validate_universal_denial_vectors()


@pytest.mark.parametrize(
    ("vector_name", "case_id"),
    [
        ("e0-evidence-v1.json", "E0-REJECT-NOT-OBSERVED-POSITIVE-FACT"),
        ("d0-evidence-v1.json", "D0-REJECT-FEATURES"),
        ("e0-evidence-v1.json", "E0-REJECT-S16-SAME-BOOT"),
        ("d0-evidence-v1.json", "D0-REJECT-LINEAGE-CYCLE"),
    ],
)
def test_evidence_error_label_is_derived_not_trusted(
    tmp_path: Path, vector_name: str, case_id: str
) -> None:
    copied_vendor = tmp_path / "vendor"
    shutil.copytree(VENDOR, copied_vendor)
    vector_path = copied_vendor / "vectors" / vector_name
    vector = json.loads(vector_path.read_text())
    cases = vector["counterexamples"]
    target = next(case for case in cases if case["case_id"] == case_id)
    target["expected_error"] = "E_FAKE_ACCEPTED_WITHOUT_PREDICATE"
    vector_path.write_text(json.dumps(vector, ensure_ascii=False))

    with pytest.raises(AssertionError):
        validate_semantic_vector_file(vector_name, vendor=copied_vendor)


def test_name_stage_precedes_value_entropy_schema_and_side_effects() -> None:
    record = _dom_record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["z_cookie"] = "TEST_ONLY_SECRET_A7z9Q2m5N8v1K4p7R0t3W6y9B2d5F8h1"
    facts["Aauthorization"] = "Input.dispatchMouseEvent"
    observed_effects: list[str] = []

    outcome = run_synthetic_side_effect_boundary(
        UniversalDenialEngine(),
        _encode(record),
        E0_SCHEMA,
        observed_effects.append,
        receipt_identity=TEST_IDENTITY,
    )

    assert outcome.error_code == "E_FORBIDDEN_NAME"
    assert outcome.location_code == "FACTS_AAUTHORIZATION"
    assert outcome.completed_stages == ("DECODE", "SHAPE_SCAN")
    assert observed_effects == []
    assert outcome.receipt is not None
    assert all(outcome.receipt[field] is False for field in _receipt_false_fields())


@pytest.mark.parametrize(
    "command",
    [
        "Runtime.evaluate",
        "DOM.getDocument",
        "Input.dispatchMouseEvent",
        "Fetch.enable",
        "CSS.getComputedStyleForNode",
        "Target.attachToTarget",
        "Page.navigate",
        "Browser.getVersion",
        "Network.setCacheDisabled",
    ],
)
def test_arbitrary_cdp_command_values_are_denied(command: str) -> None:
    record = _dom_record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["command"] = command

    outcome = UniversalDenialEngine().scan(_encode(record), E0_SCHEMA)

    assert outcome.error_code == "E_FORBIDDEN_COMMAND"
    assert outcome.violation_class == "FORBIDDEN_VALUE"
    assert outcome.location_code == "FACTS_COMMAND"


@pytest.mark.parametrize("command", ["Network.enable", "Network.disable"])
def test_exact_allowed_commands_pass_value_scan_only(command: str) -> None:
    record = _dom_record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["command"] = command

    outcome = UniversalDenialEngine().scan(_encode(record), E0_SCHEMA)

    assert outcome.error_code == "E_UNKNOWN_NAME"
    assert outcome.disposition == "QUARANTINED"
    assert "VALUE_SCAN" in outcome.completed_stages


@pytest.mark.parametrize(
    ("raw", "expected_error", "expected_class"),
    [
        (b"\xef\xbb\xbf{}", "E_ENCODING", "ENCODING"),
        (b'{"a":1,"a":2}', "E_DUPLICATE_NAME", "DUPLICATE_NAME"),
        ('{"a":"e\u0301"}'.encode(), "E_NON_NFC", "NORMALIZATION"),
        ('{"a":"\ufffe"}'.encode(), "E_ENCODING", "ENCODING"),
        (b'{"a":"\xff"}', "E_ENCODING", "ENCODING"),
        (b'{"a":1e400}', "E_SHAPE", "SHAPE"),
        (b"[]", "E_SHAPE", "SHAPE"),
    ],
)
def test_decode_and_shape_fail_closed(
    raw: bytes, expected_error: str, expected_class: str
) -> None:
    observed_effects: list[str] = []

    outcome = run_synthetic_side_effect_boundary(
        UniversalDenialEngine(),
        raw,
        D0_SCHEMA,
        observed_effects.append,
        receipt_identity=TEST_IDENTITY,
    )

    assert outcome.error_code == expected_error
    assert outcome.violation_class == expected_class
    assert observed_effects == []
    assert set(outcome.completed_stages).isdisjoint(SIDE_EFFECT_STAGES)


def test_entropy_denial_precedes_unknown_member_and_hash() -> None:
    record = _dom_record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["opaque"] = "TEST_ONLY_SECRET_A7z9Q2m5N8v1K4p7R0t3W6y9B2d5F8h1"

    outcome = UniversalDenialEngine().scan(
        _encode(record), E0_SCHEMA, receipt_identity=TEST_IDENTITY
    )

    assert outcome.error_code == "E_CREDENTIAL_ENTROPY"
    assert outcome.location_code == "FACTS_OPAQUE"
    assert outcome.receipt is not None
    assert outcome.receipt["candidate_bytes_hashed"] is False
    assert "DECLARATION_CHECK" not in outcome.completed_stages


def test_schema_compiled_signature_and_safe_key_identifier_reach_acceptance() -> None:
    record = _provider_call_receipt()

    outcome = UniversalDenialEngine().scan(_encode(record), D0_SCHEMA)

    assert outcome.disposition == "ACCEPTED"
    assert outcome.error_code is None
    assert outcome.completed_stages == (
        "DECODE",
        "SHAPE_SCAN",
        "NAME_SCAN",
        "VALUE_SCAN",
        "ENTROPY_SCAN",
        "DECLARATION_CHECK",
        "SCHEMA_VALIDATE",
    )


def test_safe_key_identifier_requires_exact_declaring_path_and_value() -> None:
    engine = UniversalDenialEngine()
    wrong_value = _provider_call_receipt()
    protocol = wrong_value["provider_probe_protocol"]
    assert isinstance(protocol, dict)
    protocol["issuer_key_id"] = "key:ed25519:not-valid"
    wrong_path = _provider_call_receipt()
    wrong_path["issuer_key_id"] = (
        "key:ed25519:21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9"
    )

    first = engine.scan(_encode(wrong_value), D0_SCHEMA)
    second = engine.scan(_encode(wrong_path), D0_SCHEMA)

    assert (first.error_code, first.location_code) == (
        "E_FORBIDDEN_NAME",
        "PROVIDER_PROBE_PROTOCOL_ISSUER_KEY_ID",
    )
    assert (second.error_code, second.location_code) == (
        "E_FORBIDDEN_NAME",
        "ROOT_ISSUER_KEY_ID",
    )


def test_schema_validation_uses_format_checker() -> None:
    record = _provider_call_receipt()
    record["scheduled_at"] = "2030-99-99T25:61:61Z"

    outcome = UniversalDenialEngine().scan(_encode(record), D0_SCHEMA)

    assert outcome.error_code == "E_CLOSED_SCHEMA_VIOLATION"
    assert outcome.completed_stages[-1] == "SCHEMA_VALIDATE"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_bytes_hashed", True),
        ("attempt_id", "not-a-uuid"),
        ("unexpected", False),
    ],
)
def test_denial_receipt_schema_rejects_mutation(field: str, value: object) -> None:
    record = _dom_record()
    facts = record["facts"]
    assert isinstance(facts, dict)
    facts["cookie"] = "never-record-this"
    engine = UniversalDenialEngine()
    outcome = engine.scan(_encode(record), E0_SCHEMA, receipt_identity=TEST_IDENTITY)
    assert outcome.receipt is not None
    mutated = copy.deepcopy(outcome.receipt)
    mutated[field] = value

    with pytest.raises(ValidationError):
        engine.validate_schema(mutated, RECEIPT_SCHEMA)


def test_forbidden_registry_removal_is_fail_closed_drift(tmp_path: Path) -> None:
    copied_vendor = tmp_path / "vendor"
    shutil.copytree(VENDOR, copied_vendor)
    meta_path = copied_vendor / "schemas/meta-records.schema.json"
    meta = json.loads(meta_path.read_text())
    forbidden = meta["x-universal-forbidden-registry"]
    forbidden["forbidden_name_fragments"].remove("cookie")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))

    with pytest.raises(
        UniversalDenialContractError, match="E_UNIVERSAL_DENIAL_POLICY_DRIFT"
    ):
        UniversalDenialEngine(copied_vendor)


def test_public_scanner_has_no_fault_control_or_side_effect_primitive() -> None:
    signature = inspect.signature(UniversalDenialEngine.scan)
    assert "fault" not in signature.parameters
    tree = ast.parse(inspect.getsource(denial_module))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported_roots.isdisjoint(
        {"hashlib", "logging", "sqlite3", "socket", "urllib", "requests", "httpx"}
    )
    forbidden_calls = {
        "hash",
        "open",
        "write",
        "write_text",
        "write_bytes",
        "execute",
        "connect",
    }
    scan_methods = {
        "_scan",
        "_name_scan",
        "_value_scan",
        "_entropy_scan",
        "_declaration_check",
        "_denied",
    }
    called: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or node.name not in scan_methods
        ):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    called.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    called.add(child.func.attr)
    assert called.isdisjoint(forbidden_calls)


def _receipt_false_fields() -> tuple[str, ...]:
    return (
        "matched_bytes_recorded",
        "candidate_bytes_hashed",
        "sanitized_record_projected",
        "artifact_written",
        "log_written",
        "indexeddb_written",
        "sqlite_written",
        "fixture_emitted",
        "report_emitted",
        "replay_artifact_emitted",
        "export_emitted",
    )
