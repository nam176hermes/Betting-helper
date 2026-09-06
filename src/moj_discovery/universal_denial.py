from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from referencing import Registry, Resource

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")

_ORDERED_STAGES = (
    "DECODE",
    "SHAPE_SCAN",
    "NAME_SCAN",
    "VALUE_SCAN",
    "ENTROPY_SCAN",
    "DECLARATION_CHECK",
    "SCHEMA_VALIDATE",
    "PROJECT_SANITIZED_RECORD",
    "HASH_SANITIZED_RECORD",
    "LOG_RECEIPT",
    "PERSIST_INDEXEDDB",
    "PERSIST_SQLITE",
    "EMIT_FIXTURE",
    "EMIT_REPORT",
    "EMIT_REPLAY_ARTIFACT",
    "EMIT_EXPORT",
)
SIDE_EFFECT_STAGES = _ORDERED_STAGES[7:]

_REQUIRED_FORBIDDEN_REGISTRY: dict[str, tuple[str, ...]] = {
    "forbidden_name_fragments": (
        "cookie",
        "authorization",
        "bearer",
        "basic",
        "token",
        "secret",
        "key",
        "password",
        "credentials",
        "url",
        "query",
        "fragment",
        "headers",
        "selector",
        "script",
        "expression",
    ),
    "forbidden_open_object_names": ("payload", "data", "attributes"),
    "forbidden_credential_value_markers": ("Bearer ", "Basic "),
    "forbidden_command_prefixes": ("Runtime.", "DOM.", "Input.", "Fetch."),
    "forbidden_mutating_command_prefixes": (
        "Page.",
        "Network.set",
        "Network.emulate",
        "Network.continue",
        "Network.fail",
        "Network.fulfill",
        "Network.delete",
        "Network.clear",
    ),
    "forbidden_authority_values": ("PRODUCTION", "LIVE", "REAL_MONEY"),
    "allowed_non_mutating_command_values": ("Network.enable", "Network.disable"),
    "forbidden_result_names": ("final_score", "winner", "settlement", "outcome", "outcomes"),
    "forbidden_metric_names": (
        "wdl_metric",
        "model_metric",
        "calibration_metric",
        "market_performance",
        "roi",
        "yield",
        "ev",
        "edge",
        "profit",
        "pnl",
        "drawdown",
        "ranking",
        "champion",
    ),
}

_SAFE_IDENTIFIER = {
    "field_name": "issuer_key_id",
    "required_declaring_schema_id": "urn:hybrid-discovery:v6.2:authorization-records",
    "required_declared_value_pattern": r"^key:ed25519:[0-9a-f]{64}$",
    "excepted_forbidden_segment": "key",
    "bypass_scope": "NAME_FRAGMENT_ONLY",
}

_EXPECTED_LIMITS = {
    "maximum_depth": 64,
    "maximum_object_properties": 512,
    "maximum_array_items": 4096,
    "maximum_total_nodes": 100000,
    "maximum_string_utf8_bytes": 2097152,
}

_EXPECTED_DENIAL_PRECEDENCE = (
    (1, "DECODE", "E_ENCODING_OR_DUPLICATE_OR_NFC"),
    (2, "SHAPE_SCAN", "E_SHAPE_RESOURCE_LIMIT_OR_NONFINITE"),
    (3, "NAME_SCAN", "E_FORBIDDEN_NAME_OR_OPEN_OBJECT_ESCAPE"),
    (4, "VALUE_SCAN", "E_FORBIDDEN_VALUE_OR_COMMAND_OR_AUTHORITY"),
    (5, "ENTROPY_SCAN", "E_CREDENTIAL_ENTROPY"),
    (6, "DECLARATION_CHECK", "E_UNKNOWN_NAME_OR_SCHEMA_QUARANTINE"),
    (7, "SCHEMA_VALIDATE", "E_CLOSED_SCHEMA_VIOLATION"),
)

_COMMAND_VALUE = re.compile(r"^[A-Z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*$")
_RFC3339_DATE_TIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})$"
)
_SIGNATURE_PATTERN = r"^[A-Za-z0-9_-]{86}$"
_NONCE_PATTERN = r"^[A-Za-z0-9_-]{43}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_DECIMAL_PATTERNS = {
    r"^(0|[1-9][0-9]*)$",
    r"^(0|[1-9][0-9]*)(\.[0-9]+)?$",
    r"^[1-9][0-9]*$",
}
_EXCLUDED_ANCHORS = {
    "Sha256",
    "UUID",
    "OpaqueId",
    "UnsignedDecimal",
    "UnsignedInteger",
    "PositiveInteger",
    "UtcDateTime",
}

Disposition = Literal["ACCEPTED", "REJECTED", "SCANNER_FAILURE", "QUARANTINED"]


class UniversalDenialContractError(AssertionError):
    """The immutable denial contract or its synthetic fixture has drifted."""


@dataclass(frozen=True)
class DenialReceiptIdentity:
    receipt_id: str
    attempt_id: str
    input_class: str


@dataclass(frozen=True)
class UniversalScanOutcome:
    disposition: Disposition
    error_code: str | None
    violation_class: str | None
    location_code: str | None
    completed_stages: tuple[str, ...]
    receipt: dict[str, object] | None


@dataclass(frozen=True)
class _Violation(Exception):
    error_code: str
    violation_class: str
    path: tuple[str | int, ...]
    disposition: Disposition = "REJECTED"
    fixed_location: str | None = None


@dataclass(frozen=True)
class _SchemaNode:
    document_id: str
    schema: object


class _DuplicateName(ValueError):
    pass


class _MalformedEncoding(ValueError):
    pass


class _NonNfc(ValueError):
    pass


class _SchemaNavigator:
    def __init__(self, documents: Mapping[str, dict[str, object]]) -> None:
        self._documents = documents
        self._path_cache: dict[tuple[str, tuple[str | int, ...]], tuple[_SchemaNode, ...]] = {}

    def resolve_target(self, reference: str, current_document_id: str | None = None) -> _SchemaNode:
        if reference.startswith("#"):
            if current_document_id is None:
                raise KeyError(reference)
            document_id = current_document_id
            fragment = reference[1:]
        else:
            document_id, separator, fragment = reference.partition("#")
            if not separator:
                fragment = ""
        document = self._documents[document_id]
        target: object = document
        if fragment.startswith("/"):
            for encoded_part in fragment[1:].split("/"):
                part = encoded_part.replace("~1", "/").replace("~0", "~")
                if isinstance(target, dict):
                    target = target[part]
                elif isinstance(target, list):
                    target = target[int(part)]
                else:
                    raise KeyError(reference)
        elif fragment:
            matches = list(_find_anchor(document, fragment))
            if len(matches) != 1:
                raise KeyError(reference)
            target = matches[0]
        return _SchemaNode(document_id, target)

    def nodes_at_path(
        self, schema_ref: str, record: object, path: Sequence[str | int]
    ) -> tuple[_SchemaNode, ...]:
        cache_key = (schema_ref, tuple(path))
        cached = self._path_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            nodes: tuple[_SchemaNode, ...] = (self.resolve_target(schema_ref),)
        except (KeyError, ValueError):
            return ()
        value = record
        for component in path:
            children: list[_SchemaNode] = []
            for node in self._expand(nodes):
                schema = node.schema
                if not isinstance(schema, dict):
                    continue
                if isinstance(component, str):
                    properties = schema.get("properties")
                    if isinstance(properties, dict) and component in properties:
                        children.append(_SchemaNode(node.document_id, properties[component]))
                    pattern_properties = schema.get("patternProperties")
                    if isinstance(pattern_properties, dict):
                        for pattern, child in pattern_properties.items():
                            if isinstance(pattern, str) and re.search(pattern, component):
                                children.append(_SchemaNode(node.document_id, child))
                else:
                    prefix_items = schema.get("prefixItems")
                    if isinstance(prefix_items, list) and component < len(prefix_items):
                        children.append(_SchemaNode(node.document_id, prefix_items[component]))
                    elif isinstance(schema.get("items"), (dict, bool)):
                        children.append(_SchemaNode(node.document_id, schema["items"]))
            if not children:
                self._path_cache[cache_key] = ()
                return ()
            nodes = _deduplicate_nodes(children)
            if isinstance(component, str) and isinstance(value, dict):
                value = value.get(component)
            elif isinstance(component, int) and isinstance(value, list) and component < len(value):
                value = value[component]
            else:
                value = None
        result = tuple(self._expand(nodes))
        self._path_cache[cache_key] = result
        return result

    def _expand(self, nodes: Sequence[_SchemaNode]) -> tuple[_SchemaNode, ...]:
        expanded: list[_SchemaNode] = []
        pending = list(reversed(nodes))
        seen: set[tuple[str, int]] = set()
        while pending:
            node = pending.pop()
            marker = (node.document_id, id(node.schema))
            if marker in seen:
                continue
            seen.add(marker)
            expanded.append(node)
            schema = node.schema
            if not isinstance(schema, dict):
                continue
            reference = schema.get("$ref")
            if isinstance(reference, str):
                try:
                    pending.append(self.resolve_target(reference, node.document_id))
                except (KeyError, ValueError):
                    continue
            for keyword in ("allOf", "oneOf", "anyOf"):
                branches = schema.get(keyword)
                if isinstance(branches, list):
                    pending.extend(
                        _SchemaNode(node.document_id, branch) for branch in reversed(branches)
                    )
            for keyword in ("if", "then", "else"):
                branch = schema.get(keyword)
                if isinstance(branch, (dict, bool)):
                    pending.append(_SchemaNode(node.document_id, branch))
        return tuple(expanded)


class UniversalDenialEngine:
    """Bootstrap-only, closed scanner that stops before every downstream side effect."""

    def __init__(self, vendor: Path = VENDOR) -> None:
        self.vendor = vendor
        self._documents, self._registry = _load_schemas(vendor)
        meta = self._documents["urn:hybrid-discovery:v6.2:meta-records:v1"]
        forbidden = meta.get("x-universal-forbidden-registry")
        policy = meta.get("x-universal-denial-policy")
        if not isinstance(forbidden, dict) or not isinstance(policy, dict):
            raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
        _validate_policy(forbidden, policy)
        self._forbidden = forbidden
        self._policy = policy
        self._navigator = _SchemaNavigator(self._documents)
        self._format_checker = _format_checker()

    def scan(
        self,
        raw_candidate: bytes,
        schema_ref: str,
        *,
        receipt_identity: DenialReceiptIdentity | None = None,
    ) -> UniversalScanOutcome:
        return self._scan(
            raw_candidate,
            schema_ref,
            receipt_identity=receipt_identity,
            inject_scanner_fault=False,
        )

    def validate_schema(self, instance: object, schema_ref: str) -> None:
        Draft202012Validator(
            {"$ref": schema_ref},
            registry=self._registry,
            format_checker=self._format_checker,
        ).validate(instance)

    def _scan(
        self,
        raw_candidate: bytes,
        schema_ref: str,
        *,
        receipt_identity: DenialReceiptIdentity | None,
        inject_scanner_fault: bool,
    ) -> UniversalScanOutcome:
        completed: list[str] = []
        try:
            record = _decode(raw_candidate)
            completed.append("DECODE")
            _shape_scan(record, cast(dict[str, int], self._policy["limits"]))
            completed.append("SHAPE_SCAN")
            record_object = cast(dict[str, object], record)
            if inject_scanner_fault:
                raise _Violation(
                    "E_SCANNER_FAILURE",
                    "SCANNER_FAILURE",
                    (),
                    "SCANNER_FAILURE",
                    "SCANNER_INTERNAL_FAILURE",
                )
            self._name_scan(record_object, schema_ref)
            completed.append("NAME_SCAN")
            self._value_scan(record_object)
            completed.append("VALUE_SCAN")
            self._entropy_scan(record_object, schema_ref)
            completed.append("ENTROPY_SCAN")
            self._declaration_check(record_object, schema_ref)
            completed.append("DECLARATION_CHECK")
            self.validate_schema(record_object, schema_ref)
            completed.append("SCHEMA_VALIDATE")
        except _Violation as violation:
            return self._denied(violation, tuple(completed), receipt_identity)
        except _DuplicateName:
            return self._denied(
                _Violation(
                    "E_DUPLICATE_NAME",
                    "DUPLICATE_NAME",
                    (),
                    fixed_location="ROOT_DUPLICATE_NAME",
                ),
                tuple(completed),
                receipt_identity,
            )
        except _NonNfc:
            return self._denied(
                _Violation("E_NON_NFC", "NORMALIZATION", (), fixed_location="ROOT_NORMALIZATION"),
                tuple(completed),
                receipt_identity,
            )
        except _MalformedEncoding:
            return self._denied(
                _Violation("E_ENCODING", "ENCODING", (), fixed_location="ROOT_ENCODING"),
                tuple(completed),
                receipt_identity,
            )
        except ValidationError:
            completed.append("SCHEMA_VALIDATE")
            return self._denied(
                _Violation(
                    "E_CLOSED_SCHEMA_VIOLATION",
                    "UNKNOWN_SCHEMA",
                    (),
                    fixed_location="ROOT_SCHEMA",
                ),
                tuple(completed),
                receipt_identity,
            )
        except Exception:
            return self._denied(
                _Violation(
                    "E_SCANNER_FAILURE",
                    "SCANNER_FAILURE",
                    (),
                    "SCANNER_FAILURE",
                    "SCANNER_INTERNAL_FAILURE",
                ),
                tuple(completed),
                receipt_identity,
            )
        return UniversalScanOutcome(
            disposition="ACCEPTED",
            error_code=None,
            violation_class=None,
            location_code=None,
            completed_stages=tuple(completed),
            receipt=None,
        )

    def _name_scan(self, record: dict[str, object], schema_ref: str) -> None:
        open_names = _string_set(self._forbidden, "forbidden_open_object_names")
        result_names = _string_set(self._forbidden, "forbidden_result_names")
        metric_names = _string_set(self._forbidden, "forbidden_metric_names")
        fragments = _string_tuple(self._forbidden, "forbidden_name_fragments")
        for path, name, value in _walk_names(record):
            lowered = _ascii_lower(name)
            if lowered in open_names:
                raise _Violation("E_OPEN_OBJECT_ESCAPE", "FORBIDDEN_NAME", path)
            if lowered in result_names:
                raise _Violation("E_D0_RESULT_FIELD", "FORBIDDEN_NAME", path)
            if lowered in metric_names:
                raise _Violation("E_D0_PERFORMANCE_FIELD", "FORBIDDEN_NAME", path)
            matched = [fragment for fragment in fragments if fragment in lowered]
            if not matched:
                continue
            if matched == ["key"] and self._safe_identifier_allowed(
                path, name, value, record, schema_ref
            ):
                continue
            raise _Violation("E_FORBIDDEN_NAME", "FORBIDDEN_NAME", path)

    def _safe_identifier_allowed(
        self,
        path: tuple[str | int, ...],
        name: str,
        value: object,
        record: dict[str, object],
        schema_ref: str,
    ) -> bool:
        if name != _SAFE_IDENTIFIER["field_name"] or not isinstance(value, str):
            return False
        pattern = _SAFE_IDENTIFIER["required_declared_value_pattern"]
        if re.fullmatch(pattern, value) is None:
            return False
        return any(
            node.document_id == _SAFE_IDENTIFIER["required_declaring_schema_id"]
            and isinstance(node.schema, dict)
            and node.schema.get("pattern") == pattern
            for node in self._navigator.nodes_at_path(schema_ref, record, path)
        )

    def _value_scan(self, record: dict[str, object]) -> None:
        credential_markers = _string_tuple(
            self._forbidden, "forbidden_credential_value_markers"
        )
        command_prefixes = _string_tuple(self._forbidden, "forbidden_command_prefixes")
        mutating_prefixes = _string_tuple(
            self._forbidden, "forbidden_mutating_command_prefixes"
        )
        allowed_commands = _string_set(
            self._forbidden, "allowed_non_mutating_command_values"
        )
        forbidden_authority = {
            value.casefold()
            for value in _string_tuple(self._forbidden, "forbidden_authority_values")
        }
        for path, value in _walk_string_values(record):
            folded = value.casefold()
            if any(folded.startswith(marker.casefold()) for marker in credential_markers):
                raise _Violation("E_FORBIDDEN_VALUE", "FORBIDDEN_VALUE", path)
            if value not in allowed_commands and (
                value.startswith(command_prefixes)
                or value.startswith(mutating_prefixes)
                or _COMMAND_VALUE.fullmatch(value) is not None
            ):
                raise _Violation("E_FORBIDDEN_COMMAND", "FORBIDDEN_VALUE", path)
            if folded in forbidden_authority:
                raise _Violation("E_FORBIDDEN_AUTHORITY", "FORBIDDEN_VALUE", path)

    def _entropy_scan(self, record: dict[str, object], schema_ref: str) -> None:
        entropy = cast(dict[str, object], self._policy["entropy_rule"])
        minimum_bytes = cast(int, entropy["minimum_utf8_bytes"])
        minimum_bits = float(cast(str, entropy["minimum_shannon_bits_per_byte"]))
        minimum_classes = cast(int, entropy["minimum_character_classes"])
        for path, value in _walk_string_values(record):
            encoded = value.encode("utf-8")
            if len(encoded) < minimum_bytes:
                continue
            if self._is_typed_entropy_exclusion(record, schema_ref, path):
                continue
            if _character_class_count(value) < minimum_classes:
                continue
            if _shannon_bits_per_byte(encoded) >= minimum_bits:
                raise _Violation("E_CREDENTIAL_ENTROPY", "CREDENTIAL_ENTROPY", path)

    def _is_typed_entropy_exclusion(
        self,
        record: dict[str, object],
        schema_ref: str,
        path: tuple[str | int, ...],
    ) -> bool:
        for node in self._navigator.nodes_at_path(schema_ref, record, path):
            schema = node.schema
            if not isinstance(schema, dict):
                continue
            if schema.get("$anchor") in _EXCLUDED_ANCHORS:
                return True
            pattern = schema.get("pattern")
            if pattern in {
                _SIGNATURE_PATTERN,
                _NONCE_PATTERN,
                _SHA256_PATTERN,
                _UUID_PATTERN,
                *_DECIMAL_PATTERNS,
            }:
                return True
            if schema.get("format") == "date-time" and schema.get("pattern") == "Z$":
                return True
        return False

    def _declaration_check(self, record: dict[str, object], schema_ref: str) -> None:
        if not self._navigator.nodes_at_path(schema_ref, record, ()):
            raise _Violation(
                "E_UNKNOWN_SCHEMA",
                "UNKNOWN_SCHEMA",
                (),
                "QUARANTINED",
                "ROOT_SCHEMA",
            )
        for path, _name, _value in _walk_names(record):
            if not self._navigator.nodes_at_path(schema_ref, record, path):
                raise _Violation("E_UNKNOWN_NAME", "UNKNOWN_NAME", path, "QUARANTINED")

    def _denied(
        self,
        violation: _Violation,
        completed_stages: tuple[str, ...],
        identity: DenialReceiptIdentity | None,
    ) -> UniversalScanOutcome:
        location = violation.fixed_location or _location_code(violation.path)
        receipt = None
        if identity is not None:
            receipt = _build_receipt(identity, violation, location)
            self.validate_schema(
                receipt,
                "urn:hybrid-discovery:v6.2:meta-records:v1#UniversalDenialReceipt",
            )
        if set(completed_stages) & set(SIDE_EFFECT_STAGES):
            raise UniversalDenialContractError("E_DENIAL_AFTER_SIDE_EFFECT_BOUNDARY")
        return UniversalScanOutcome(
            disposition=violation.disposition,
            error_code=violation.error_code,
            violation_class=violation.violation_class,
            location_code=location,
            completed_stages=completed_stages,
            receipt=receipt,
        )


def run_synthetic_side_effect_boundary(
    engine: UniversalDenialEngine,
    raw_candidate: bytes,
    schema_ref: str,
    side_effect_probe: Callable[[str], None],
    *,
    receipt_identity: DenialReceiptIdentity | None = None,
) -> UniversalScanOutcome:
    """Exercise the admission boundary without implementing a downstream side effect."""
    outcome = engine.scan(
        raw_candidate,
        schema_ref,
        receipt_identity=receipt_identity,
    )
    if outcome.disposition == "ACCEPTED":
        for stage in SIDE_EFFECT_STAGES:
            side_effect_probe(stage)
    return outcome


def validate_universal_denial_vectors(vendor: Path = VENDOR) -> None:
    engine = UniversalDenialEngine(vendor)
    rank_one_counts = {"e0-evidence-v1.json": 6, "d0-evidence-v1.json": 17}
    seam_count = 0
    acceptance_count = 0
    for vector_name, expected_rank_one_count in rank_one_counts.items():
        data = _load_json_object(vendor / "vectors" / vector_name)
        bases = _vector_bases(data)
        rank_one = [
            case
            for case in _object_list(data, "counterexamples")
            if case.get("precedence_rank") == 1
        ]
        if len(rank_one) != expected_rank_one_count:
            raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_VECTOR_COUNT")
        for case in rank_one:
            engine.validate_schema(
                case,
                "urn:hybrid-discovery:v6.2:meta-records:v1#SemanticVectorCase",
            )
            candidate = _patched_candidate(case, bases)
            outcome = engine.scan(_record_bytes(candidate), _record_schema_ref(candidate))
            if outcome.error_code != case["expected_error"] or outcome.disposition == "ACCEPTED":
                raise UniversalDenialContractError(
                    f"E_UNIVERSAL_DENIAL_VECTOR:{case['case_id']}"
                )
            _assert_before_side_effects(outcome)

        for base in bases.values():
            expectation = base.get("scanner_acceptance_expectation")
            if expectation is None:
                continue
            acceptance_count += 1
            engine.validate_schema(
                expectation,
                "urn:hybrid-discovery:v6.2:meta-records:v1#UniversalScannerAcceptanceExpectation",
            )
            observed_effects: list[str] = []
            outcome = run_synthetic_side_effect_boundary(
                engine,
                _record_bytes(base),
                _record_schema_ref(base),
                observed_effects.append,
            )
            if outcome.disposition != "ACCEPTED" or outcome.completed_stages != _ORDERED_STAGES[:7]:
                raise UniversalDenialContractError(
                    f"E_UNIVERSAL_DENIAL_ACCEPTANCE:{base['case_id']}"
                )
            if observed_effects != list(SIDE_EFFECT_STAGES):
                raise UniversalDenialContractError("E_SIDE_EFFECT_BOUNDARY_ORDER")
            expected_side_effects = cast(dict[str, object], expectation)[
                "side_effects_before_acceptance"
            ]
            if not isinstance(expected_side_effects, dict) or any(expected_side_effects.values()):
                raise UniversalDenialContractError("E_ACCEPTANCE_SIDE_EFFECT_EXPECTATION")

        if vector_name != "e0-evidence-v1.json":
            continue
        seams = _object_list(data, "denial_seam_vectors")
        seam_count += len(seams)
        for case in seams:
            expected_receipt = case.get("expected_receipt")
            if not isinstance(expected_receipt, dict):
                raise UniversalDenialContractError("E_DENIAL_RECEIPT_MISSING")
            identity = DenialReceiptIdentity(
                receipt_id=cast(str, expected_receipt["receipt_id"]),
                attempt_id=cast(str, expected_receipt["attempt_id"]),
                input_class=cast(str, expected_receipt["input_class"]),
            )
            if "fault_injection" in case:
                engine.validate_schema(
                    case,
                    "urn:hybrid-discovery:v6.2:meta-records:v1#UniversalScannerFaultVectorCase",
                )
                _validate_fault_injection(cast(dict[str, object], case["fault_injection"]))
                candidate = _base_candidate(case, bases)
                outcome = engine._scan(
                    _record_bytes(candidate),
                    _record_schema_ref(candidate),
                    receipt_identity=identity,
                    inject_scanner_fault=True,
                )
            else:
                engine.validate_schema(
                    case,
                    "urn:hybrid-discovery:v6.2:meta-records:v1#UniversalDenialVectorCase",
                )
                candidate = _patched_candidate(case, bases)
                seam_effects: list[str] = []
                outcome = run_synthetic_side_effect_boundary(
                    engine,
                    _record_bytes(candidate),
                    _record_schema_ref(candidate),
                    seam_effects.append,
                    receipt_identity=identity,
                )
                if seam_effects:
                    raise UniversalDenialContractError("E_DENIAL_SIDE_EFFECT")
            if outcome.error_code != case["expected_error"]:
                raise UniversalDenialContractError(
                    f"E_UNIVERSAL_DENIAL_SEAM:{case['case_id']}"
                )
            if outcome.receipt != expected_receipt:
                raise UniversalDenialContractError(
                    f"E_UNIVERSAL_DENIAL_RECEIPT:{case['case_id']}"
                )
            if case.get("secret_fixture_hash_computed") is not False:
                raise UniversalDenialContractError("E_SECRET_FIXTURE_HASHED")
            _assert_before_side_effects(outcome)
    if seam_count != 8 or acceptance_count != 1:
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_COVERAGE")


def _validate_policy(forbidden: dict[str, object], policy: dict[str, object]) -> None:
    for key, expected in _REQUIRED_FORBIDDEN_REGISTRY.items():
        if forbidden.get(key) != list(expected):
            raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    if forbidden.get("credential_safe_identifier_name_allowlist") != [_SAFE_IDENTIFIER]:
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    precedence = policy.get("within_denial_error_precedence")
    if not isinstance(precedence, list) or [
        (entry.get("scanner_rank"), entry.get("stage"), entry.get("outcome"))
        for entry in precedence
        if isinstance(entry, dict)
    ] != list(_EXPECTED_DENIAL_PRECEDENCE):
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    entropy = policy.get("entropy_rule")
    if not isinstance(entropy, dict):
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    required_policy = {
        "policy_id": "universal-denial-before-side-effects/v1",
        "input_encoding": "UTF8_NO_BOM",
        "encoding_validation": (
            "REJECT_INVALID_UTF8_OVERLONG_SEQUENCES_SURROGATES_NONCHARACTERS_AND_BOM"
        ),
        "unicode_rule": "REQUIRE_NFC_DO_NOT_NORMALIZE",
        "duplicate_object_names": "REJECT_BEFORE_TRAVERSAL",
        "name_case_rule": "ASCII_LOWERCASE_FOR_MATCH_ONLY",
        "value_case_rule": "UNICODE_DEFAULT_CASEFOLD_FOR_MATCH_ONLY",
        "traversal": "DEPTH_FIRST_PREORDER_OBJECT_NAMES_UTF8_LEXICOGRAPHIC_ARRAY_INDEX_ASCENDING",
        "shape_rule": (
            "JSON_OBJECT_ROOT_ONLY_FINITE_TREE_RESOURCE_LIMITS_NO_NONFINITE_NUMBER_"
            "CAPTURE_EVERY_MEMBER_WITHOUT_SCHEMA_ACCEPTANCE"
        ),
        "shape_unknown_member_handling": (
            "CAPTURE_EPHEMERALLY_THEN_CONTINUE_NAME_VALUE_ENTROPY_SCANS; "
            "IF_NO_EARLIER_DENIAL_MATCH_QUARANTINE_AS_UNKNOWN_NAME_OR_SCHEMA_AT_"
            "DECLARATION_CHECK_BEFORE_SCHEMA_VALIDATE"
        ),
        "captured_member_custody": (
            "IN_MEMORY_EXACT_BYTES_ONLY_UNHASHED_UNLOGGED_UNPERSISTED_UNEMITTED"
        ),
        "limits": _EXPECTED_LIMITS,
        "ordered_stages": list(_ORDERED_STAGES),
        "denial_must_complete_before": list(SIDE_EFFECT_STAGES),
        "scanner_failure": "SAFETY_STOP_ZERO_SIDE_EFFECTS",
        "unknown_name_or_schema": "QUARANTINE_ZERO_SIDE_EFFECTS",
        "matched_bytes_recorded": False,
        "candidate_bytes_hashed": False,
        "denied_or_quarantined_candidate_bytes_projected": False,
        "receipt_custody": "SYNTHETIC_IN_MEMORY_EXPECTATION_ONLY_NOT_A_LOG_OR_PERSISTED_ARTIFACT",
        "production_authority": "NONE",
    }
    if any(policy.get(key) != value for key, value in required_policy.items()):
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    if entropy != {
        "minimum_utf8_bytes": 32,
        "minimum_shannon_bits_per_byte": "4.5",
        "minimum_character_classes": 3,
        "calculation": "SHANNON_ENTROPY_BASE2_OVER_EXACT_UTF8_BYTE_FREQUENCIES_WHOLE_STRING",
        "scope": "EVERY_STRING_VALUE_NOT_MATCHING_A_SCHEMA_COMPILED_EXCLUDED_TYPED_PATH",
        "excluded_typed_value_classes": [
            "SHA256",
            "UUID",
            "OPAQUE_ID",
            "SIGNATURE",
            "NONCE",
            "DECIMAL",
            "UTC_DATETIME",
        ],
    }:
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")


def _load_schemas(
    vendor: Path,
) -> tuple[dict[str, dict[str, object]], Registry[dict[str, object]]]:
    documents: dict[str, dict[str, object]] = {}
    resources: list[tuple[str, Resource[dict[str, object]]]] = []
    paths = sorted((vendor / "schemas").glob("*.json"))
    if len(paths) != 13:
        raise UniversalDenialContractError("E_SCHEMA_REGISTRY_DRIFT")
    for path in paths:
        schema = _load_json_object(path)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or schema_id in documents:
            raise UniversalDenialContractError("E_SCHEMA_REGISTRY_DRIFT")
        documents[schema_id] = schema
        resources.append((schema_id, Resource.from_contents(schema)))
    return documents, Registry().with_resources(resources)


def _format_checker() -> FormatChecker:
    checker = FormatChecker()

    @checker.checks("date-time")  # type: ignore[untyped-decorator]
    def valid_date_time(value: object) -> bool:
        if not isinstance(value, str) or _RFC3339_DATE_TIME.fullmatch(value) is None:
            return False
        normalized = value.replace("t", "T").replace("z", "Z")
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    return checker


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = _decode(path.read_bytes())
    except (_DuplicateName, _MalformedEncoding, _NonNfc) as error:
        raise UniversalDenialContractError(f"E_STRICT_JSON:{path.name}") from error
    if not isinstance(value, dict):
        raise UniversalDenialContractError(f"E_JSON_OBJECT:{path.name}")
    return value


def _decode(raw: bytes) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _MalformedEncoding
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise _MalformedEncoding from error
    _validate_unicode(value)
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateName
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise _MalformedEncoding


def _validate_unicode(value: object) -> None:
    if isinstance(value, str):
        for character in value:
            codepoint = ord(character)
            if (
                0xD800 <= codepoint <= 0xDFFF
                or 0xFDD0 <= codepoint <= 0xFDEF
                or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}
                or codepoint == 0xFEFF
            ):
                raise _MalformedEncoding
        if unicodedata.normalize("NFC", value) != value:
            raise _NonNfc
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_unicode(key)
            _validate_unicode(child)
    elif isinstance(value, list):
        for child in value:
            _validate_unicode(child)


def _shape_scan(record: object, limits: Mapping[str, int]) -> None:
    if not isinstance(record, dict):
        raise _Violation("E_SHAPE", "SHAPE", (), fixed_location="ROOT_SHAPE")
    node_count = 0

    def visit(value: object, depth: int, path: tuple[str | int, ...]) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > limits["maximum_total_nodes"] or depth > limits["maximum_depth"]:
            raise _Violation("E_SHAPE", "SHAPE", path)
        if isinstance(value, dict):
            if len(value) > limits["maximum_object_properties"]:
                raise _Violation("E_SHAPE", "SHAPE", path)
            for key in sorted(value, key=lambda item: item.encode("utf-8")):
                if len(key.encode("utf-8")) > limits["maximum_string_utf8_bytes"]:
                    raise _Violation("E_SHAPE", "SHAPE", (*path, key))
                visit(value[key], depth + 1, (*path, key))
        elif isinstance(value, list):
            if len(value) > limits["maximum_array_items"]:
                raise _Violation("E_SHAPE", "SHAPE", path)
            for index, child in enumerate(value):
                visit(child, depth + 1, (*path, index))
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > limits["maximum_string_utf8_bytes"]:
                raise _Violation("E_SHAPE", "SHAPE", path)
        elif (
            isinstance(value, float)
            and not math.isfinite(value)
            or value is not None
            and not isinstance(value, (bool, int, float))
        ):
            raise _Violation("E_SHAPE", "SHAPE", path)

    visit(record, 0, ())


def _walk_names(
    value: object, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], str, object]]:
    if isinstance(value, dict):
        for name in sorted(value, key=lambda item: item.encode("utf-8")):
            child_path = (*path, name)
            child = value[name]
            yield child_path, name, child
            yield from _walk_names(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_names(child, (*path, index))


def _walk_string_values(
    value: object, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for name in sorted(value, key=lambda item: item.encode("utf-8")):
            yield from _walk_string_values(value[name], (*path, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_string_values(child, (*path, index))


def _find_anchor(value: object, anchor: str) -> Iterator[object]:
    if isinstance(value, dict):
        if value.get("$anchor") == anchor:
            yield value
        for child in value.values():
            yield from _find_anchor(child, anchor)
    elif isinstance(value, list):
        for child in value:
            yield from _find_anchor(child, anchor)


def _deduplicate_nodes(nodes: Sequence[_SchemaNode]) -> tuple[_SchemaNode, ...]:
    seen: set[tuple[str, int]] = set()
    result: list[_SchemaNode] = []
    for node in nodes:
        marker = (node.document_id, id(node.schema))
        if marker not in seen:
            seen.add(marker)
            result.append(node)
    return tuple(result)


def _ascii_lower(value: str) -> str:
    return value.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def _string_tuple(source: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = source.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UniversalDenialContractError("E_UNIVERSAL_DENIAL_POLICY_DRIFT")
    return tuple(cast(list[str], value))


def _string_set(source: Mapping[str, object], key: str) -> set[str]:
    return set(_string_tuple(source, key))


def _character_class_count(value: str) -> int:
    return sum(
        (
            any(character.islower() for character in value),
            any(character.isupper() for character in value),
            any(character.isdigit() for character in value),
            any(not character.isalnum() for character in value),
        )
    )


def _shannon_bits_per_byte(value: bytes) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _location_code(path: Sequence[str | int]) -> str:
    components = ["ROOT"] if len(path) == 1 else []
    components.extend(str(component) for component in path)
    raw = "_".join(components) if components else "ROOT"
    normalized = re.sub(r"[^A-Z0-9]+", "_", _ascii_lower(raw).upper()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"ROOT_{normalized or 'VALUE'}"
    return normalized[:96].rstrip("_")


def _build_receipt(
    identity: DenialReceiptIdentity, violation: _Violation, location: str
) -> dict[str, object]:
    return {
        "schema_version": "universal-denial-receipt/v1",
        "receipt_id": identity.receipt_id,
        "attempt_id": identity.attempt_id,
        "input_class": identity.input_class,
        "scanner_disposition": violation.disposition,
        "violation_class": violation.violation_class,
        "location_code": location,
        "matched_bytes_recorded": False,
        "candidate_bytes_hashed": False,
        "sanitized_record_projected": False,
        "artifact_written": False,
        "log_written": False,
        "indexeddb_written": False,
        "sqlite_written": False,
        "fixture_emitted": False,
        "report_emitted": False,
        "replay_artifact_emitted": False,
        "export_emitted": False,
        "safety_stop": True,
        "production_authority": "NONE",
    }


def _object_list(source: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = source.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise UniversalDenialContractError("E_VECTOR_SHAPE")
    return cast(list[dict[str, object]], value)


def _vector_bases(data: Mapping[str, object]) -> dict[str, dict[str, object]]:
    bases: dict[str, dict[str, object]] = {}
    for key in ("valid_records", "semantic_bases", "valid_capabilities"):
        for base in _object_list(data, key) if key in data else []:
            case_id = base.get("case_id")
            if not isinstance(case_id, str) or case_id in bases:
                raise UniversalDenialContractError("E_VECTOR_BASE_ID")
            bases[case_id] = base
    return bases


def _base_candidate(
    case: Mapping[str, object], bases: Mapping[str, dict[str, object]]
) -> dict[str, object]:
    base_id = case.get("base_case_id")
    if not isinstance(base_id, str) or base_id not in bases:
        raise UniversalDenialContractError("E_VECTOR_BASE_ID")
    return copy.deepcopy(bases[base_id])


def _patched_candidate(
    case: Mapping[str, object], bases: Mapping[str, dict[str, object]]
) -> dict[str, object]:
    candidate = _base_candidate(case, bases)
    operations = case.get("operations")
    if not isinstance(operations, list) or not operations:
        raise UniversalDenialContractError("E_JSON_PATCH")
    for operation in operations:
        if not isinstance(operation, dict):
            raise UniversalDenialContractError("E_JSON_PATCH")
        _apply_patch_operation(candidate, operation)
    return candidate


def _apply_patch_operation(document: object, operation: Mapping[str, object]) -> None:
    op = operation.get("op")
    path = operation.get("path")
    if not isinstance(op, str) or not isinstance(path, str):
        raise UniversalDenialContractError("E_JSON_PATCH")
    if op == "test":
        if not _json_equal(_pointer_value(document, path), operation.get("value")):
            raise UniversalDenialContractError("E_JSON_PATCH_TEST")
        return
    if op in {"copy", "move"}:
        source = operation.get("from")
        if not isinstance(source, str):
            raise UniversalDenialContractError("E_JSON_PATCH")
        value = copy.deepcopy(_pointer_value(document, source))
        if op == "move":
            _remove_pointer(document, source)
    elif op in {"add", "replace"}:
        value = copy.deepcopy(operation.get("value"))
    elif op == "remove":
        _remove_pointer(document, path)
        return
    else:
        raise UniversalDenialContractError("E_JSON_PATCH")
    parent, component = _pointer_parent(document, path)
    if isinstance(parent, dict):
        if op == "replace" and component not in parent:
            raise UniversalDenialContractError("E_JSON_PATCH")
        parent[component] = value
    elif isinstance(parent, list):
        if component == "-" and op in {"add", "copy", "move"}:
            parent.append(value)
            return
        index = _array_index(component, len(parent), allow_end=op in {"add", "copy", "move"})
        if op in {"add", "copy", "move"}:
            parent.insert(index, value)
        else:
            parent[index] = value
    else:
        raise UniversalDenialContractError("E_JSON_PATCH")


def _pointer_parts(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise UniversalDenialContractError("E_JSON_POINTER")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _pointer_parent(document: object, pointer: str) -> tuple[object, str]:
    parts = _pointer_parts(pointer)
    if not parts:
        raise UniversalDenialContractError("E_JSON_POINTER")
    value = document
    for part in parts[:-1]:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list):
            value = value[_array_index(part, len(value))]
        else:
            raise UniversalDenialContractError("E_JSON_POINTER")
    return value, parts[-1]


def _pointer_value(document: object, pointer: str) -> object:
    parent, component = _pointer_parent(document, pointer)
    if isinstance(parent, dict) and component in parent:
        return parent[component]
    if isinstance(parent, list):
        return parent[_array_index(component, len(parent))]
    raise UniversalDenialContractError("E_JSON_POINTER")


def _remove_pointer(document: object, pointer: str) -> None:
    parent, component = _pointer_parent(document, pointer)
    if isinstance(parent, dict) and component in parent:
        del parent[component]
        return
    if isinstance(parent, list):
        del parent[_array_index(component, len(parent))]
        return
    raise UniversalDenialContractError("E_JSON_POINTER")


def _array_index(component: str, length: int, *, allow_end: bool = False) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", component):
        raise UniversalDenialContractError("E_JSON_POINTER")
    index = int(component)
    outside = index > length if allow_end else index >= length
    if index < 0 or outside:
        raise UniversalDenialContractError("E_JSON_POINTER")
    return index


def _json_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _record_bytes(candidate: Mapping[str, object]) -> bytes:
    record = candidate.get("record")
    return json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _record_schema_ref(candidate: Mapping[str, object]) -> str:
    schema_ref = candidate.get("record_schema_ref")
    if not isinstance(schema_ref, str):
        raise UniversalDenialContractError("E_VECTOR_SCHEMA_REF")
    return schema_ref


def _validate_fault_injection(fault: Mapping[str, object]) -> None:
    expected = {
        "schema_version": "scanner-fault-injection/v1",
        "fixture_id": "scanner-fault:after-shape-before-name",
        "enabled_only_in": "SYNTHETIC_VECTOR_HARNESS",
        "inject_after_stage": "SHAPE_SCAN",
        "inject_before_stage": "NAME_SCAN",
        "fault_kind": "DETERMINISTIC_SCANNER_INTERNAL_EXCEPTION",
        "occurrence": "FIRST_INVOCATION",
        "candidate_bytes_changed": False,
        "candidate_member_added": False,
        "production_authority": "NONE",
    }
    if fault != expected:
        raise UniversalDenialContractError("E_SCANNER_FAULT_CONTROL")


def _assert_before_side_effects(outcome: UniversalScanOutcome) -> None:
    if set(outcome.completed_stages) & set(SIDE_EFFECT_STAGES):
        raise UniversalDenialContractError("E_DENIAL_AFTER_SIDE_EFFECT_BOUNDARY")
    if outcome.receipt is not None:
        for field in (
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
        ):
            if outcome.receipt[field] is not False:
                raise UniversalDenialContractError("E_DENIAL_SIDE_EFFECT_RECEIPT")
