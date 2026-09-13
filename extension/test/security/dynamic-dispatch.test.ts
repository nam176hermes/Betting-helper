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
  for (const [name, source, expected] of [
    [vectors.deny, "const send=chrome.debugger.sendCommand;send(target,method,{})", "E_PRIVILEGED_API_ALIAS"],
    [vectors.mutate, "chrome.debugger['send'+'Command'](target,'Runtime.evaluate',{})", "E_CDP_METHOD_DENIED"],
  ] as const) {
    const root = mkdtempSync(resolve(tmpdir(), "sec-dispatch-"));
    writeFileSync(resolve(root, "fixture.ts"), source);
    assert.ok(verifyCapabilityGraph(root).includes(expected), `${name}: ${expected}`);
  }
  const root = mkdtempSync(resolve(tmpdir(), "sec-reexport-"));
  writeFileSync(resolve(root, "entry.ts"), "import {dispatch} from './barrel.js'; dispatch(target,method,{});");
  writeFileSync(resolve(root, "barrel.ts"), "export {dispatch} from './dispatcher.js';");
  const dispatcher = resolve(root, "dispatcher.ts");
  writeFileSync(dispatcher, "export const dispatch = () => undefined;");
  assert.deepEqual(verifyCapabilityGraph(root), [], "local re-export control");
  writeFileSync(dispatcher, "export const dispatch = chrome.debugger.sendCommand;");
  assert.ok(verifyCapabilityGraph(root).includes("E_PRIVILEGED_API_ALIAS"), "re-exported forbidden dispatcher");
};

void test("dynamic privileged dispatch cannot escape the closed graph", testSecurityBoundary);
