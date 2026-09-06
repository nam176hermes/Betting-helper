import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.governance import validate_authorization_vectors

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")


def _mutable_authorization_vendor(tmp_path: Path) -> Path:
    vendor = tmp_path / "hybrid-discovery-v6.2"
    for relative in (
        "registries/canonical-hash-domains.v1.json",
        "schemas/authorization-records.schema.json",
        "security/trust-root.v1.json",
        "vectors/authorization-v1.json",
    ):
        destination = vendor / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VENDOR / relative, destination)
    return vendor


def _authorization_vectors(vendor: Path) -> dict[str, object]:
    value = json.loads((vendor / "vectors/authorization-v1.json").read_text())
    assert isinstance(value, dict)
    return value


def _write_authorization_vectors(vendor: Path, value: dict[str, object]) -> None:
    (vendor / "vectors/authorization-v1.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def test_rfc8032_vectors_reproduce() -> None:
    validate_authorization_vectors()


def test_signed_vector_test_result_label_is_not_trusted(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    signed = vectors["test_only_signed_record_vectors"]
    assert isinstance(signed, dict)
    cases = signed["vectors"]
    assert isinstance(cases, list)
    case = next(item for item in cases if item["vector_id"] == "GATE_WRONG_ROLE_RESIGNED")
    case["expected_test_result"] = "VALID"
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="GATE_WRONG_ROLE_RESIGNED.*expected_test_result"):
        validate_authorization_vectors(vendor)


def test_signed_vector_active_results_cannot_be_swapped(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    signed = vectors["test_only_signed_record_vectors"]
    assert isinstance(signed, dict)
    cases = signed["vectors"]
    assert isinstance(cases, list)
    valid = next(item for item in cases if item["vector_id"] == "GATERECEIPT_VALID_SIGNATURE")
    invalid = next(
        item
        for item in cases
        if item["vector_id"] == "EXPORT_DESTRUCTION_GATE_WRONG_ROLE_RESIGNED"
    )
    valid["expected_active_result"], invalid["expected_active_result"] = (
        invalid["expected_active_result"],
        valid["expected_active_result"],
    )
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="expected_active_result"):
        validate_authorization_vectors(vendor)


def test_signed_vector_replay_and_revocation_state_is_evaluated(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    signed = vectors["test_only_signed_record_vectors"]
    assert isinstance(signed, dict)
    cases = signed["vectors"]
    assert isinstance(cases, list)
    revoked = next(item for item in cases if item["vector_id"] == "GATE_REVOKED")
    revoked["verification_state"]["revocation_state"]["signed_revocation_records"] = []
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="GATE_REVOKED.*expected_test_result"):
        validate_authorization_vectors(vendor)


def test_test_key_role_membership_is_evaluated(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    trust_path = vendor / "security/trust-root.v1.json"
    trust = json.loads(trust_path.read_text())
    trust["test_only_untrusted_keys"][0]["roles"].remove("PACK_REVIEWER")
    trust_path.write_text(json.dumps(trust, ensure_ascii=False, indent=2) + "\n")

    with pytest.raises(AssertionError, match="role order and membership"):
        validate_authorization_vectors(vendor)


def test_trust_root_rejects_extra_private_key_material(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    trust_path = vendor / "security/trust-root.v1.json"
    trust = json.loads(trust_path.read_text())
    trust["test_only_untrusted_keys"][0]["private_key"] = "SHOULD_BE_REJECTED"
    trust_path.write_text(json.dumps(trust, ensure_ascii=False, indent=2) + "\n")

    with pytest.raises(AssertionError, match="trust root schema invalid"):
        validate_authorization_vectors(vendor)


def test_trust_root_rejects_role_order_and_duplicate_drift(tmp_path: Path) -> None:
    for index, mutation in enumerate(("root-order", "audience-duplicate", "key-order")):
        vendor = _mutable_authorization_vendor(tmp_path / f"case-{index}")
        trust_path = vendor / "security/trust-root.v1.json"
        trust = json.loads(trust_path.read_text())
        if mutation == "root-order":
            trust["trust_roles"].reverse()
        elif mutation == "audience-duplicate":
            trust["audience_role_bindings"][0]["roles"].append("PACK_REVIEWER")
        else:
            trust["test_only_untrusted_keys"][0]["roles"].reverse()
        trust_path.write_text(json.dumps(trust, ensure_ascii=False, indent=2) + "\n")

        with pytest.raises(AssertionError, match="trust root schema invalid|role"):
            validate_authorization_vectors(vendor)


def test_authorization_bundle_rejects_unknown_contract_fields(tmp_path: Path) -> None:
    for index, location in enumerate(("top", "run-vector", "signed-group", "signed-vector")):
        vendor = _mutable_authorization_vendor(tmp_path / f"case-{index}")
        vectors = _authorization_vectors(vendor)
        if location == "top":
            vectors["ignored_contract"] = True
        elif location == "run-vector":
            run_vectors = vectors["vectors"]
            assert isinstance(run_vectors, list)
            run_vector = run_vectors[0]
            assert isinstance(run_vector, dict)
            run_vector["ignored_contract"] = True
        elif location == "signed-group":
            signed = vectors["test_only_signed_record_vectors"]
            assert isinstance(signed, dict)
            signed["ignored_contract"] = True
        else:
            signed = vectors["test_only_signed_record_vectors"]
            assert isinstance(signed, dict)
            signed_vectors = signed["vectors"]
            assert isinstance(signed_vectors, list)
            signed_vector = signed_vectors[0]
            assert isinstance(signed_vector, dict)
            signed_vector["ignored_contract"] = True
        _write_authorization_vectors(vendor, vectors)

        with pytest.raises(AssertionError, match="fields must be exact"):
            validate_authorization_vectors(vendor)


def test_signature_base64url_rejects_noncanonical_pad_bits(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    record = vectors["base_record"]
    assert isinstance(record, dict)
    signature = record["signature"]
    assert isinstance(signature, str)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(signature[-1])
    assert final_index % 4 == 0
    record["signature"] = signature[:-1] + alphabet[final_index + 1]
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="AUTH_VALID.*SIGNATURE_INVALID"):
        validate_authorization_vectors(vendor)


def test_serial_and_nonce_conflicts_are_computed(tmp_path: Path) -> None:
    cases = [
        (
            {
                "issuer": "issuer:rfc8032-test-vector-1",
                "issuer_key_id": (
                    "key:ed25519:21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9"
                ),
                "audience": "hybrid-discovery:bootstrap-gate:v1",
                "scope": "IMPLEMENTATION_GATE_ONLY",
                "serial": "TEST-GATE-0001",
                "nonce": "OTHER-NONCE",
                "content_hash": "0" * 64,
            },
            "SERIAL_CONFLICT",
        ),
        (
            {
                "issuer": "issuer:rfc8032-test-vector-1",
                "issuer_key_id": (
                    "key:ed25519:21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9"
                ),
                "audience": "hybrid-discovery:bootstrap-gate:v1",
                "scope": "IMPLEMENTATION_GATE_ONLY",
                "serial": "OTHER-SERIAL",
                "nonce": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                "content_hash": "0" * 64,
            },
            "LOCAL_STATE_CONFLICT",
        ),
    ]
    for index, (consumed_record, expected_result) in enumerate(cases):
        vendor = _mutable_authorization_vendor(tmp_path / f"case-{index}")
        vectors = _authorization_vectors(vendor)
        signed = vectors["test_only_signed_record_vectors"]
        assert isinstance(signed, dict)
        signed_cases = signed["vectors"]
        assert isinstance(signed_cases, list)
        replay_case = next(
            item
            for item in signed_cases
            if item["vector_id"] == "GATE_SINGLE_USE_REPLAY_RESIGNED"
        )
        consumed_record["scope_binding_hash"] = replay_case["verification_state"][
            "consumed_records"
        ][0]["scope_binding_hash"]
        case = next(
            item
            for item in signed_cases
            if item["vector_id"] == "GATERECEIPT_VALID_SIGNATURE"
        )
        case["verification_state"]["consumed_records"] = [consumed_record]
        case["expected_test_result"] = expected_result
        _write_authorization_vectors(vendor, vectors)

        validate_authorization_vectors(vendor)


def test_clock_outcome_is_computed_from_context_not_declared_faults(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    clock = vectors["clock_lease_contract_and_vectors"]
    assert isinstance(clock, dict)
    cases = clock["vectors"]
    assert isinstance(cases, list)
    case = next(item for item in cases if item["vector_id"] == "CLOCK_BOOT_CHANGED")
    case["faults"] = []
    case["expected_result"] = "VALID"
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="CLOCK_BOOT_CHANGED.*expected_result"):
        validate_authorization_vectors(vendor)


def test_failure_precedence_uses_observed_faults_not_fixture_faults(tmp_path: Path) -> None:
    vendor = _mutable_authorization_vendor(tmp_path)
    vectors = _authorization_vectors(vendor)
    clock = vectors["clock_lease_contract_and_vectors"]
    assert isinstance(clock, dict)
    cases = clock["vectors"]
    assert isinstance(cases, list)
    case = next(
        item
        for item in cases
        if item["vector_id"] == "PRECEDENCE_REVOKED_BEFORE_CLOCK_AND_EXPIRED"
    )
    case["faults"] = ["CLOCK_UNTRUSTED", "EXPIRED"]
    case["expected_result"] = "CLOCK_UNTRUSTED"
    _write_authorization_vectors(vendor, vectors)

    with pytest.raises(AssertionError, match="PRECEDENCE_REVOKED.*expected_result"):
        validate_authorization_vectors(vendor)


def test_all_pack_baseline_build_and_path_bindings_are_evaluated(tmp_path: Path) -> None:
    cases = [
        ("expected_pack_manifest_sha256", "0" * 64, "PACK_HASH_MISMATCH"),
        ("expected_repo0_git_commit_oid", "0" * 40, "BASELINE_MISMATCH"),
        ("expected_repo0_git_tree_oid", "0" * 40, "BASELINE_MISMATCH"),
        ("expected_repo0_tree_sha256", "0" * 64, "BASELINE_MISMATCH"),
        ("expected_dependency_lock_hash", "0" * 64, "BUILD_HASH_MISMATCH"),
        ("expected_schema_vendor_hash", "0" * 64, "BUILD_HASH_MISMATCH"),
        ("expected_pathname", "/different", "SCOPE_BINDING_MISMATCH"),
    ]
    for index, (context_field, replacement, expected_result) in enumerate(cases):
        vendor = _mutable_authorization_vendor(tmp_path / f"case-{index}")
        vectors = _authorization_vectors(vendor)
        run_cases = vectors["vectors"]
        assert isinstance(run_cases, list)
        case = next(item for item in run_cases if item["vector_id"] == "AUTH_VALID")
        case["verification_context"][context_field] = replacement
        case["expected_result"] = expected_result
        _write_authorization_vectors(vendor, vectors)

        validate_authorization_vectors(vendor)
