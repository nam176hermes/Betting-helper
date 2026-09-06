import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { canonicalPreimage, parseStrictJson, } from "../src/canonical.js";
const vectors = parseStrictJson(readFileSync("vendor/hybrid-discovery-v6.3.6/vectors/canonical-hashing-v1.json"));
const registry = parseStrictJson(readFileSync("vendor/hybrid-discovery-v6.3.6/registries/canonical-hash-domains.v1.json"));
void test("strict canonical parser rejects malformed and ambiguous bytes", () => {
    for (const vector of vectors.invalid_vectors.slice(0, 4)) {
        const raw = vector.raw_json_hex;
        assert.ok(raw, vector.vector_id);
        assert.throws(() => parseStrictJson(Buffer.from(raw, "hex")), new RegExp(vector.expected_error, "u"), vector.vector_id);
    }
});
void test("unregistered exclusions and missing registered fields fail closed", () => {
    const unregistered = vectors.invalid_vectors[4];
    const missing = vectors.invalid_vectors[5];
    assert.ok(unregistered && missing);
    const mutatedRegistry = structuredClone(registry);
    const golden = mutatedRegistry.domains.find((entry) => entry.artifact_type === "GoldenASCII");
    assert.ok(golden);
    golden.excluded_json_pointers.push("/a");
    assert.throws(() => canonicalPreimage("GoldenASCII", { a: "alpha", b: "2" }, mutatedRegistry), new RegExp(unregistered.expected_error, "u"));
    assert.ok(missing.artifact_type);
    assert.throws(() => canonicalPreimage(missing.artifact_type ?? "", missing.input, registry), new RegExp(missing.expected_error, "u"));
});
