import json
import shutil
import subprocess
from pathlib import Path

import pytest

from moj_discovery.canonical import (
    CanonicalError,
    canonical_content_hash,
    parse_strict_json,
    verify_canonical_content_hash,
)

ROOT = Path(__file__).parents[2]


def test_security_boundary() -> None:
    vectors_by_kind = {
        "allow": "SEC_CANONICAL_HASHING-ALLOW",
        "deny": "SEC_CANONICAL_HASHING-DENY",
        "mutate": "SEC_CANONICAL_HASHING-MUTATE",
    }
    vectors = json.loads(
        (ROOT / "vendor/hybrid-discovery-v6.3.6/vectors/canonical-hashing-v1.json").read_text()
    )
    vector = next(item for item in vectors["valid_vectors"] if item["vector_id"] == "CANON-ASCII")
    value = parse_strict_json(b'{"b":"2","a":"alpha"}')
    assert value == vector["input"]
    python_hash = canonical_content_hash(str(vector["artifact_type"]), value)
    assert python_hash == vector["sha256"], vectors_by_kind["allow"]
    script = """
import {readFileSync} from 'node:fs';
import {canonicalContentHash,verifyCanonicalContentHash} from './extension/dist/canonical.js';
const registryPath='./vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json';
const registry=JSON.parse(readFileSync(registryPath,'utf8'));
const value=JSON.parse(process.argv[1]);
const digest=await canonicalContentHash(process.argv[2],value,registry);
await verifyCanonicalContentHash(process.argv[2],value,digest,registry);
try {
  await verifyCanonicalContentHash(process.argv[2],value,'0'.repeat(64),registry);
  process.exit(9);
} catch (error) {
  if (!(error instanceof Error) || error.message !== 'CONTENT_HASH_MISMATCH') throw error;
}
process.stdout.write(digest);
"""
    node = shutil.which("node")
    assert node is not None
    node_hash = subprocess.run(  # noqa: S603 -- fixed script and validated vector input
        [
            node,
            "--input-type=module",
            "--eval",
            script,
            json.dumps(value),
            str(vector["artifact_type"]),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert node_hash == python_hash, vectors_by_kind["allow"]
    changed = canonical_content_hash(str(vector["artifact_type"]), {"a": "altered", "b": "2"})
    assert changed != vector["sha256"], vectors_by_kind["mutate"]
    assert verify_canonical_content_hash(str(vector["artifact_type"]), value, str(vector["sha256"]))
    with pytest.raises(CanonicalError, match="CONTENT_HASH_MISMATCH"):
        verify_canonical_content_hash(str(vector["artifact_type"]), value, "0" * 64)
    with pytest.raises(CanonicalError, match="DUPLICATE_JSON_KEY"):
        parse_strict_json(b'{"a":1,"a":2}')
    assert vectors_by_kind["deny"]
