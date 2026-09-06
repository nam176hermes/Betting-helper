import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
export const testSecurityBoundary = () => {
    const vectors = {
        allow: "SEC_CDP_REACHABILITY-ALLOW",
        deny: "SEC_CDP_REACHABILITY-DENY",
        mutate: "SEC_CDP_REACHABILITY-MUTATE",
    };
    assert.deepEqual(verifyCapabilityGraph(resolve("extension/src")), [], vectors.allow);
    for (const [name, source] of [
        [vectors.deny, "chrome.debugger.sendCommand(target,'Runtime.evaluate',{})"],
        [vectors.mutate, "chrome.debugger.sendCommand(target,'Network.enable',{maxPostDataSize:1})"],
    ]) {
        const root = mkdtempSync(resolve(tmpdir(), "sec-cdp-"));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
};
void test("CDP reachability allows only the pinned bounded graph", testSecurityBoundary);
