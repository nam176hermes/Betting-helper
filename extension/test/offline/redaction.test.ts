import assert from "node:assert/strict";
import test from "node:test";
import { projectBeforePersistence } from "../../src/security/redaction.js";
import { validateArtifact } from "../../src/schema-registry.js";
import {raw, schemas, canonicalRegistry} from "./fixtures.js";
const context = {sourceKind: "SYNTHETIC_TEST", runId: raw.discovery_run_id,
 browserRunId: raw.context.browser_run_id, streamId: raw.stream_id, generation: raw.generation,
 allowedKinds: ["TERMINAL"], canonicalRegistry,
 validateRaw: (value: unknown): void => { validateArtifact(value,
  "urn:hybrid-discovery:v6.2:raw-observation:v1", schemas); }};
const project = async (input: unknown): Promise<unknown> =>
 await Reflect.apply(projectBeforePersistence, undefined, [input, context]) as unknown;
void test("valid synthetic input crosses the real projector", async () => {
 const projected = await project(new TextEncoder().encode(JSON.stringify(raw))) as {
  canonicalSanitizedBytes: Uint8Array };
 assert.deepEqual(JSON.parse(new TextDecoder().decode(projected.canonicalSanitizedBytes)), raw);
});
void test("unknown secret field rejected before hash", async () => {
 await assert.rejects(project(new TextEncoder().encode(JSON.stringify({...raw, token: "synthetic-poison"}))),
  /E_OFFLINE_SCHEMA/);
});
void test("accessor is never evaluated", async () => {
 let evaluated = false;
 const input = Object.defineProperty({}, "secret", {get() {evaluated = true; return "synthetic-poison";}});
 await assert.rejects(project(input), /E_OFFLINE_JSON/);
 assert.equal(evaluated, false);
});
void test("wrong source binding and content hash fail closed", async () => {
 await assert.rejects(project({...raw, discovery_run_id: raw.context.browser_run_id}), /E_OFFLINE_SOURCE_BINDING/);
 await assert.rejects(project({...raw, content_hash: "f".repeat(64)}), /E_OFFLINE_CONTENT_HASH/);
});
void test("duplicate keys, BOM and invalid Unicode are rejected", async () => {
 for (const text of ['{"a":1,"a":2}', '\ufeff{}', '{"a":"\\ud800"}', '{"a":"e\\u0301"}']) {
  await assert.rejects(project(new TextEncoder().encode(text)), /E_OFFLINE_JSON/);
 }
});

void test("prototype-named unknown fields cannot disappear during strict parsing", async () => {
 const text = JSON.stringify(raw).replace("{", '{"__proto__":"synthetic-poison",');
 await assert.rejects(project(new TextEncoder().encode(text)), /E_OFFLINE_SCHEMA/);
});
void test("schema rejection precedes access to the hashing registry", async () => {
 let hashed = false;
 const poisonContext = {...context, get canonicalRegistry() { hashed = true; return canonicalRegistry; }};
 await assert.rejects(async () => await Reflect.apply(projectBeforePersistence, undefined,
  [new TextEncoder().encode(JSON.stringify({...raw, unknown: "synthetic-poison"})), poisonContext]) as unknown, /E_OFFLINE_SCHEMA/);
 assert.equal(hashed, false);
});
