import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
import { verifyCurrentSurface } from "./current-surface.js";

export const testSecurityBoundary = (): void => {
  const vectors = {
    allow: "SEC_CDP_REACHABILITY-ALLOW",
    deny: "SEC_CDP_REACHABILITY-DENY",
    mutate: "SEC_CDP_REACHABILITY-MUTATE",
  };
  assert.doesNotThrow(verifyCurrentSurface, vectors.allow);
  const root = mkdtempSync(resolve(tmpdir(), "sec-cdp-"));
  mkdirSync(resolve(root, "src/security"), { recursive: true });
  const broker = resolve(root, "src/security/cdp-broker.ts");
  const bounded = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
  for (const [name, method, parameters, expected] of [
    [vectors.allow, "Network.enable", bounded, []],
    [vectors.allow, "Network.disable", "{}", []],
    [vectors.deny, "Runtime.evaluate", "{}", ["E_CDP_METHOD_DENIED"]],
    [vectors.deny, "Input.dispatchMouseEvent", "{}", ["E_CDP_DOMAIN_DENIED"]],
    [vectors.deny, "Page.navigate", "{}", ["E_CDP_METHOD_DENIED"]],
    [vectors.mutate, "Network.enable", "{maxPostDataSize:1}", ["E_CDP_PARAMETER_MISMATCH"]],
  ] as const) {
    writeFileSync(broker, `export const sendLiteralCommand = (authorization: DiscoveryRunAuthorization) => {
      const selectedTabId = authorization.browser_binding.tab_id;
      chrome.debugger.sendCommand({tabId:selectedTabId}, ${JSON.stringify(method)}, ${parameters});
    };`);
    assert.deepEqual(verifyCapabilityGraph(root), expected, `${name}: ${method}`);
  }
};

void test("CDP reachability allows only the pinned bounded graph", testSecurityBoundary);
