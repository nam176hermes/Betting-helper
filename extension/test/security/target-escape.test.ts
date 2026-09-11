import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
import { verifyCurrentSurface } from "./current-surface.js";

export const testSecurityBoundary = (): void => {
  const vectors = {
    allow: "SEC_TARGET_ESCAPE-ALLOW",
    deny: "SEC_TARGET_ESCAPE-DENY",
    mutate: "SEC_TARGET_ESCAPE-MUTATE",
  };
  assert.doesNotThrow(verifyCurrentSurface, vectors.allow);
  for (const [name, source] of [
    [vectors.deny, "chrome.debugger.attach({targetId},'1.3')"],
    [vectors.mutate, "chrome.debugger.sendCommand({sessionId},'Network.disable',{})"],
  ] as const) {
    const root = mkdtempSync(resolve(tmpdir(), "sec-target-"));
    writeFileSync(resolve(root, "fixture.ts"), source);
    assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
  }
};

void test("target and child-session escapes are rejected before attach", testSecurityBoundary);
