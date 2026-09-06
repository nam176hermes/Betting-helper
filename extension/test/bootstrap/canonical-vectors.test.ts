import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  canonicalContentHash,
  canonicalPreimage,
  type CanonicalRegistry,
  parseStrictJson,
} from "../../src/canonical.js";

interface CanonicalVector {
  readonly artifact_type: string;
  readonly domain_hex: string;
  readonly equivalent_raw_json_hex?: readonly string[];
  readonly input: unknown;
  readonly jcs_utf8_hex: string;
  readonly preimage_hex: string;
  readonly sha256: string;
  readonly vector_id: string;
}

interface CanonicalVectors {
  readonly valid_vectors: readonly CanonicalVector[];
}

const vendor = "vendor/hybrid-discovery-v6.3.6";
const registry = parseStrictJson(
  readFileSync(`${vendor}/registries/canonical-hash-domains.v1.json`),
) as CanonicalRegistry;
const vectors = parseStrictJson(
  readFileSync(`${vendor}/vectors/canonical-hashing-v1.json`),
) as CanonicalVectors;

const hex = (value: Uint8Array): string => Buffer.from(value).toString("hex");

void test("JCS vectors reproduce bytes and digests in TypeScript", async () => {
  for (const vector of vectors.valid_vectors) {
    const domain = registry.domains.find(
      (entry) => entry.artifact_type === vector.artifact_type,
    );
    assert.ok(domain, vector.vector_id);
    assert.equal(hex(new TextEncoder().encode(domain.domain)), vector.domain_hex, vector.vector_id);
    const preimage = canonicalPreimage(vector.artifact_type, vector.input, registry);
    assert.equal(hex(preimage), vector.preimage_hex, vector.vector_id);
    assert.equal(
      hex(preimage.slice(vector.domain_hex.length / 2)),
      vector.jcs_utf8_hex,
      vector.vector_id,
    );
    assert.equal(
      await canonicalContentHash(vector.artifact_type, vector.input, registry),
      vector.sha256,
      vector.vector_id,
    );
    for (const raw of vector.equivalent_raw_json_hex ?? []) {
      assert.equal(
        await canonicalContentHash(
          vector.artifact_type,
          parseStrictJson(Buffer.from(raw, "hex")),
          registry,
        ),
        vector.sha256,
        vector.vector_id,
      );
    }
  }
});
