import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
export const testSecurityBoundary = () => {
    const vectors = {
        allow: "SEC_OUTBOUND_NETWORK-ALLOW",
        deny: "SEC_OUTBOUND_NETWORK-DENY",
        mutate: "SEC_OUTBOUND_NETWORK-MUTATE",
    };
    assert.deepEqual(verifyCapabilityGraph(resolve("extension/src")), [], vectors.allow);
    for (const [name, source] of [
        [vectors.deny, "fetch('https://example.invalid')"],
        [vectors.mutate, "new WebSocket(userUrl)"],
    ]) {
        const root = mkdtempSync(resolve(tmpdir(), "sec-network-"));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
};
void test("generic outbound network paths are absent from the pinned graph", testSecurityBoundary);
