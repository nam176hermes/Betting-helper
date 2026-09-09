import assert from "node:assert/strict";
import test from "node:test";
import { Spool } from "../../src/spool.js";
import { canonicalContentHash } from "../../src/canonical.js";
import { validateArtifact } from "../../src/schema-registry.js";
import type { PersistableSanitizedObservationV1 } from "../../src/security/redaction.js";
import {raw, schemas, canonicalRegistry} from "./fixtures.js";

void test("forged brand cannot open IndexedDB before schema rejection", async () => {
 let opened = false;
 const descriptor = Object.getOwnPropertyDescriptor(globalThis, "indexedDB");
 Object.defineProperty(globalThis, "indexedDB", {configurable: true, value: {
  open() { opened = true; throw new Error("E_TEST_OPEN"); },
 }});
 try {
  const poisoned = {...raw, unknown: "synthetic-poison"};
  poisoned.content_hash = await canonicalContentHash("RawObservation", poisoned, canonicalRegistry);
  const bytes = new TextEncoder().encode(JSON.stringify(poisoned));
  const options = {browser_run_id: raw.context.browser_run_id, producer_id: raw.clock_context.clock_domain_id,
   stream_id: raw.stream_id, generation: raw.generation, registry: canonicalRegistry,
   validateRaw: (value: unknown): void => {validateArtifact(value, "urn:hybrid-discovery:v6.2:raw-observation:v1", schemas);}};
  const spool = new Spool(options);
  await assert.rejects(spool.append({canonicalSanitizedBytes: bytes,
   validatedRawObservation: {canonicalBytes: bytes}} as PersistableSanitizedObservationV1), /E_SPOOL_SCHEMA/);
  assert.equal(opened, false);
 } finally {
  if (descriptor) Object.defineProperty(globalThis, "indexedDB", descriptor);
  else Reflect.deleteProperty(globalThis, "indexedDB");
 }
});
