import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
import { verifyCurrentSurface } from "./current-surface.js";
import { book, capture, validators } from "../live/wire.test.js";
import { liveEventHash } from "../../src/live/protocol.js";
import { LiveCaptureSpool } from "../../src/live/spool.js";

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

void test("nested commands reject before live hashing, logging or IndexedDB access", async t => {
  const event = await capture(), market = book();
  const digest = t.mock.method(crypto.subtle, "digest");
  await liveEventHash(event, validators.record);
  assert.ok(digest.mock.callCount() > 0); // The same probe sees the allowed control.
  digest.mock.resetCalls();
  let opens = 0;
  const original = Object.getOwnPropertyDescriptor(globalThis, "indexedDB");
  Object.defineProperty(globalThis, "indexedDB", {configurable: true,
    value: {open: () => { opens++; throw Error("TEST_ONLY_DB_OPEN"); }}});
  t.after(() => {
    if (original) Object.defineProperty(globalThis, "indexedDB", original);
    else Reflect.deleteProperty(globalThis, "indexedDB");
  });
  const logs = ["log", "info", "warn", "error", "debug"].map(name =>
    t.mock.method(console, name as "log", () => undefined));
  for (const deep of [false, true]) {
    const mutated = structuredClone(event);
    const command = {method: "Page.navigate", params: {url: "https://example.invalid/"}};
    if (deep) {
      const home = (mutated.payload["selections"] as Record<string, Record<string, unknown>>)["HOME"];
      assert.ok(home);
      home["command"] = command;
    } else mutated.payload["command"] = command;
    const spool = new LiveCaptureSpool({runId: event.run_id, streamId: event.stream_id,
      generation: event.generation, bindingId: market.binding_id, documentEpoch: market.document_epoch,
      profileHash: market.profile_hash, validate: validators.record});
    await assert.rejects(liveEventHash(mutated, validators.record), {message: "E_LIVE_RECORD"});
    await assert.rejects(spool.append(mutated), {message: "E_LIVE_RECORD"});
    assert.equal(digest.mock.callCount(), 0);
    assert.equal(opens, 0);
    assert.ok(logs.every(log => log.mock.callCount() === 0));
  }
});
