import json
from pathlib import Path

import pytest

from moj_discovery.canonical import (
    CanonicalError,
    canonical_content_hash,
    canonical_preimage,
    parse_strict_json,
)

VECTORS = json.loads(
    Path("vendor/hybrid-discovery-v6.3.6/vectors/canonical-hashing-v1.json").read_text()
)


@pytest.mark.parametrize(
    "vector", VECTORS["invalid_vectors"][:4], ids=lambda item: item["vector_id"]
)
def test_invalid_canonical_bytes_are_rejected(vector: dict[str, object]) -> None:
    with pytest.raises(CanonicalError, match=str(vector["expected_error"])):
        parse_strict_json(bytes.fromhex(str(vector["raw_json_hex"])))


@pytest.mark.parametrize("vector", VECTORS["valid_vectors"], ids=lambda item: item["vector_id"])
def test_canonical_hash_vectors(vector: dict[str, object]) -> None:
    preimage = canonical_preimage(str(vector["artifact_type"]), vector["input"])
    assert preimage.hex() == vector["preimage_hex"]
    assert preimage[: len(bytes.fromhex(str(vector["domain_hex"])))] == bytes.fromhex(
        str(vector["domain_hex"])
    )
    assert preimage[len(bytes.fromhex(str(vector["domain_hex"]))) :].hex() == vector["jcs_utf8_hex"]
    assert canonical_content_hash(str(vector["artifact_type"]), vector["input"]) == vector["sha256"]


def test_unregistered_exclusion_is_rejected(tmp_path: Path) -> None:
    registry = json.loads(
        Path("vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json").read_text()
    )
    domain = next(item for item in registry["domains"] if item["artifact_type"] == "GoldenASCII")
    domain["excluded_json_pointers"] = ["/a"]
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    vector = VECTORS["invalid_vectors"][4]
    with pytest.raises(CanonicalError, match=str(vector["expected_error"])):
        canonical_preimage("GoldenASCII", {"a": "alpha", "b": "2"}, registry_path=registry_path)


def test_missing_registered_excluded_field_is_rejected() -> None:
    vector = VECTORS["invalid_vectors"][5]
    with pytest.raises(CanonicalError, match=str(vector["expected_error"])):
        canonical_preimage(str(vector["artifact_type"]), vector["input"])
