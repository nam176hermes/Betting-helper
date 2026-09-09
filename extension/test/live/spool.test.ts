import assert from "node:assert/strict";
import test from "node:test";
import { LiveCaptureSpool } from "../../src/live/spool.js";
import { book, capture, runId, validators } from "./wire.test.js";

void test("live spool rejects wrong source and scope before touching native IndexedDB", async () => {
  const raw = await capture(), b = book();
  const spool = new LiveCaptureSpool({runId, streamId: raw.stream_id, generation: "0", bindingId: b.binding_id,
    documentEpoch: b.document_epoch, profileHash: b.profile_hash, validate: validators.record});
  await assert.rejects(spool.append({...raw, source_kind: "PROVIDER"}), /E_LIVE_RECORD/);
  await assert.rejects(spool.append({...raw, content_hash: "f".repeat(64)}), /E_LIVE_SPOOL_BINDING/);
  assert.throws(() => new LiveCaptureSpool({runId, streamId: raw.stream_id, generation: "-1", bindingId: b.binding_id,
    documentEpoch: b.document_epoch, profileHash: b.profile_hash, validate: validators.record}), /INTEGER/);
  // Successful durability cases are executed in real Chrome by test_live_spool_bridge.py.
});
