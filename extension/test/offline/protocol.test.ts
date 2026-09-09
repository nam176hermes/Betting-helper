import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import type {AnySchemaObject} from "ajv/dist/2020.js";
import {SessionState, encodeFrame, verifyFrame} from "../../src/offline/protocol.js";
import {validateArtifact} from "../../src/schema-registry.js";
import {schemas, raw} from "./fixtures.js";
const all = [...schemas, JSON.parse(readFileSync("contracts/offline_slice/v1/frame.schema.json", "utf8")) as AnySchemaObject];
const validate = (value: unknown): void => {validateArtifact(value, "urn:betting-helper:offline-slice:frame:v1", all);};
const key = Uint8Array.from({length: 32}, (_, i) => i); // Public unit codec vector only.
const clientNonce = Buffer.alloc(32).toString("base64url");
const serverNonce = Buffer.alloc(32, 1).toString("base64url");

void test("nonce handshake then exact authenticated counters", async () => {
 const client = new SessionState(raw.discovery_run_id, raw.discovery_run_id, "CLIENT", validate);
 const backend = new SessionState(raw.discovery_run_id, raw.discovery_run_id, "BACKEND", validate);
 const body = {run_id: raw.discovery_run_id, client_nonce: clientNonce, server_nonce: serverNonce};
 await verifyFrame(await client.send("HELLO", {run_id: body.run_id, client_nonce: clientNonce}, key), key, backend);
 await verifyFrame(await backend.send("WELCOME", body, key), key, client);
 await verifyFrame(await client.send("READY", body, key), key, backend);
 assert.equal(backend.ready, false);
 await verifyFrame(await backend.send("READY_ACK", body, key), key, client);
 assert.equal(client.ready && backend.ready, true);
 const ping = await client.send("PING", {nonce: clientNonce, monotonic_us: "1"}, key);
 await verifyFrame(ping, key, backend);
 await assert.rejects(verifyFrame(ping, key, backend), /E_OFFLINE_SESSION_COUNTER/);
 assert.equal(backend.inCounter, 3n);
});
void test("wrong MAC cannot advance handshake", async () => {
 const backend = new SessionState(raw.discovery_run_id, raw.discovery_run_id, "BACKEND", validate);
 const frame = await encodeFrame({protocol: "BH_OFFLINE_WIRE_V1", session_id: raw.discovery_run_id,
  direction: "CLIENT_TO_BACKEND", counter: "1", message_type: "HELLO",
  body: {run_id: raw.discovery_run_id, client_nonce: clientNonce}}, key, validate);
 const tampered = JSON.parse(frame) as {mac: string};
 tampered.mac = "0".repeat(64);
 await assert.rejects(verifyFrame(JSON.stringify(tampered), key, backend), /E_OFFLINE_MAC/);
 assert.equal(backend.inCounter, 0n);
});
