import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createHmac } from "node:crypto";
import { Ajv2020, type AnySchemaObject } from "ajv/dist/2020.js";
import addFormatsImport, { type FormatsPlugin } from "ajv-formats";
import { canonicalBytes } from "../../src/canonical.js";
import { LiveSession, encodeFrame, liveEventHash, type LiveRole, type Validators } from "../../src/live/protocol.js";
import type { LiveEvent, MarketBook } from "../../src/live/contracts.js";

const ajv = new Ajv2020({strict: false, allErrors: true});
(addFormatsImport as unknown as FormatsPlugin)(ajv);
for (const name of ["records", "wire"]) ajv.addSchema(JSON.parse(readFileSync(`contracts/live_readonly/v1/${name}.schema.json`, "utf8")) as AnySchemaObject);
export const validators: Validators = {
  record: (value, kind) => Boolean(ajv.getSchema(`urn:betting-helper:live-records:v1#/$defs/${kind}`)?.(value)),
  frame: value => Boolean(ajv.getSchema("urn:betting-helper:live-wire:v1")?.(value)),
};
export const runId = "11111111-1111-4111-8111-111111111119";
const sid = "22222222-2222-4222-8222-222222222229";
const key = Uint8Array.from({length: 32}, (_, i) => i); // Public codec vector, never an API key.
const clientNonce = Buffer.alloc(32, 1).toString("base64url"), serverNonce = Buffer.alloc(32, 2).toString("base64url");
export const book = (): MarketBook => ({binding_id: "11111111-1111-4111-8111-111111111111", binding_revision: "1",
  operator_fixture_id: "SYNTHETIC-101", market_id: "SYNTHETIC-FT", horizon: "FT", settlement_basis: "NORMAL_TIME_INCLUDING_STOPPAGE",
  selections: {HOME: {selection_id: "SYNTHETIC-HOME", decimal_odds: "2.10"}, DRAW: {selection_id: "SYNTHETIC-DRAW", decimal_odds: "3.20"}, AWAY: {selection_id: "SYNTHETIC-AWAY", decimal_odds: "3.40"}},
  market_status: "OPEN", capture_revision: "1", native_revision: null, observed_at_utc: "2026-09-09T18:00:00Z", browser_mono_us: "1000000",
  clock_domain_id: sid, source_updated_at: null, operator_score: {home: 0, away: 0}, operator_period: "H1", capture_evidence_tier: "DISPLAY_COHERENT",
  profile_hash: "a".repeat(64), document_epoch: "33333333-3333-4333-8333-333333333333", quality_flags: ["SYNTHETIC"]});
export async function capture(): Promise<LiveEvent> {
  const b = book();
  const event: LiveEvent = {protocol: "BH_LIVE_READONLY_V1", run_id: runId, source_kind: "OPERATOR", stream_id: sid,
    generation: "0", sequence: "1", observation_id: "44444444-4444-4444-8444-444444444444", observed_at_utc: b.observed_at_utc,
    received_mono_us: "1000000", previous_hash: "0".repeat(64), content_hash: "0".repeat(64), payload_type: "MarketBook", payload: {...b}};
  event.content_hash = await liveEventHash(event, validators.record); return event;
}
async function handshake(role: LiveRole): Promise<[LiveSession, LiveSession]> {
  const c = new LiveSession(sid, runId, "CLIENT", role, validators, 120, () => 0);
  const s = new LiveSession(sid, runId, "BACKEND", role, validators, 120, () => 0);
  await s.receive(await c.send("HELLO", {run_id: runId, role, client_nonce: clientNonce}, key), key);
  const body = {run_id: runId, client_nonce: clientNonce, server_nonce: serverNonce};
  await c.receive(await s.send("WELCOME", body, key), key);
  await s.receive(await c.send("READY", body, key), key);
  await c.receive(await s.send("READY_ACK", body, key), key); return [c, s];
}
void test("live codec uses independently calculated Node HMAC and rejects offline domain", async () => {
  const body = {run_id: runId, role: "CAPTURE_PRODUCER", client_nonce: clientNonce};
  const frame = {protocol: "BH_LIVE_WIRE_V1" as const, session_id: sid, direction: "CLIENT_TO_BACKEND" as const, counter: "1", message_type: "HELLO", body};
  const encoded = await encodeFrame(frame, key, validators);
  const expected = createHmac("sha256", key).update("BH-LIVE-WIRE/v1\0").update(canonicalBytes(frame)).digest("hex");
  assert.equal((JSON.parse(encoded) as {mac: string}).mac, expected);
  const server = new LiveSession(sid, runId, "BACKEND", "CAPTURE_PRODUCER", validators, 120, () => 0);
  const bad = {...frame, mac: createHmac("sha256", key).update("BH-OFFLINE-WIRE/v1\0").update(canonicalBytes(frame)).digest("hex")};
  await assert.rejects(server.receive(JSON.stringify(bad), key), /AUTHENTICATION/);
  assert.equal(server.inCounter, 0n);
});
void test("handshake, counters, roles and nested provider injection are enforced", async () => {
  const [client, server] = await handshake("CAPTURE_PRODUCER"), event = await capture();
  const body = {run_id: runId, stream_id: sid, generation: "0", batch_id: crypto.randomUUID(), first_sequence: "1", last_sequence: "1", events: [event]};
  const encoded = await client.send("CAPTURE_BATCH", body, key);
  await server.receive(encoded, key);
  await assert.rejects(server.receive(encoded, key), /COUNTER/);
  const [subscriber] = await handshake("UI_SUBSCRIBER");
  await assert.rejects(subscriber.send("CAPTURE_BATCH", body, key), /ROLE_DENIED/);
  const [producer] = await handshake("CAPTURE_PRODUCER");
  await assert.rejects(producer.send("REFRESH", {run_id: runId, binding_id: book().binding_id}, key), /ROLE_DENIED/);
  await assert.rejects(producer.send("CAPTURE_BATCH", {...body, events: [{...event, source_kind: "PROVIDER"}]}, key), /SCHEMA/);
});
