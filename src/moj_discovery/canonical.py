import copy
import hashlib
import hmac
import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import rfc8785


class CanonicalError(ValueError):
    pass


def parse_strict_json(raw: bytes) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CanonicalError("MALFORMED_UTF8_OR_JSON")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeError as error:
        raise CanonicalError("MALFORMED_UTF8_OR_JSON") from error
    except json.JSONDecodeError as error:
        raise CanonicalError("MALFORMED_UTF8_OR_JSON") from error
    _validate_unicode(value)
    return value


def _reject_constant(_value: str) -> None:
    raise CanonicalError("MALFORMED_UTF8_OR_JSON")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _validate_unicode(value: object) -> None:
    if isinstance(value, str):
        if str.isascii(value):
            return
        if (
            any(0xD800 <= ord(char) <= 0xDFFF for char in value)
            or unicodedata.normalize("NFC", value) != value
        ):
            raise CanonicalError("NON_NFC_OR_INVALID_UNICODE")
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_unicode(key)
            _validate_unicode(child)
    elif isinstance(value, list):
        for child in value:
            _validate_unicode(child)


def canonical_content_hash(
    artifact_type: str,
    value: object,
    *,
    registry_path: Path | None = None,
    registry_bytes: bytes | None = None,
) -> str:
    return hashlib.sha256(
        canonical_preimage(
            artifact_type, value, registry_path=registry_path, registry_bytes=registry_bytes
        )
    ).hexdigest()


def verify_canonical_content_hash(
    artifact_type: str,
    value: object,
    expected_hash: str,
    *,
    registry_path: Path | None = None,
) -> bool:
    computed = canonical_content_hash(artifact_type, value, registry_path=registry_path)
    if not hmac.compare_digest(computed, expected_hash):
        raise CanonicalError("CONTENT_HASH_MISMATCH")
    return True


@lru_cache(maxsize=8)
def _domain(registry_bytes: bytes, artifact_type: str) -> tuple[str, tuple[str, ...]]:
    # Cache immutable results by complete source bytes, never pathname or mtime.
    registry = parse_strict_json(registry_bytes)
    assert isinstance(registry, dict)
    matches = [entry for entry in registry["domains"] if entry["artifact_type"] == artifact_type]
    if len(matches) != 1:
        raise CanonicalError("UNSUPPORTED_VERSION_OR_ALGORITHM")
    entry = matches[0]
    _validate_registered_exclusions(
        artifact_type,
        cast(list[str], entry["excluded_json_pointers"]),
        cast(dict[str, Any], registry),
    )
    domain = entry["domain"]
    if not isinstance(domain, str):
        raise CanonicalError("SCHEMA_INVALID")
    return domain, tuple(entry["excluded_json_pointers"])


def canonical_preimage(
    artifact_type: str,
    value: object,
    *,
    registry_path: Path | None = None,
    registry_bytes: bytes | None = None,
) -> bytes:
    registry_path = registry_path or Path(
        "vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json"
    )
    domain, exclusions = _domain(
        registry_path.read_bytes() if registry_bytes is None else registry_bytes, artifact_type
    )
    projected = copy.deepcopy(value)
    if not isinstance(projected, dict):
        raise CanonicalError("SCHEMA_INVALID")
    for pointer in exclusions:
        if pointer.count("/") != 1:
            raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
        key = pointer[1:].replace("~1", "/").replace("~0", "~")
        if key not in projected:
            raise CanonicalError("SCHEMA_INVALID_BEFORE_CANONICAL_HASH")
        del projected[key]
    _validate_unicode(projected)
    canonical = rfc8785.dumps(projected)
    assert isinstance(canonical, bytes)
    return domain.encode() + canonical


def _validate_registered_exclusions(
    artifact_type: str, exclusions: list[str], registry: dict[str, Any]
) -> None:
    classes = registry.get("domain_validation_classes")
    groups = registry.get("schema_binding_groups")
    if not isinstance(classes, list) or not isinstance(groups, list):
        raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
    class_matches = [
        item
        for item in classes
        if isinstance(item, dict)
        and isinstance(item.get("artifact_types"), list)
        and artifact_type in item["artifact_types"]
    ]
    if len(class_matches) != 1:
        raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
    class_id = class_matches[0].get("class_id")
    if class_id == "GOVERNED_NO_EXCLUSION":
        if exclusions:
            raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
        return
    if class_id != "SCHEMA_GATED_SELF_HASH":
        raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
    group_matches = [
        item
        for item in groups
        if isinstance(item, dict)
        and isinstance(item.get("artifact_types"), list)
        and artifact_type in item["artifact_types"]
    ]
    if len(group_matches) != 1:
        raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
    registered = group_matches[0].get("required_excluded_json_pointers")
    if not isinstance(registered, list) or exclusions != registered:
        raise CanonicalError("UNREGISTERED_HASH_EXCLUSION")
