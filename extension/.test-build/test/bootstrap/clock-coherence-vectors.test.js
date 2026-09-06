import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseStrictJson } from "../../src/canonical.js";
const vectors = parseStrictJson(readFileSync("vendor/hybrid-discovery-v6.3.6/vectors/clock-coherence-v1.json"));
void test("clock golden mapping and coherence paths reproduce", () => {
    const mapping = vectors.golden_mapping;
    const rawLower = mapping.t3 - mapping.t4;
    const rawUpper = mapping.t2 - mapping.t1;
    const networkRtt = mapping.t4 - mapping.t1 - (mapping.t3 - mapping.t2);
    const padding = mapping.source.resolution_us + mapping.target.resolution_us;
    const lower = rawLower - padding;
    const upper = rawUpper + padding;
    assert.deepEqual(mapping.expected, {
        raw_lower_us: rawLower,
        raw_upper_us: rawUpper,
        network_rtt_us: networkRtt,
        padding_us: padding,
        offset_interval_us: [lower, upper],
        offset_midpoint_us: lower + (upper - lower) / 2,
        base_uncertainty_us: (upper - lower) / 2,
        accepted: true,
    });
    assert.deepEqual(vectors.coherence_state_machine.states, [
        "OPEN",
        "SHOCKED_CLOSED",
        "WAITING_FOR_RESNAPSHOT",
        "NEW_EPOCH_PENDING",
        "NEW_EPOCH_OPEN",
    ]);
    assert.equal(vectors.coherence_state_machine.required_path.length, 4);
    assert.equal(vectors.candidate_acceptance_negative_vectors.length, 4);
    assert.ok(vectors.candidate_acceptance_negative_vectors.every((vector) => vector.expected_state === "WAITING_FOR_RESNAPSHOT"));
    assert.equal(vectors.release_negative_vectors.length, 19);
    assert.equal(vectors.release_negative_vectors.find((vector) => vector.id === "RELEASE-NEG-09-MAPPING-CLOSED")?.expected_state, "NEW_EPOCH_PENDING");
});
