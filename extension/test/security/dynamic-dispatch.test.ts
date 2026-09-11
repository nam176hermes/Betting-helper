import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
import { verifyCurrentSurface } from "./current-surface.js";

export const testSecurityBoundary = (): void => {
  const vectors = {
    allow: "SEC_DYNAMIC_DISPATCH-ALLOW",
    deny: "SEC_DYNAMIC_DISPATCH-DENY",
    mutate: "SEC_DYNAMIC_DISPATCH-MUTATE",
  };
  assert.doesNotThrow(verifyCurrentSurface, vectors.allow);
  for (const [name, source] of [
    [vectors.deny, "const send=chrome.debugger.sendCommand;send(target,method,{})"],
    [vectors.mutate, "chrome.debugger['send'+'Command'](target,'Network.disable',{})"],
  ] as const) {
    const root = mkdtempSync(resolve(tmpdir(), "sec-dispatch-"));
    writeFileSync(resolve(root, "fixture.ts"), source);
    assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
  }
};

void test("dynamic privileged dispatch cannot escape the closed graph", testSecurityBoundary);
