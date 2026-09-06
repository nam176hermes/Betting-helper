"""Bootstrap-only semantic verification for the sealed authorization vectors.

This module verifies contract fixtures.  It does not expose an authorization or
discovery runtime entry point, mutate a consumption ledger, or confer authority.
"""

from __future__ import annotations

import base64
import copy
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .canonical import CanonicalError, canonical_content_hash, parse_strict_json
from .schema_formats import STRICT_FORMAT_CHECKER

JsonObject = dict[str, Any]

SIGNATURE_DOMAIN = b"HYBRID-DISCOVERY/v6.2/SIGNATURE/Ed25519/v1\0"
TEST_TRUST_MODE = "RFC8032_TEST_KEY_TEMPORARILY_TRUSTED_FOR_MECHANISM_TEST_ONLY"
ACTIVE_TRUST_MODE = "ACTIVE_TRUST_ROOT"

TOP_LEVEL_FIELDS = {
    "schema_version",
    "trust",
    "canonical_algorithm",
    "signature_algorithm",
    "signature_domain",
    "hash_domain",
    "excluded_json_pointers",
    "rfc8032_test_vector_1",
    "test_only_signed_record_vectors",
    "recovered_approved_compatibility_vector",
    "base_record",
    "failure_precedence",
    "clock_lease_contract_and_vectors",
    "vectors",
    "production_authority",
}

RUN_VECTOR_IDS = (
    "AUTH_VALID",
    "AUTH_FORGED_SIGNATURE",
    "AUTH_EXPIRED",
    "AUTH_REPLAYED",
    "AUTH_REVOKED",
    "AUTH_WRONG_AUDIENCE_RESIGNED",
    "AUTH_WRONG_BUILD_RESIGNED",
    "AUTH_WRONG_ORIGIN_RESIGNED",
    "AUTH_WRONG_TAB_RESIGNED",
    "AUTH_WRONG_DOCUMENT_RESIGNED",
    "AUTH_PREREQUISITE_MISSING",
    "AUTH_PREREQUISITE_SWAPPED",
    "AUTH_PREREQUISITE_FORGED",
)

SIGNED_VECTOR_IDS = (
    "GATERECEIPT_VALID_SIGNATURE",
    "BODYCLASSAPPROVAL_VALID_SIGNATURE",
    "PROVIDERPROBEPROTOCOL_VALID_SIGNATURE",
    "PROVIDERCALLAUTHORIZATION_VALID_SIGNATURE",
    "REVOCATIONRECORD_VALID_SIGNATURE",
    "GATE_WRONG_ROLE_RESIGNED",
    "GATE_WRONG_AUDIENCE_RESIGNED",
    "GATE_WRONG_PACK_BINDING_RESIGNED",
    "GATE_SINGLE_USE_REPLAY_RESIGNED",
    "GATE_REVOKED",
    "EXPORT_DESTRUCTION_GATE_VALID_SIGNATURE",
    "EXPORT_DESTRUCTION_GATE_WRONG_RUN_RESIGNED",
    "EXPORT_DESTRUCTION_GATE_WRONG_EXPORT_HASH_RESIGNED",
    "EXPORT_DESTRUCTION_GATE_REPLAY",
    "EXPORT_DESTRUCTION_GATE_WRONG_ROLE_RESIGNED",
    "EXPORT_DESTRUCTION_GATE_WRONG_AUDIENCE_RESIGNED",
    "BODY_WRONG_ROLE_RESIGNED",
    "BODY_WRONG_AUDIENCE_RESIGNED",
    "BODY_WRONG_TAB_BINDING_RESIGNED",
    "BODY_REPLAYED",
    "BODY_REVOKED",
    "PROTOCOL_WRONG_ROLE_RESIGNED",
    "PROTOCOL_WRONG_AUDIENCE_RESIGNED",
    "PROTOCOL_WRONG_ENDPOINT_BINDING_RESIGNED",
    "PROTOCOL_REUSE_ALLOWED",
    "PROTOCOL_REVOKED",
    "CALL_WRONG_ROLE_RESIGNED",
    "CALL_WRONG_AUDIENCE_RESIGNED",
    "CALL_WRONG_PROTOCOL_BINDING_RESIGNED",
    "CALL_REPLAYED",
    "CALL_REVOKED",
    "REVOCATION_WRONG_ROLE_RESIGNED",
    "REVOCATION_WRONG_AUDIENCE_RESIGNED",
    "REVOCATION_CHAIN_BINDING_RESIGNED",
    "REVOCATION_SEQUENCE_CONFLICT_RESIGNED",
)

CLOCK_VECTOR_IDS = (
    "CLOCK_VALID_CONTROL",
    "CLOCK_BOOT_CHANGED",
    "CLOCK_BACKEND_RESTARTED",
    "CLOCK_WALL_ROLLBACK",
    "CLOCK_MONOTONIC_REGRESSION",
    "CLOCK_EVIDENCE_MISSING",
    "CLOCK_MONOTONIC_EXPIRED",
    "CLOCK_NOT_YET_VALID",
    "PRECEDENCE_REVOKED_BEFORE_CLOCK_AND_EXPIRED",
    "PRECEDENCE_CLOCK_BEFORE_NOT_YET_AND_CONSUMED",
    "PRECEDENCE_SIGNATURE_BEFORE_BUILD_AND_EXPIRED",
    "PRECEDENCE_UNTRUSTED_KEY_BEFORE_AUDIENCE_AND_EXPIRED",
)

FAILURE_PRECEDENCE = (
    "MALFORMED_UTF8_OR_JSON",
    "DUPLICATE_JSON_KEY",
    "SCHEMA_INVALID",
    "NON_NFC_OR_INVALID_UNICODE",
    "UNSUPPORTED_VERSION_OR_ALGORITHM",
    "CONTENT_HASH_MISMATCH",
    "UNTRUSTED_KEY_ID",
    "KEY_ROLE_OR_ISSUANCE_INVALID",
    "SIGNATURE_INVALID",
    "PACK_HASH_MISMATCH",
    "BASELINE_MISMATCH",
    "BUILD_HASH_MISMATCH",
    "AUDIENCE_MISMATCH",
    "REVOKED",
    "CLOCK_UNTRUSTED",
    "NOT_YET_VALID",
    "EXPIRED",
    "PREREQUISITE_GATE_INVALID",
    "SCOPE_BINDING_MISMATCH",
    "CONSUMPTION_STORE_UNAVAILABLE",
    "ALREADY_CONSUMED",
    "SERIAL_CONFLICT",
    "LOCAL_STATE_CONFLICT",
)

ALLOWED_ROLES = {
    "GateReceipt": frozenset({"PACK_REVIEWER"}),
    "DiscoveryRunAuthorization": frozenset({"DISCOVERY_OPERATOR"}),
    "BodyClassApproval": frozenset({"DISCOVERY_OPERATOR"}),
    "ProviderProbeProtocol": frozenset({"PACK_REVIEWER", "PROVIDER_OPERATOR"}),
    "ProviderCallAuthorization": frozenset({"PROVIDER_OPERATOR"}),
    "RevocationRecord": frozenset({"REVOCATION_AUTHORITY"}),
}

EXPECTED_AUDIENCE = {
    "GateReceipt": "hybrid-discovery:bootstrap-gate:v1",
    "DiscoveryRunAuthorization": "hybrid-discovery:extension-run-controller:v1",
    "BodyClassApproval": "hybrid-discovery:body-broker:v1",
    "ProviderProbeProtocol": "hybrid-discovery:provider-protocol:v1",
    "ProviderCallAuthorization": "hybrid-discovery:provider-client:v1",
    "RevocationRecord": "hybrid-discovery:revocation-ledger:v1",
}

TRUST_ROLES = (
    "PACK_REVIEWER",
    "DISCOVERY_OPERATOR",
    "PROVIDER_OPERATOR",
    "REVOCATION_AUTHORITY",
)

AUDIENCE_ROLE_BINDINGS = (
    ("hybrid-discovery:bootstrap-gate:v1", ("PACK_REVIEWER",)),
    ("hybrid-discovery:extension-run-controller:v1", ("DISCOVERY_OPERATOR",)),
    ("hybrid-discovery:body-broker:v1", ("DISCOVERY_OPERATOR",)),
    (
        "hybrid-discovery:provider-protocol:v1",
        ("PACK_REVIEWER", "PROVIDER_OPERATOR"),
    ),
    ("hybrid-discovery:provider-client:v1", ("PROVIDER_OPERATOR",)),
    ("hybrid-discovery:revocation-ledger:v1", ("REVOCATION_AUTHORITY",)),
)

BROWSER_FIELDS = (
    "browser_id",
    "profile_id",
    "browser_run_id",
    "window_id",
    "tab_id",
    "tab_instance_id",
    "document_id",
    "navigation_id",
    "origin",
    "pathname",
)


@dataclass(frozen=True)
class _VerifierKey:
    key_id: str
    public_key: Ed25519PublicKey
    issuers: frozenset[str]
    roles: frozenset[str]
    audiences: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    active: bool
    test_only: bool


@dataclass(frozen=True)
class _Evaluation:
    result: str
    faults: frozenset[str]


def validate_authorization_semantics(vendor: Path) -> None:
    """Recompute every authorization-vector outcome from sealed inputs."""

    vectors = _as_object(
        parse_strict_json((vendor / "vectors/authorization-v1.json").read_bytes()),
        "authorization vectors",
    )
    schema = _as_object(
        parse_strict_json(
            (vendor / "schemas/authorization-records.schema.json").read_bytes()
        ),
        "authorization schema",
    )
    trust = _as_object(
        parse_strict_json((vendor / "security/trust-root.v1.json").read_bytes()),
        "trust root",
    )
    _validate_bundle_shape(vectors)
    validator = Draft202012Validator(schema, format_checker=STRICT_FORMAT_CHECKER)
    assert next(validator.iter_errors(trust), None) is None, "trust root schema invalid"
    keys = _load_and_validate_trust_root(
        trust, _as_object(vectors["rfc8032_test_vector_1"], "RFC vector")
    )
    _validate_bundle_contract(vectors, trust)

    run_reference = _as_object(vectors["base_record"], "base_record")
    for vector_value in _as_list(vectors["vectors"], "vectors"):
        vector = _as_object(vector_value, "run vector")
        record = _apply_mutations(
            run_reference,
            _as_list(vector["mutations"], "run vector mutations"),
        )
        evaluation = _evaluate_record(
            record=record,
            reference=run_reference,
            context=_as_object(vector["verification_context"], "verification_context"),
            trust_mode=TEST_TRUST_MODE,
            keys=keys,
            validator=validator,
            vendor=vendor,
        )
        _assert_result(vector, "expected_result", evaluation.result)

    signed = _as_object(
        vectors["test_only_signed_record_vectors"], "test_only_signed_record_vectors"
    )
    base_records = _as_object(signed["base_records"], "signed base_records")
    for vector_value in _as_list(signed["vectors"], "signed vectors"):
        vector = _as_object(vector_value, "signed vector")
        vector_id = _as_string(vector["vector_id"], "vector_id")
        base_name = _as_string(vector["base_record"], f"{vector_id}.base_record")
        reference = _as_object(base_records[base_name], f"{vector_id}.reference")
        record = _apply_mutations(
            reference,
            _as_list(vector["mutations"], f"{vector_id}.mutations"),
        )
        state = _as_object(vector["verification_state"], f"{vector_id}.verification_state")
        test_evaluation = _evaluate_record(
            record=record,
            reference=reference,
            context=_signed_vector_context(reference, state),
            trust_mode=_as_string(vector["test_trust_mode"], f"{vector_id}.test_trust_mode"),
            keys=keys,
            validator=validator,
            vendor=vendor,
        )
        _assert_result(vector, "expected_test_result", test_evaluation.result)
        active_evaluation = _evaluate_record(
            record=record,
            reference=reference,
            context=_signed_vector_context(reference, state),
            trust_mode=ACTIVE_TRUST_MODE,
            keys=keys,
            validator=validator,
            vendor=vendor,
        )
        _assert_result(vector, "expected_active_result", active_evaluation.result)

    clock_group = _as_object(
        vectors["clock_lease_contract_and_vectors"], "clock_lease_contract_and_vectors"
    )
    for vector_value in _as_list(clock_group["vectors"], "clock vectors"):
        vector = _as_object(vector_value, "clock vector")
        record = _apply_mutations(
            run_reference,
            _as_list(vector["record_mutations"], "clock record_mutations"),
        )
        evaluation = _evaluate_record(
            record=record,
            reference=run_reference,
            context=_as_object(vector["verification_context"], "clock verification_context"),
            trust_mode=_as_string(vector["verification_mode"], "verification_mode"),
            keys=keys,
            validator=validator,
            vendor=vendor,
        )
        _assert_result(vector, "expected_result", evaluation.result)
        declared_faults = frozenset(
            _as_string(item, "clock fault") for item in _as_list(vector["faults"], "faults")
        )
        assert evaluation.faults == declared_faults, (
            f"{vector['vector_id']}:faults declared={sorted(declared_faults)!r} "
            f"computed={sorted(evaluation.faults)!r}"
        )


def _validate_bundle_contract(vectors: JsonObject, trust: JsonObject) -> None:
    assert vectors["schema_version"] == "authorization-vectors/v1"
    assert vectors["trust"] == "TEST_ONLY_UNTRUSTED"
    assert vectors["canonical_algorithm"] == "HD-JCS-SHA256-v1"
    assert vectors["signature_algorithm"] == "Ed25519"
    assert vectors["signature_domain"] == SIGNATURE_DOMAIN.decode()
    assert vectors["excluded_json_pointers"] == ["/content_hash", "/signature"]
    assert tuple(_as_list(vectors["failure_precedence"], "failure_precedence")) == (
        FAILURE_PRECEDENCE
    )
    assert vectors["production_authority"] == "NONE"
    assert trust["production_authority"] == "NONE"


def _validate_bundle_shape(vectors: JsonObject) -> None:
    assert set(vectors) == TOP_LEVEL_FIELDS, "authorization top-level fields must be exact"
    assert set(_as_object(vectors["rfc8032_test_vector_1"], "RFC vector")) == {
        "trust",
        "seed_hex",
        "public_key_hex",
        "public_key_unpadded_base64url",
        "key_id",
        "empty_message_signature_hex",
    }, "RFC vector fields must be exact"
    signed = _as_object(
        vectors["test_only_signed_record_vectors"], "test_only_signed_record_vectors"
    )
    assert set(signed) == {
        "classification",
        "signature_algorithm",
        "signature_domain",
        "hash_rule",
        "active_trust_invariant",
        "base_records",
        "vectors",
    }, "signed group fields must be exact"
    assert tuple(_as_object(signed["base_records"], "base_records")) == (
        "GateReceipt",
        "EvidenceExportAcceptedGateReceipt",
        "BodyClassApproval",
        "ProviderProbeProtocol",
        "ProviderCallAuthorization",
        "RevocationRecord",
    ), "signed base-record keys must be exact"

    run_vectors = [
        _as_object(value, "run vector") for value in _as_list(vectors["vectors"], "vectors")
    ]
    assert tuple(value.get("vector_id") for value in run_vectors) == RUN_VECTOR_IDS, (
        "run vector IDs and order must be exact"
    )
    for vector in run_vectors:
        assert set(vector) == {
            "vector_id",
            "base_record",
            "mutations",
            "verification_context",
            "expected_result",
        }, "run vector fields must be exact"

    signed_vectors = [
        _as_object(value, "signed vector")
        for value in _as_list(signed["vectors"], "signed vectors")
    ]
    assert tuple(value.get("vector_id") for value in signed_vectors) == SIGNED_VECTOR_IDS, (
        "signed vector IDs and order must be exact"
    )
    signed_fields = {
        "vector_id",
        "base_record",
        "mutations",
        "test_trust_mode",
        "verification_state",
        "expected_test_result",
        "expected_active_result",
    }
    for vector in signed_vectors:
        actual = set(vector)
        assert actual == signed_fields or actual == signed_fields | {
            "failure_precedence_outcome"
        }, "signed vector fields must be exact"

    clock = _as_object(
        vectors["clock_lease_contract_and_vectors"], "clock_lease_contract_and_vectors"
    )
    assert set(clock) == {"context_schema", "vectors"}, "clock group fields must be exact"
    clock_vectors = [
        _as_object(value, "clock vector")
        for value in _as_list(clock["vectors"], "clock vectors")
    ]
    assert tuple(value.get("vector_id") for value in clock_vectors) == CLOCK_VECTOR_IDS, (
        "clock vector IDs and order must be exact"
    )
    for vector in clock_vectors:
        assert set(vector) == {
            "vector_id",
            "base_record",
            "record_mutations",
            "verification_mode",
            "verification_context",
            "faults",
            "expected_result",
        }, "clock vector fields must be exact"


def _load_and_validate_trust_root(
    trust: JsonObject, rfc_vector: JsonObject
) -> dict[str, _VerifierKey]:
    assert set(trust) == {
        "schema_version",
        "signature_algorithm",
        "public_key_encoding",
        "key_id_derivation",
        "signature_domain",
        "runtime_key_material",
        "signing_key_custody",
        "trust_roles",
        "audience_role_bindings",
        "trusted_keys",
        "test_only_untrusted_keys",
        "production_authority",
    }, "trust root fields must be exact"
    assert trust["schema_version"] == "trust-root/v1"
    assert trust["signature_algorithm"] == "Ed25519"
    assert trust["public_key_encoding"] == (
        "RAW_32_BYTES_UNPADDED_BASE64URL_CANONICAL_REENCODE_REQUIRED"
    )
    assert trust["key_id_derivation"] == "key:ed25519:<sha256-lowercase-hex-of-raw-public-key>"
    assert trust["signature_domain"] == SIGNATURE_DOMAIN.decode()
    assert trust["runtime_key_material"] == "VERIFIER_PUBLIC_KEYS_ONLY"
    assert trust["signing_key_custody"] == "USER_SCOPED_OS_BACKED_OUTSIDE_PACK_AND_RUNTIME"
    assert tuple(_as_list(trust["trust_roles"], "trust_roles")) == TRUST_ROLES, (
        "trust role order and membership must be exact"
    )
    actual_audience_roles: list[tuple[str, tuple[object, ...]]] = []
    for value in _as_list(trust["audience_role_bindings"], "audience_role_bindings"):
        binding = _as_object(value, "audience role binding")
        assert set(binding) == {"audience", "roles"}, "audience binding fields must be exact"
        audience = _as_string(binding["audience"], "audience")
        actual_audience_roles.append(
            (
                audience,
                tuple(
                    _as_string(role, "role")
                    for role in _as_list(binding["roles"], "roles")
                ),
            )
        )
    assert tuple(actual_audience_roles) == AUDIENCE_ROLE_BINDINGS, (
        "audience role order and membership must be exact"
    )

    active_values = _as_list(trust["trusted_keys"], "trusted_keys")
    # v6.2 authoring is deliberately fail-closed: no production root is provisioned.
    assert active_values == []
    keys: dict[str, _VerifierKey] = {}
    assert rfc_vector["trust"] == "TEST_ONLY_UNTRUSTED"
    assert rfc_vector["seed_hex"] == (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    )
    rfc_public_bytes = bytes.fromhex(_as_string(rfc_vector["public_key_hex"], "RFC public key"))
    assert len(rfc_public_bytes) == 32
    assert rfc_vector["public_key_unpadded_base64url"] == base64.urlsafe_b64encode(
        rfc_public_bytes
    ).rstrip(b"=").decode("ascii")
    rfc_key_id = "key:ed25519:" + hashlib.sha256(rfc_public_bytes).hexdigest()
    assert rfc_vector["key_id"] == rfc_key_id
    rfc_public_key = Ed25519PublicKey.from_public_bytes(rfc_public_bytes)
    rfc_signature = bytes.fromhex(
        _as_string(rfc_vector["empty_message_signature_hex"], "RFC signature")
    )
    assert len(rfc_signature) == 64
    rfc_public_key.verify(rfc_signature, b"")
    for value in _as_list(trust["test_only_untrusted_keys"], "test_only_untrusted_keys"):
        entry = _as_object(value, "test key")
        assert set(entry) == {
            "label",
            "trust",
            "status",
            "issuers",
            "roles",
            "audiences",
            "valid_from",
            "valid_until",
            "key_id",
            "public_key",
        }, "test key fields must be exact"
        assert entry["trust"] == "TEST_ONLY_UNTRUSTED"
        assert entry["status"] == "TEST_ONLY_DISABLED"
        assert entry["label"] == "RFC8032_TEST_VECTOR_1"
        assert tuple(_as_list(entry["issuers"], "test key issuers")) == (
            "issuer:rfc8032-test-vector-1",
        )
        assert tuple(_as_list(entry["roles"], "test key roles")) == TRUST_ROLES, (
            "test key role order and membership must be exact"
        )
        assert tuple(_as_list(entry["audiences"], "test key audiences")) == tuple(
            audience for audience, _roles in AUDIENCE_ROLE_BINDINGS
        ), "test key audience order and membership must be exact"
        valid_from = _instant(entry["valid_from"])
        valid_until = _instant(entry["valid_until"])
        assert valid_from < valid_until, "test key validity interval must be ordered"
        raw_key = _decode_base64url(_as_string(entry["public_key"], "public_key"), 32)
        key_id = "key:ed25519:" + hashlib.sha256(raw_key).hexdigest()
        assert entry["key_id"] == key_id
        assert raw_key == rfc_public_bytes and key_id == rfc_key_id
        assert key_id not in keys
        keys[key_id] = _VerifierKey(
            key_id=key_id,
            public_key=Ed25519PublicKey.from_public_bytes(raw_key),
            issuers=frozenset(
                _as_string(issuer, "test key issuer")
                for issuer in _as_list(entry["issuers"], "test key issuers")
            ),
            roles=frozenset(
                _as_string(role, "test key role")
                for role in _as_list(entry["roles"], "test key roles")
            ),
            audiences=frozenset(
                _as_string(audience, "test key audience")
                for audience in _as_list(entry["audiences"], "test key audiences")
            ),
            valid_from=valid_from,
            valid_until=valid_until,
            active=False,
            test_only=True,
        )
    assert len(keys) == 1
    return keys


def _evaluate_record(
    *,
    record: JsonObject,
    reference: JsonObject,
    context: JsonObject,
    trust_mode: str,
    keys: dict[str, _VerifierKey],
    validator: Draft202012Validator,
    vendor: Path,
) -> _Evaluation:
    if next(validator.iter_errors(record), None) is not None:
        return _evaluation({"SCHEMA_INVALID"})

    faults: set[str] = set()
    record_type = _as_string(record["record_type"], "record_type")
    try:
        computed_hash = canonical_content_hash(
            record_type,
            record,
            registry_path=vendor / "registries/canonical-hash-domains.v1.json",
        )
    except CanonicalError as error:
        code = str(error)
        faults.add(code if code in FAILURE_PRECEDENCE else "UNSUPPORTED_VERSION_OR_ALGORITHM")
        return _evaluation(faults)
    if computed_hash != record["content_hash"]:
        faults.add("CONTENT_HASH_MISMATCH")

    key_id = _as_string(record["issuer_key_id"], "issuer_key_id")
    key = keys.get(key_id)
    trusted = key is not None and (
        (trust_mode == TEST_TRUST_MODE and key.test_only)
        or (trust_mode == ACTIVE_TRUST_MODE and key.active)
    )
    if trust_mode not in {TEST_TRUST_MODE, ACTIVE_TRUST_MODE}:
        faults.add("KEY_ROLE_OR_ISSUANCE_INVALID")
    if not trusted:
        faults.add("UNTRUSTED_KEY_ID")

    allowed_roles = ALLOWED_ROLES[record_type]
    issuer_role = _as_string(record["issuer_role"], "issuer_role")
    issued_at = _instant(record["issued_at"])
    if (
        key is None
        or issuer_role not in allowed_roles
        or issuer_role not in key.roles
        or record["issuer"] not in key.issuers
        or record["issuer"] != reference["issuer"]
        or record["audience"] not in key.audiences
        or not key.valid_from <= issued_at <= key.valid_until
        or not _issuance_order_is_valid(record)
    ):
        faults.add("KEY_ROLE_OR_ISSUANCE_INVALID")

    if key is not None and not _signature_is_valid(record, key.public_key):
        faults.add("SIGNATURE_INVALID")

    expected_pack = copy.deepcopy(_as_object(reference["pack_bindings"], "pack bindings"))
    _overlay_expected(
        expected_pack,
        context,
        {
            "final_pack_zip_sha256": "expected_pack_zip_sha256",
            "pack_manifest_sha256": "expected_pack_manifest_sha256",
            "repo0_baseline_receipt_sha256": "expected_repo0_baseline_receipt_sha256",
            "repo0_git_commit_oid": "expected_repo0_git_commit_oid",
            "repo0_git_tree_oid": "expected_repo0_git_tree_oid",
            "repo0_tree_sha256": "expected_repo0_tree_sha256",
        },
    )
    actual_pack = _as_object(record["pack_bindings"], "pack bindings")
    if any(
        actual_pack[field] != expected_pack[field]
        for field in ("final_pack_zip_sha256", "pack_manifest_sha256")
    ):
        faults.add("PACK_HASH_MISMATCH")
    if any(
        actual_pack[field] != expected_pack[field]
        for field in (
            "repo0_baseline_receipt_sha256",
            "repo0_git_commit_oid",
            "repo0_git_tree_oid",
            "repo0_tree_sha256",
        )
    ):
        faults.add("BASELINE_MISMATCH")

    expected_implementation = copy.deepcopy(
        _as_object(reference["implementation_bindings"], "implementation bindings")
    )
    _overlay_expected(
        expected_implementation,
        context,
        {
            "implementation_build_hash": "expected_implementation_build_hash",
            "dependency_lock_hash": "expected_dependency_lock_hash",
            "schema_vendor_hash": "expected_schema_vendor_hash",
        },
    )
    if record["implementation_bindings"] != expected_implementation:
        faults.add("BUILD_HASH_MISMATCH")

    expected_audience = context.get("expected_audience", EXPECTED_AUDIENCE[record_type])
    if record["audience"] != expected_audience or record["audience"] != EXPECTED_AUDIENCE[
        record_type
    ]:
        faults.add("AUDIENCE_MISMATCH")

    now = _validation_time(record, context)
    revoked, revocation_valid = _is_revoked(
        record, context, now, trust_mode, keys, validator, vendor
    )
    if revoked:
        faults.add("REVOKED")
    if not revocation_valid:
        faults.add("LOCAL_STATE_CONFLICT")
    _add_clock_and_time_faults(faults, record, context, now)
    _add_prerequisite_faults(
        faults, record, reference, context, now, trust_mode, keys, validator, vendor
    )
    _add_scope_faults(
        faults, record, reference, context, now, trust_mode, keys, validator, vendor
    )

    if context.get("consumption_store_available", True) is not True:
        faults.add("CONSUMPTION_STORE_UNAVAILABLE")
    _add_consumption_faults(faults, record, context)
    _add_serial_and_local_state_faults(faults, record, reference, context)
    return _evaluation(faults)


def _issuance_order_is_valid(record: JsonObject) -> bool:
    issued = _instant(record["issued_at"])
    not_before = _instant(record["not_before"])
    expires = _instant(record["expires_at"])
    return issued <= not_before < expires


def _signature_is_valid(record: JsonObject, key: Ed25519PublicKey) -> bool:
    try:
        signature = _decode_base64url(_as_string(record["signature"], "signature"), 64)
        content_hash = bytes.fromhex(_as_string(record["content_hash"], "content_hash"))
        key.verify(signature, SIGNATURE_DOMAIN + content_hash)
    except (InvalidSignature, ValueError):
        return False
    return True


def _validation_time(record: JsonObject, context: JsonObject) -> datetime:
    value = context.get("validation_time", record["not_before"])
    return _instant(value)


def _is_revoked(
    record: JsonObject,
    context: JsonObject,
    now: datetime,
    trust_mode: str,
    keys: dict[str, _VerifierKey],
    validator: Draft202012Validator,
    vendor: Path,
) -> tuple[bool, bool]:
    state_value = context.get("revocation_state")
    if not isinstance(state_value, dict) or set(state_value) != {
        "required_revocation_checkpoint",
        "signed_revocation_records",
    }:
        return False, False
    state = cast(JsonObject, state_value)
    required = _as_object(
        state["required_revocation_checkpoint"], "required revocation checkpoint"
    )
    signed_checkpoint = _as_object(record["revocation_checkpoint"], "signed checkpoint")
    if set(required) != {"ledger_id", "sequence", "head_hash"}:
        return False, False
    if required["ledger_id"] != signed_checkpoint["ledger_id"]:
        return False, False
    try:
        signed_sequence = int(_as_string(signed_checkpoint["sequence"], "signed sequence"))
        required_sequence = int(_as_string(required["sequence"], "required sequence"))
    except (AssertionError, ValueError):
        return False, False
    if signed_sequence != 0 or required_sequence < signed_sequence:
        return False, False
    ledger_id = _as_string(required["ledger_id"], "ledger_id")
    genesis = hashlib.sha256(
        b"HYBRID-DISCOVERY/v6.2/REVOCATION-LEDGER-GENESIS/v1\0"
        + ledger_id.encode("ascii")
    ).hexdigest()
    if signed_checkpoint["head_hash"] != genesis:
        return False, False
    records = _as_list(state["signed_revocation_records"], "signed revocation records")
    if len(records) != required_sequence:
        return False, False
    previous_hash = genesis
    revoked = False
    for sequence, value in enumerate(records, 1):
        candidate = _as_object(value, "signed revocation record")
        checkpoint = candidate.get("revocation_checkpoint")
        if not isinstance(checkpoint, dict):
            return False, False
        expected_previous = None if sequence == 1 else previous_hash
        if (
            candidate.get("record_type") != "RevocationRecord"
            or candidate.get("ledger_id") != ledger_id
            or candidate.get("revocation_sequence") != str(sequence)
            or candidate.get("previous_revocation_hash") != expected_previous
            or checkpoint
            != {
                "ledger_id": ledger_id,
                "sequence": str(sequence - 1),
                "head_hash": previous_hash,
            }
            or candidate.get("pack_bindings") != record.get("pack_bindings")
            or candidate.get("implementation_bindings")
            != record.get("implementation_bindings")
            or not _record_mechanism_valid(
                candidate, trust_mode, keys, validator, vendor
            )
        ):
            return False, False
        previous_hash = _as_string(candidate["content_hash"], "revocation content hash")
        if _instant(candidate["effective_at"]) <= now and (
            candidate.get("revoked_content_hash") == record.get("content_hash")
            or candidate.get("revoked_serial") == record.get("serial")
            or candidate.get("revoked_key_id") == record.get("issuer_key_id")
        ):
            revoked = True
    if required["head_hash"] != previous_hash:
        return False, False
    return revoked, True


def _record_mechanism_valid(
    record: JsonObject,
    trust_mode: str,
    keys: dict[str, _VerifierKey],
    validator: Draft202012Validator,
    vendor: Path,
) -> bool:
    if next(validator.iter_errors(record), None) is not None:
        return False
    try:
        record_type = _as_string(record["record_type"], "record type")
        digest = canonical_content_hash(
            record_type,
            record,
            registry_path=vendor / "registries/canonical-hash-domains.v1.json",
        )
        key = keys.get(_as_string(record["issuer_key_id"], "key id"))
        issued = _instant(record["issued_at"])
        role = _as_string(record["issuer_role"], "issuer role")
        audience = _as_string(record["audience"], "audience")
    except (AssertionError, CanonicalError, KeyError, ValueError):
        return False
    trusted = key is not None and (
        (trust_mode == TEST_TRUST_MODE and key.test_only)
        or (trust_mode == ACTIVE_TRUST_MODE and key.active)
    )
    if key is None:
        return False
    return bool(
        trusted
        and digest == record.get("content_hash")
        and role in ALLOWED_ROLES.get(record_type, frozenset())
        and role in key.roles
        and record.get("issuer") in key.issuers
        and audience in key.audiences
        and audience == EXPECTED_AUDIENCE.get(record_type)
        and key.valid_from <= issued <= key.valid_until
        and _issuance_order_is_valid(record)
        and _signature_is_valid(record, key.public_key)
    )


def _add_clock_and_time_faults(
    faults: set[str], record: JsonObject, context: JsonObject, now: datetime
) -> None:
    if record["record_type"] in {
        "DiscoveryRunAuthorization",
        "ProviderCallAuthorization",
    }:
        clock = _as_object(record["verifier_clock"], "verifier_clock")
        start = _as_object(clock["monotonic_start"], "monotonic start")
        deadline = _as_object(clock["monotonic_deadline"], "monotonic deadline")
        wall = _as_object(clock["trusted_wall_anchor"], "trusted wall anchor")
        current_value = context.get("current_monotonic")
        current = cast(JsonObject, current_value) if isinstance(current_value, dict) else None
        required_clock_context = {
            "backend_restart_detected": False,
            "wall_clock_rollback_detected": False,
            "monotonic_regression_detected": False,
            "clock_evidence_verified": True,
        }
        if current is None or any(
            context.get(field) is not expected
            for field, expected in required_clock_context.items()
        ):
            faults.add("CLOCK_UNTRUSTED")
        else:
            clock_keys = {"clock_domain_id", "boot_id", "unit", "value", "resolution"}
            shape_or_identity_invalid = (
                set(start) != clock_keys
                or set(deadline) != clock_keys
                or set(current) != clock_keys
                or any(
                    start[field] != deadline[field] or start[field] != current[field]
                    for field in ("clock_domain_id", "boot_id", "unit")
                )
                or wall.get("boot_id") != start.get("boot_id")
            )
            if shape_or_identity_invalid:
                faults.add("CLOCK_UNTRUSTED")
            else:
                start_value = int(_as_string(start["value"], "monotonic start"))
                deadline_value = int(_as_string(deadline["value"], "monotonic deadline"))
                current_monotonic = int(_as_string(current["value"], "current monotonic"))
                if start_value > current_monotonic or deadline_value <= start_value:
                    faults.add("CLOCK_UNTRUSTED")
                if deadline_value - start_value > 1_800_000_000:
                    faults.add("CLOCK_UNTRUSTED")
                if current_monotonic >= deadline_value:
                    faults.add("EXPIRED")
            if _instant(wall["value"]) > _instant(record["issued_at"]):
                faults.add("CLOCK_UNTRUSTED")
    if now < _instant(record["not_before"]):
        faults.add("NOT_YET_VALID")
    if now >= _instant(record["expires_at"]):
        faults.add("EXPIRED")


def _add_prerequisite_faults(
    faults: set[str],
    record: JsonObject,
    reference: JsonObject,
    context: JsonObject,
    now: datetime,
    trust_mode: str,
    keys: dict[str, _VerifierKey],
    validator: Draft202012Validator,
    vendor: Path,
) -> None:
    if record["record_type"] == "DiscoveryRunAuthorization":
        bindings = record["prerequisite_gates"]
        supplied = context.get("prerequisite_gate_records")
        if bindings != reference["prerequisite_gates"] or not isinstance(supplied, list):
            faults.add("PREREQUISITE_GATE_INVALID")
            return
        expected_kinds = (
            "R0_REPAIR_ACCEPTED",
            "F0A_FOUNDATION_ACCEPTED",
            "DISCOVERY_SECURITY_ACCEPTED",
        )
        if len(supplied) != 3:
            faults.add("PREREQUISITE_GATE_INVALID")
            return
        previous_hash: str | None = None
        paired_gates = zip(bindings, supplied, strict=True)
        for index, (binding_value, receipt_value) in enumerate(paired_gates):
            binding = _as_object(binding_value, "prerequisite gate binding")
            receipt = _as_object(receipt_value, "prerequisite gate receipt")
            expected_prerequisites = [] if previous_hash is None else [previous_hash]
            revoked, revocation_valid = _is_revoked(
                receipt, context, now, trust_mode, keys, validator, vendor
            )
            if (
                binding.get("gate_kind") != expected_kinds[index]
                or receipt.get("gate_kind") != expected_kinds[index]
                or binding.get("content_hash") != receipt.get("content_hash")
                or receipt.get("gate_result") != "PASS"
                or receipt.get("declared_use_semantics") != "SINGLE_USE"
                or receipt.get("one_use") is not True
                or receipt.get("consumed_before")
                != "ATOMIC_LEDGER_COMMIT_BEFORE_GATE_USE"
                or receipt.get("prerequisite_receipt_hashes") != expected_prerequisites
                or receipt.get("pack_bindings") != record.get("pack_bindings")
                or receipt.get("implementation_bindings")
                != record.get("implementation_bindings")
                or not _record_mechanism_valid(
                    receipt, trust_mode, keys, validator, vendor
                )
                or revoked
                or not revocation_valid
                or now < _instant(receipt["not_before"])
                or now >= _instant(receipt["expires_at"])
            ):
                faults.add("PREREQUISITE_GATE_INVALID")
            previous_hash = _as_string(receipt["content_hash"], "prerequisite hash")
    if record["record_type"] == "GateReceipt" and record[
        "prerequisite_receipt_hashes"
    ] != reference["prerequisite_receipt_hashes"]:
        faults.add("PREREQUISITE_GATE_INVALID")


def _add_scope_faults(
    faults: set[str],
    record: JsonObject,
    reference: JsonObject,
    context: JsonObject,
    now: datetime,
    trust_mode: str,
    keys: dict[str, _VerifierKey],
    validator: Draft202012Validator,
    vendor: Path,
) -> None:
    record_type = _as_string(record["record_type"], "record_type")
    if record["scope"] != reference["scope"]:
        faults.add("SCOPE_BINDING_MISMATCH")

    if record_type in {"DiscoveryRunAuthorization", "BodyClassApproval"}:
        actual_browser = _as_object(record["browser_binding"], "browser binding")
        expected_browser = copy.deepcopy(
            _as_object(reference["browser_binding"], "reference browser binding")
        )
        _overlay_expected(
            expected_browser,
            context,
            {field: f"expected_{field}" for field in BROWSER_FIELDS},
        )
        if actual_browser != expected_browser:
            faults.add("SCOPE_BINDING_MISMATCH")

    if record_type == "DiscoveryRunAuthorization":
        for field in (
            "authorization_mode",
            "discovery_run_id",
            "pairing_secret_commitment",
            "verifier_clock",
            "prerequisite_gates",
            "budget",
        ):
            if record[field] != reference[field]:
                faults.add("SCOPE_BINDING_MISMATCH")
        if record["authorization_mode"] == "NEW_RUN" and "resume_binding" in record:
            faults.add("SCOPE_BINDING_MISMATCH")
        if record["authorization_mode"] == "RESUME_EXISTING_RUN" and (
            "resume_binding" not in record
            or record.get("resume_binding") != reference.get("resume_binding")
        ):
            faults.add("SCOPE_BINDING_MISMATCH")
    elif record_type == "GateReceipt":
        for field in ("gate_kind", "gate_result", "criteria_evidence_hashes"):
            if record[field] != reference[field]:
                faults.add("SCOPE_BINDING_MISMATCH")
        if record["gate_kind"] == "EVIDENCE_EXPORT_ACCEPTED" and (
            record.get("bound_run_id")
            != context.get(
                "expected_bound_run_id", reference.get("bound_run_id")
            )
            or record.get("accepted_sanitized_export_manifest_hash")
            != context.get(
                "expected_accepted_sanitized_export_manifest_hash",
                reference.get("accepted_sanitized_export_manifest_hash"),
            )
        ):
            faults.add("SCOPE_BINDING_MISMATCH")
    elif record_type == "BodyClassApproval":
        for field in (
            "discovery_run_id",
            "body_class",
            "metadata_only_evidence_hash",
            "test_only_manifest_hash",
        ):
            if record[field] != reference[field]:
                faults.add("SCOPE_BINDING_MISMATCH")
    elif record_type == "ProviderProbeProtocol":
        for field in (
            "protocol_id",
            "protocol_state",
            "endpoint_templates",
            "sample_windows",
            "deterministic_sampling_rule",
            "retry_policy",
            "maximum_response_bytes",
            "allowed_fields",
            "denominators",
            "cadence",
            "budget",
            "licensing",
            "credential_class",
            "accepted_schema_versions",
            "prohibited_outputs",
        ):
            if record[field] != reference[field]:
                faults.add("SCOPE_BINDING_MISMATCH")
    elif record_type == "ProviderCallAuthorization":
        for field in (
            "provider_call_id",
            "protocol_id",
            "protocol_content_hash",
            "endpoint_template_id",
            "sample_window_id",
            "sample_id",
            "method",
            "body_policy",
            "maximum_response_bytes",
            "verifier_clock",
        ):
            if record[field] != reference[field]:
                faults.add("SCOPE_BINDING_MISMATCH")
        protocol_value = context.get("provider_protocol_record")
        if not isinstance(protocol_value, dict):
            faults.add("SCOPE_BINDING_MISMATCH")
        else:
            protocol = cast(JsonObject, protocol_value)
            revoked, revocation_valid = _is_revoked(
                protocol, context, now, trust_mode, keys, validator, vendor
            )
            endpoints = protocol.get("endpoint_templates")
            windows = protocol.get("sample_windows")
            endpoint = next(
                (
                    item
                    for item in endpoints
                    if isinstance(item, dict)
                    and item.get("endpoint_template_id")
                    == record.get("endpoint_template_id")
                ),
                None,
            ) if isinstance(endpoints, list) else None
            window = next(
                (
                    item
                    for item in windows
                    if isinstance(item, dict)
                    and item.get("window_id") == record.get("sample_window_id")
                ),
                None,
            ) if isinstance(windows, list) else None
            if (
                not _record_mechanism_valid(
                    protocol, trust_mode, keys, validator, vendor
                )
                or revoked
                or not revocation_valid
                or now < _instant(protocol["not_before"])
                or now >= _instant(protocol["expires_at"])
                or protocol.get("protocol_id") != record.get("protocol_id")
                or protocol.get("content_hash") != record.get("protocol_content_hash")
                or endpoint is None
                or window is None
                or endpoint.get("method") != record.get("method")
                or endpoint.get("body_policy") != record.get("body_policy")
                or int(_as_string(record["maximum_response_bytes"], "response ceiling"))
                > int(_as_string(protocol["maximum_response_bytes"], "protocol ceiling"))
            ):
                faults.add("SCOPE_BINDING_MISMATCH")


def _add_consumption_faults(
    faults: set[str], record: JsonObject, context: JsonObject
) -> None:
    if record["one_use"] is not True:
        return
    content_hash = record["content_hash"]
    if content_hash in _as_list(context.get("consumed_content_hashes", []), "consumed hashes"):
        faults.add("ALREADY_CONSUMED")
    for value in _as_list(context.get("consumed_records", []), "consumed records"):
        consumed = _as_object(value, "consumed record")
        if consumed.get("content_hash") == content_hash:
            consumed_identity = _consumption_identity(consumed)
            if consumed_identity is not None and consumed_identity != _consumption_identity(record):
                faults.add("LOCAL_STATE_CONFLICT")
            else:
                faults.add("ALREADY_CONSUMED")


def _add_serial_and_local_state_faults(
    faults: set[str], record: JsonObject, reference: JsonObject, context: JsonObject
) -> None:
    if record["record_type"] == "RevocationRecord":
        if record["revocation_sequence"] != reference["revocation_sequence"]:
            faults.add("SERIAL_CONFLICT")
        if record["previous_revocation_hash"] != reference["previous_revocation_hash"]:
            faults.add("LOCAL_STATE_CONFLICT")
    for value in _as_list(context.get("consumed_records", []), "consumed records"):
        consumed = _as_object(value, "consumed record")
        consumed_identity = _consumption_identity(consumed)
        record_identity = _consumption_identity(record)
        if consumed_identity == record_identity and consumed.get("content_hash") != record[
            "content_hash"
        ]:
            faults.add("SERIAL_CONFLICT")
        consumed_scope = _nonce_scope(consumed)
        if (
            consumed_scope is not None
            and consumed_scope == _nonce_scope(record)
            and consumed.get("nonce") == record["nonce"]
            and consumed.get("content_hash") != record["content_hash"]
        ):
            faults.add("LOCAL_STATE_CONFLICT")


def _consumption_identity(record: JsonObject) -> tuple[object, object, object, object] | None:
    fields = ("issuer", "issuer_key_id", "audience", "serial")
    if not all(field in record for field in fields):
        return None
    return tuple(record[field] for field in fields)


def _nonce_scope(record: JsonObject) -> tuple[object, object, object, object] | None:
    fields = ("issuer", "issuer_key_id", "audience")
    if not all(field in record for field in fields):
        return None
    scope_binding_hash = record.get("scope_binding_hash")
    if scope_binding_hash is None:
        try:
            scope_binding_hash = _scope_binding_hash(record)
        except (AssertionError, KeyError, TypeError, ValueError):
            return None
    return (
        record["issuer"],
        record["issuer_key_id"],
        record["audience"],
        scope_binding_hash,
    )


def _scope_binding_hash(record: JsonObject) -> str:
    record_type = _as_string(record["record_type"], "record type")
    projection: JsonObject = {
        "record_type": record_type,
        "scope": record["scope"],
    }
    fields_by_type = {
        "GateReceipt": ("gate_kind", "bound_run_id"),
        "DiscoveryRunAuthorization": ("discovery_run_id", "browser_binding"),
        "BodyClassApproval": ("discovery_run_id", "browser_binding", "body_class"),
        "ProviderProbeProtocol": ("protocol_id",),
        "ProviderCallAuthorization": (
            "protocol_id",
            "endpoint_template_id",
            "sample_window_id",
            "sample_id",
        ),
        "RevocationRecord": ("ledger_id",),
    }
    for field in fields_by_type[record_type]:
        if field in record:
            projection[field] = record[field]
    canonical = rfc8785.dumps(projection)
    return hashlib.sha256(
        b"HYBRID-DISCOVERY/v6.2/AUTHORIZATION-SCOPE-BINDING/v1\0" + canonical
    ).hexdigest()


def _signed_vector_context(reference: JsonObject, state: JsonObject) -> JsonObject:
    context = copy.deepcopy(state)
    context.setdefault("validation_time", reference["not_before"])
    return context


def _evaluation(faults: set[str]) -> _Evaluation:
    result = next((code for code in FAILURE_PRECEDENCE if code in faults), "VALID")
    return _Evaluation(result=result, faults=frozenset(faults))


def _assert_result(vector: JsonObject, field: str, computed: str) -> None:
    expected = vector[field]
    assert computed == expected, (
        f"{vector['vector_id']}:{field} declared={expected!r} computed={computed!r}"
    )


def _apply_mutations(reference: JsonObject, mutations: list[object]) -> JsonObject:
    record = copy.deepcopy(reference)
    for value in mutations:
        mutation = _as_object(value, "mutation")
        assert set(mutation) == {"operation", "path", "value"}
        assert mutation["operation"] == "replace"
        path = _as_string(mutation["path"], "mutation path")
        assert path.startswith("/") and path != "/"
        components = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        target: object = record
        for component in components[:-1]:
            if isinstance(target, dict):
                assert component in target
                target = target[component]
            else:
                assert isinstance(target, list)
                target = target[int(component)]
        final = components[-1]
        if isinstance(target, dict):
            assert final in target
            target[final] = mutation["value"]
        else:
            assert isinstance(target, list)
            target[int(final)] = mutation["value"]
    return record


def _overlay_expected(
    expected: JsonObject, context: JsonObject, mapping: dict[str, str]
) -> None:
    for field, context_field in mapping.items():
        if context_field in context:
            expected[field] = context[context_field]


def _decode_base64url(value: str, expected_length: int) -> bytes:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if "=" in value or any(char not in alphabet for char in value):
        raise ValueError("invalid unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError as error:
        raise ValueError("invalid unpadded base64url") from error
    if len(decoded) != expected_length:
        raise ValueError("invalid decoded length")
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise ValueError("noncanonical unpadded base64url")
    return decoded


def _instant(value: object) -> datetime:
    text = _as_string(value, "instant")
    assert text.endswith("Z")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    assert parsed.utcoffset() == timedelta(0)
    return parsed


def _as_object(value: object, label: str) -> JsonObject:
    assert isinstance(value, dict), f"{label} must be an object"
    assert all(isinstance(key, str) for key in value)
    return cast(JsonObject, value)


def _as_list(value: object, label: str) -> list[object]:
    assert isinstance(value, list), f"{label} must be an array"
    return cast(list[object], value)


def _as_string(value: object, label: str) -> str:
    assert isinstance(value, str), f"{label} must be a string"
    return value
