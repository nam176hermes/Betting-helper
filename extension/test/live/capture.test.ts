import assert from "node:assert/strict";
import {test} from "node:test";
import {handleCaptureMessage} from "../../src/live/background.js";

const active = {tabId: 7, documentId: "document-a", exactUrl: "https://example.invalid/match/101",
  captureId: "00000000-0000-4000-8000-000000000001", profileHash: "a".repeat(64),
  bindingRevision: "1", documentEpoch: "00000000-0000-4000-8000-000000000002"};
const message = {kind: "READER_NOTICE", captureId: active.captureId, profileHash: active.profileHash,
  bindingRevision: active.bindingRevision, documentEpoch: active.documentEpoch, code: "DIRTY"};
const sender: chrome.runtime.MessageSender = {id: "extension-id", tab: {id: 7, index: 0,
  pinned: false, highlighted: true, active: true, incognito: false, selected: true,
  windowId: 1, frozen: false, groupId: -1, lastAccessed: 0, discarded: false, autoDiscardable: false}, frameId: 0,
  documentId: "document-a", url: active.exactUrl};
void test("only the bound top-frame document may invalidate its capture", () => {
  assert.ok(sender.tab);
  assert.equal(handleCaptureMessage(message, sender, active, "extension-id"), true);
  for (const changed of [{...sender, frameId: 1}, {...sender, documentId: "document-old"},
    {...sender, id: "other"}, {...sender, url: "https://example.invalid/elsewhere"},
    {...sender, tab: {...sender.tab, id: 8}}]) {
    assert.equal(handleCaptureMessage(message, changed, active, "extension-id"), false);
  }
  for (const changed of [{...message, code: "EXECUTE"}, {...message, code: "CURRENT_DISPLAY_ONLY"},
    {...message, bindingRevision: "2"}, {...message, script: "page source"}]) {
    assert.equal(handleCaptureMessage(changed, sender, active, "extension-id"), false);
  }
});

import {assembleCapture, validateCapturePlan, runDiscoveryTicket} from "../../src/live/capture.js";
import type {CapturePlan} from "../../src/live/capture.js";
const plan: CapturePlan = {tabId: 7, exactUrl: "http://127.0.0.1:8888/match/101", sourceKind: "SYNTHETIC_TEST",
  profileStatus: "DRAFT", profileHash: active.profileHash, expiresAt: "2099-01-01T00:00:00Z", leaseMs: 600000,
  bindingId: active.captureId, bindingRevision: "1", operatorFixtureId: "FIXTURE", homeId: "H", awayId: "A",
  documentEpoch: active.documentEpoch, clockDomainId: active.documentEpoch, captureRevision: "0",
  priceParser: "DECIMAL_DOT", selectors: {}, markets: [{market_id: "M", horizon: "FT",
    settlement_basis: "NORMAL_TIME_INCLUDING_STOPPAGE", selections: {HOME: "SH", DRAW: "SD", AWAY: "SA"},
    labels: {horizon: "Full match", status: {OPEN: "Available"}, period: {H1: "Half one"}, score_separator: "COLON"}}]};
const fields = {fixture_id: "FIXTURE", home_team: "Home", away_team: "Away", home_id: "H", away_id: "A",
  market_root: "M", horizon_label: "Full match", home_selection: "SH", draw_selection: "SD", away_selection: "SA",
  home_odds: "2.10", draw_odds: "3.20", away_odds: "3.40", market_status: "Available", score: "0:0", period: "Half one"};
function response(): Record<string, unknown> {
  return {status: "DISPLAY_COHERENT", challenge: "a".repeat(64), first: {...fields}, second: {...fields},
    firstReadMonoUs: "1000000", browserMonoUs: "1100000", observedAtUtc: "2026-09-09T18:00:00Z"};
}
void test("complete stable book maps only observed labels; ambiguous content fails closed", () => {
  validateCapturePlan(plan);
  const book = assembleCapture(response(), plan, "a".repeat(64), "1");
  assert.equal(book.selections.DRAW.decimal_odds, "3.20");
  assert.equal(book.operator_period, "H1");
  assert.deepEqual(book.operator_score, {home: 0, away: 0});
  assert.equal(book.source_updated_at, null);
  for (const changed of [{...response(), second: {...fields, away_odds: "8.00"}},
    {...response(), second: {...fields, draw_selection: "SH"}}, {...response(), browserMonoUs: "1099999"},
    {...response(), browserMonoUs: "2000001"}, {...response(), challenge: "b".repeat(64)},
    {...response(), first: {...fields, arbitrary: "value"}}]) {
    assert.throws(() => assembleCapture(changed, plan, "a".repeat(64), "1"));
  }
  for (const changes of [{home_id: "A"}, {horizon_label: "FT"}, {draw_odds: "1.0"}, {draw_odds: "3,20"},
    {draw_odds: "3.2000001"}, {home_team: "x\u0000"}, {home_selection: "SD"}, {score: "101:0"}]) {
    const changed = {...fields, ...changes};
    assert.throws(() => assembleCapture({...response(), first: changed, second: changed}, plan, "a".repeat(64), "1"));
  }
  const unknown = {...fields, score: "ambiguous", period: "1H", market_status: "OPEN"};
  const unverified = assembleCapture({...response(), first: unknown, second: unknown}, plan, "a".repeat(64), "1");
  assert.equal(unverified.operator_period, null);
  assert.equal(unverified.operator_score, null);
  assert.equal(unverified.market_status, "UNKNOWN");
  assert.throws(() => { validateCapturePlan({...plan, sourceKind: "OBSERVED_REAL"}); });
  assert.throws(() => { validateCapturePlan({...plan, exactUrl: "http://outside.invalid/match/101"}); });
});

void test("discovery reads unadmitted fields without an accepted profile and always stops", async () => {
  const module = await import("../../src/live/capture.js") as unknown as Record<string, unknown>;
  assert.equal(typeof module["takeDiscoverySample"], "function", "first-observation executor is missing");
  const take = module["takeDiscoverySample"] as (p: unknown) => Promise<Record<string, unknown>>;
  const selectors = Object.fromEntries(["match_root", ...Object.keys(fields)].map(k => [k, `#${k}`]));
  const discovery = {tabId: 7, exactUrl: plan.exactUrl, sourceKind: "SYNTHETIC_TEST",
    fieldMapHash: "a".repeat(64), expiresAt: "2099-01-01T00:00:00Z", leaseMs: 600000, selectors};
  const operations: string[] = [];
  let injections = 0;
  const prior = globalThis.chrome;
  Object.assign(globalThis, {chrome: {tabs: {
    onUpdated: {addListener: () => undefined, removeListener: () => undefined},
    onRemoved: {addListener: () => undefined, removeListener: () => undefined},
    get: () => Promise.resolve({url: plan.exactUrl, active: true, discarded: false}),
    sendMessage: (_tab: number, message: {operation: string; value: unknown}, target: {documentId: string}) => {
      assert.equal(target.documentId, "document-a"); operations.push(message.operation);
      if (message.operation === "DISCOVERY_INIT") return Promise.resolve({status: "READY"});
      if (message.operation === "STOP") return Promise.resolve({status: "STOPPED"});
      assert.equal(message.operation, "READ");
      const partial = {...fields, home_id: null, away_id: null};
      return Promise.resolve({...response(), status: "DISCOVERY_SAMPLE", challenge: message.value, first: partial, second: partial});
    }}, scripting: {executeScript: (value: unknown) => {
      assert.deepEqual(value, {target: {tabId: 7, frameIds: [0]}, files: ["src/live/dom_reader.js"], world: "ISOLATED"});
      injections++; return Promise.resolve([{frameId: 0, documentId: "document-a"}]);
    }}}});
  try {
    const sample = await take(discovery);
    assert.equal(sample["status"], "UNADMITTED_SAMPLE");
    assert.equal(sample["source_kind"], "SYNTHETIC_TEST");
    assert.equal(sample["profile_accepted"], false);
    assert.equal(sample["binding_verified"], false);
    assert.deepEqual(sample["fields"], {...fields, home_id: null, away_id: null});
    assert.deepEqual(operations, ["DISCOVERY_INIT", "READ", "STOP"]);
    for (const mutation of [{leaseMs: 600001}, {exactUrl: "https://elsewhere.invalid/match/101"},
      {sourceKind: "OBSERVED_REAL"}, {selectors: {...selectors, account: "#balance"}}, {script: "arbitrary"}]) {
      await assert.rejects(() => take({...discovery, ...mutation}));
    }
    assert.equal(injections, 1, "invalid scopes must reject before script injection");
  } finally { Object.assign(globalThis, {chrome: prior}); }
});

void test("discovery rejects a connection already closed before receiver registration", async () => {
  const prior = globalThis.WebSocket;
  const connections: ClosedSocket[] = [];
  class ClosedSocket {
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;
    readonly readyState = 3;
    onclose: (() => void) | undefined;
    constructor() { connections.push(this); }
    close(): void { /* Already closed: the platform does not emit another close event. */ }
  }
  Object.assign(globalThis, {WebSocket: ClosedSocket});
  const attempt = runDiscoveryTicket(JSON.stringify({kind: "OPERATOR_DISCOVERY", runId: active.captureId,
    key: "A".repeat(43)}), 7).then(() => "UNEXPECTED_SUCCESS", (error: unknown) =>
    error instanceof Error ? error.message : "UNKNOWN_REJECTION");
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([attempt, new Promise<string>(resolve => {
      timer = setTimeout(() => { resolve("STUCK_WAITING_FOR_CLOSED_SOCKET"); }, 1000);
    })]);
    assert.equal(result, "E_DISCOVERY_CONNECTION");
  } finally {
    clearTimeout(timer);
    connections[0]?.onclose?.(); // Release the deliberately broken pre-fix implementation.
    await attempt;
    Object.assign(globalThis, {WebSocket: prior});
  }
});
