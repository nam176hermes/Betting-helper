import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import type { AnySchemaObject } from "ajv/dist/2020.js";
import { projectBeforePersistence } from "../../src/security/redaction.js";
import { validateArtifact } from "../../src/schema-registry.js";
import type { CanonicalRegistry } from "../../src/canonical.js";
const vendor = "vendor/hybrid-discovery-v6.3.6";
const schemas = readdirSync(`${vendor}/schemas`).filter(n => n.endsWith(".json"))
.map(n => JSON.parse(readFileSync(`${vendor}/schemas/${n}`, "utf8")) as AnySchemaObject);
const canonicalRegistry = JSON.parse(readFileSync(`${vendor}/registries/canonical-hash-domains.v1.json`, "utf8")) as CanonicalRegistry;
// Synthetic accounting input, never observed football data or an authorization receipt.
const raw = {
  "schema_version": "raw-observation/v1",
  "raw_observation_id": "observation:ef134f2a180ba05de91ab32d2976f51de13b68d823ea784171b1b0dafee67be4",
  "observation_kind": "TERMINAL",
  "pack_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "build_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "implementation_baseline_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "capability_manifest_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "discovery_run_id": "00000000-0000-4000-8000-000000000010",
  "run_receipt_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "stream_id": "00000000-0000-4000-8000-000000000002",
  "generation": "0",
  "sequence": "1",
  "context": {
    "context_kind": "RUN_BOUND_NOT_DOCUMENT",
    "browser_run_id": "00000000-0000-4000-8000-000000000001",
    "browser_boot_id": "00000000-0000-4000-8000-000000000001",
    "binding_reason": "TERMINAL_ACCOUNTING"
  },
  "clock_context": {
    "clock_domain_id": "00000000-0000-4000-8000-000000000003",
    "boot_id": "00000000-0000-4000-8000-000000000001",
    "unit": "MICROSECOND",
    "monotonic_value": "1",
    "resolution_us": "1",
    "owner": "BACKEND",
    "mapping_id": "NOT_APPLICABLE",
    "mapping_status": "NOT_APPLICABLE"
  },
  "sanitizer_version": "sanitizer/v1",
  "content_hash": "c179fe89b16558a24ffcc15cd6e0ff0aabae786c6fa37d267db6b1d937d05b43",
  "production_authority": "NONE",
  "facts": {
    "terminal_code": "MANUAL_STOP",
    "final_generation": "0",
    "final_sequence": "1",
    "observation_count": "1",
    "gap_count": "0",
    "safety_disposition": "PARTIAL_EVIDENCE_ONLY"
  }
};
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
