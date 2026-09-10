import assert from "node:assert/strict";
import {test} from "node:test";
import {ageLabel, exactLink, selectedBook} from "../../src/live/panel.js";
import type {Projection} from "../../src/live/panel.js";

void test("unknown clocks, absent horizons and unsafe links remain unavailable", () => {
  assert.equal(ageLabel(null), "UNKNOWN");
  assert.equal(ageLabel(35000000), "35s");
  assert.equal(exactLink("javascript:alert(1)"), null);
  assert.equal(exactLink("https://u:p@example.invalid/match"), null);
  assert.equal(exactLink("https://example.invalid/match/101"), "https://example.invalid/match/101");
  const snapshot = {binding: {binding_id: "B", revision: "1"}, books: [
    {binding_id: "A", binding_revision: "1", horizon: "FT"},
    {binding_id: "B", binding_revision: "0", horizon: "H1"},
  ]} as unknown as Projection;
  for (const horizon of ["FT", "H1", "H2"] as const) assert.equal(selectedBook(snapshot, horizon), null);
});

import {captureObservationId, parsePairingTicket} from "../../src/live/background.js";
void test("local tickets are closed and observation identities match backend UUIDv5", async () => {
  const ticket = {version: 1, runId: "11111111-1111-4111-8111-111111111119", durationSeconds: 120,
    ui: {sessionId: "11111111-1111-4111-8111-111111111111", key: Buffer.alloc(32, 1).toString("base64url")},
    capture: {sessionId: "22222222-2222-4222-8222-222222222222", key: Buffer.alloc(32, 2).toString("base64url")}};
  assert.equal(parsePairingTicket(JSON.stringify(ticket))[1].role, "CAPTURE_PRODUCER");
  for (const changed of [{...ticket, url: "https://outside.invalid"}, {...ticket, durationSeconds: 7201},
    {...ticket, capture: ticket.ui}, {...ticket, ui: {...ticket.ui, key: "secret"}}]) {
    assert.throws(() => parsePairingTicket(JSON.stringify(changed)), /E_PAIRING_TICKET/);
  }
  assert.equal(await captureObservationId("a".repeat(64), "FT"), "bb7dc095-0915-5159-9ad7-7ce1e585c5a8");
});
