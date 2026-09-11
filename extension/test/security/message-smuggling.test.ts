import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
import { verifyCurrentSurface } from "./current-surface.js";

export const testSecurityBoundary = (): void => {
  const vectors = {
    allow: "SEC_MESSAGE_SMUGGLING-ALLOW",
    deny: "SEC_MESSAGE_SMUGGLING-DENY",
    mutate: "SEC_MESSAGE_SMUGGLING-MUTATE",
  };
  assert.doesNotThrow(verifyCurrentSurface, vectors.allow);
  for (const [name, source] of [
    [vectors.deny, "window.postMessage({command:'ATTACH'},'*')"],
    [vectors.mutate, "chrome.runtime.onMessage.addListener(message=>executePrivileged(message.command))"],
  ] as const) {
    const root = mkdtempSync(resolve(tmpdir(), "sec-message-"));
    writeFileSync(resolve(root, "fixture.ts"), source);
    assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
  }
};

void test("command-bearing public messages cannot reach privileged sinks", testSecurityBoundary);
