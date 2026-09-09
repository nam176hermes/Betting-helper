import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import type {AnySchemaObject} from "ajv/dist/2020.js";
import {AuthenticatedLoopback} from "../../src/security/loopback.js";
import {Spool} from "../../src/spool.js";
import {validateArtifact} from "../../src/schema-registry.js";
import {schemas, raw, canonicalRegistry} from "./fixtures.js";
const all = [...schemas, ...["context", "frame"].map(name =>
 JSON.parse(readFileSync(`contracts/offline_slice/v1/${name}.schema.json`, "utf8")) as AnySchemaObject)];
const validator = (name: string) => (value: unknown): void => {
 validateArtifact(value, `urn:betting-helper:offline-slice:${name}:v1`, all);
};
const context = {
 schema_version: "offline-run-context/v1", source_kind: "SYNTHETIC_TEST",
 run_id: raw.discovery_run_id, browser_run_id: raw.context.browser_run_id,
 producer_id: raw.clock_context.clock_domain_id, stream_id: raw.stream_id, generation: "0",
 backend_url: "ws://127.0.0.1:8765/offline", allowed_extension_origin: "chrome-extension://" + "a".repeat(32),
 max_duration_seconds: 600, max_frame_bytes: 262144, max_raw_bytes: 65536, max_batch_records: 32,
 normal_spool_limit_bytes: "133169152", code_sha256: "a".repeat(64), vendor_sha256: "a".repeat(64),
 schema_lock_sha256: "a".repeat(64), scenario_sha256: "a".repeat(64),
 live_authority: false, provider_authority: false, money_authority: false,
};
const options = {
 context, spool: new Spool({browser_run_id: context.browser_run_id, producer_id: context.producer_id,
 stream_id: context.stream_id, generation: context.generation, registry: canonicalRegistry,
 validateRaw: (value: unknown): void => {validateArtifact(value, "urn:hybrid-discovery:v6.2:raw-observation:v1", schemas);}}),
 credentials: () => Promise.resolve({sessionId: crypto.randomUUID(), key: crypto.getRandomValues(new Uint8Array(32))}),
 validateContext: validator("context"), validateFrame: validator("frame"),
};
void test("valid offline configuration is inert until start", () => {
 assert.doesNotThrow(() => Reflect.construct(AuthenticatedLoopback, [options]));
});
void test("untrusted context fails before opening a socket", () => {
 for (const mutation of [{backend_url: "wss://example.invalid"}, {live_authority: true}, {unknown: true}]) {
  assert.throws(() => Reflect.construct(AuthenticatedLoopback, [{...options, context: {...context, ...mutation}}]), /E_OFFLINE_CONTEXT/);
 }
});
