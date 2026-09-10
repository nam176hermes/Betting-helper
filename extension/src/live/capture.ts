/** One bound document, a fixed reader and a backend-issued freshness challenge. */
import type {MarketBook, Period, Score} from "./contracts.js";
import {handleCaptureMessage} from "./background.js";

export type ObservedMarket = {market_id: string; horizon: "H1" | "H2" | "FT";
  settlement_basis: "NORMAL_TIME_INCLUDING_STOPPAGE"; selections: Record<"HOME" | "DRAW" | "AWAY", string>;
  labels: {horizon: string; status: Partial<Record<MarketBook["market_status"], string>>;
    period: Partial<Record<Period, string>>; score_separator: "EN_DASH" | "COLON" | "HYPHEN" | null}};
export type CapturePlan = {tabId: number; exactUrl: string; sourceKind: "SYNTHETIC_TEST" | "OBSERVED_REAL";
  profileStatus: "DRAFT" | "ACCEPTED"; profileHash: string; expiresAt: string; leaseMs: number;
  bindingId: string; bindingRevision: string; operatorFixtureId: string; homeId: string; awayId: string;
  documentEpoch: string; clockDomainId: string; captureRevision: string;
  priceParser: "DECIMAL_DOT" | "DECIMAL_COMMA"; selectors: Record<string, string | null>; markets: ObservedMarket[]};
export type CaptureIdentity = {tabId: number; documentId: string; exactUrl: string; captureId: string;
  profileHash: string; bindingRevision: string; documentEpoch: string};
const rawFields = ["fixture_id", "home_team", "away_team", "home_id", "away_id", "market_root", "horizon_label",
  "home_selection", "draw_selection", "away_selection", "home_odds", "draw_odds", "away_odds", "market_status", "score", "period"];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const integer = /^(0|[1-9][0-9]{0,18})$/;
function counter(value: unknown): bigint {
  if (typeof value !== "string" || !integer.test(value) || BigInt(value) > 9223372036854775807n) throw Error("E_CAPTURE_COUNTER");
  return BigInt(value);
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 256 || value !== value.normalize("NFC") ||
      Array.from(value).some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) throw Error("E_CAPTURE_TEXT");
  return value;
}
function validMarket(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const m = value as Record<string, unknown>;
  if (m["settlement_basis"] !== "NORMAL_TIME_INCLUDING_STOPPAGE" || !m["labels"] || typeof m["labels"] !== "object") return false;
  const labels = m["labels"] as Record<string, unknown>;
  if (Object.keys(labels).sort().join() !== "horizon,period,score_separator,status" ||
      ![null, "EN_DASH", "COLON", "HYPHEN"].includes(labels["score_separator"] as string | null)) return false;
  text(labels["horizon"]);
  for (const [key, allowed] of [["status", ["OPEN", "SUSPENDED", "CLOSED", "UNKNOWN"]],
    ["period", ["PREGAME", "H1", "HALFTIME", "H2", "FINISHED", "BLOCKED", "OUT_OF_SCOPE", "UNKNOWN"]]] as const) {
    const map = labels[key];
    if (!map || typeof map !== "object") return false;
    const values = Object.values(map) as unknown[];
    if (Object.keys(map).some(k => !(allowed as readonly string[]).includes(k)) ||
        new Set(values).size !== values.length || values.some(v => !text(v))) return false;
  }
  return true;
}
export function validateCapturePlan(plan: CapturePlan): void {
  const url = new URL(plan.exactUrl);
  const synthetic = plan.sourceKind === "SYNTHETIC_TEST" && plan.profileStatus === "DRAFT" &&
    url.protocol === "http:" && url.hostname === "127.0.0.1";
  const real = plan.sourceKind === "OBSERVED_REAL" && plan.profileStatus === "ACCEPTED" && url.protocol === "https:";
  if ((!synthetic && !real) || url.username || url.password || url.search || url.hash ||
      !Number.isSafeInteger(plan.tabId) || plan.tabId < 0 ||
      !/^[0-9a-f]{64}$/.test(plan.profileHash) ||
      [plan.bindingId, plan.documentEpoch, plan.clockDomainId].some(id => !uuid.test(id)) ||
      !Number.isSafeInteger(plan.leaseMs) || plan.leaseMs <= 0 || plan.leaseMs > 7200000 ||
      !Number.isFinite(Date.parse(plan.expiresAt)) || Date.parse(plan.expiresAt) <= Date.now() ||
      !["DECIMAL_DOT", "DECIMAL_COMMA"].includes(plan.priceParser) ||
      plan.markets.length < 1 || plan.markets.length > 3 ||
      new Set(plan.markets.map(m => m.horizon)).size !== plan.markets.length ||
      !plan.markets.every(m => validMarket(m) &&
        ["H1", "H2", "FT"].includes(m.horizon) && Object.keys(m.selections).sort().join() === "AWAY,DRAW,HOME" &&
        new Set(Object.values(m.selections)).size === 3 && Object.values(m.selections).every(id => !!text(id)))) throw Error("E_CAPTURE_PLAN");
  counter(plan.bindingRevision); counter(plan.captureRevision);
}
function raw(value: unknown): Record<string, string | null> {
  if (!value || typeof value !== "object" || Object.keys(value).sort().join() !== [...rawFields].sort().join()) throw Error("E_CAPTURE_FIELDS");
  for (const [name, v] of Object.entries(value)) if (v !== null || !["score", "period"].includes(name)) text(v);
  return value as Record<string, string | null>;
}
function mapped<T extends string>(value: string | null | undefined, mapping: Partial<Record<T, string>>): T | null {
  const matches = Object.entries(mapping).filter(([, label]) => label === value);
  const entry = matches[0];
  return matches.length === 1 && entry ? entry[0] as T : null;
}
export function assembleCapture(response: unknown, plan: CapturePlan, challenge: string, revision: string): MarketBook {
  if (!response || typeof response !== "object" || new TextEncoder().encode(JSON.stringify(response)).length > 65536) throw Error("E_CAPTURE_RESPONSE");
  const r = response as Record<string, unknown>;
  if (Object.keys(r).sort().join() !== ["status", "challenge", "first", "second", "firstReadMonoUs", "browserMonoUs", "observedAtUtc"].sort().join() ||
      r["status"] !== "DISPLAY_COHERENT" || r["challenge"] !== challenge || !/^[0-9a-f]{64}$/.test(challenge)) throw Error("E_CAPTURE_RESPONSE");
  const first = raw(r["first"]), second = raw(r["second"]);
  if (rawFields.some(k => first[k] !== second[k]) || second["fixture_id"] !== plan.operatorFixtureId ||
      second["home_id"] !== plan.homeId || second["away_id"] !== plan.awayId) throw Error("E_CAPTURE_IDENTITY_OR_UNSTABLE");
  const interval = counter(r["browserMonoUs"]) - counter(r["firstReadMonoUs"]);
  if (interval < 100000n || interval > 1000000n || !Number.isFinite(Date.parse(text(r["observedAtUtc"])))) throw Error("E_CAPTURE_CLOCK");
  counter(revision);
  const matches = plan.markets.filter(m => m.market_id === second["market_root"] && m.labels.horizon === second["horizon_label"]);
  const market = matches[0];
  if (matches.length !== 1 || !market) throw Error("E_CAPTURE_MARKET");
  const selections = {} as MarketBook["selections"];
  for (const side of ["HOME", "DRAW", "AWAY"] as const) {
    const key = side.toLowerCase();
    if (second[key + "_selection"] !== market.selections[side]) throw Error("E_CAPTURE_SELECTION");
    const value = text(second[key + "_odds"]);
    const pattern = plan.priceParser === "DECIMAL_DOT" ? /^[1-9][0-9]{0,5}(\.[0-9]{1,6})?$/ : /^[1-9][0-9]{0,5}(,[0-9]{1,6})?$/;
    const odds = value.replace(",", ".");
    if (!pattern.test(value) || Number(odds) <= 1) throw Error("E_CAPTURE_PRICE");
    selections[side] = {selection_id: market.selections[side], decimal_odds: odds};
  }
  let score: Score = null;
  const separator = market.labels.score_separator === "EN_DASH" ? "–" : market.labels.score_separator === "COLON" ? ":" : market.labels.score_separator === "HYPHEN" ? "-" : null;
  if (separator && second["score"]) {
    const parts = second["score"].split(separator);
    if (parts.length === 2 && parts.every(v => /^(0|[1-9][0-9]{0,2})$/.test(v))) {
      if (parts.some(v => Number(v) > 100)) throw Error("E_CAPTURE_SCORE");
      score = {home: Number(parts[0]), away: Number(parts[1])};
    }
  }
  return {binding_id: plan.bindingId, binding_revision: plan.bindingRevision, operator_fixture_id: plan.operatorFixtureId,
    market_id: market.market_id, horizon: market.horizon, settlement_basis: market.settlement_basis, selections,
    market_status: mapped(second["market_status"], market.labels.status) ?? "UNKNOWN", capture_revision: revision,
    native_revision: null, observed_at_utc: text(r["observedAtUtc"]), browser_mono_us: text(r["browserMonoUs"]),
    clock_domain_id: plan.clockDomainId, source_updated_at: null, operator_score: score,
    operator_period: mapped(second["period"], market.labels.period), capture_evidence_tier: "DISPLAY_COHERENT",
    profile_hash: plan.profileHash, document_epoch: plan.documentEpoch,
    quality_flags: plan.sourceKind === "SYNTHETIC_TEST" ? ["SYNTHETIC"] : []};
}
export async function startReadOnlyCapture(input: CapturePlan, callbacks: {
  onBook: (book: MarketBook, challenge: string) => Promise<void>;
  onInvalidation: (reason: string) => void; onRecapture: () => void;
}, expectedDocumentId?: string): Promise<{identity: CaptureIdentity; request: (challenge: string) => Promise<void>; stop: () => Promise<void>}> {
  const plan = structuredClone(input);
  validateCapturePlan(plan);
  const tab = await chrome.tabs.get(plan.tabId);
  if (tab.url !== plan.exactUrl || !tab.active || tab.discarded) throw Error("E_CAPTURE_TAB");
  const results = await chrome.scripting.executeScript({target: {tabId: plan.tabId, frameIds: [0]},
    files: ["src/live/dom_reader.js"], world: "ISOLATED"});
  if (results.length !== 1 || results[0]?.frameId !== 0 || !results[0].documentId) throw Error("E_CAPTURE_DOCUMENT");
  if (expectedDocumentId !== undefined && results[0].documentId !== expectedDocumentId) throw Error("E_CAPTURE_DOCUMENT_CHANGED");
  const identity: CaptureIdentity = {tabId: plan.tabId, documentId: results[0].documentId,
    exactUrl: plan.exactUrl, captureId: crypto.randomUUID(), profileHash: plan.profileHash,
    bindingRevision: plan.bindingRevision, documentEpoch: plan.documentEpoch};
  let stopped = false, revision = counter(plan.captureRevision);
  const isStopped = (): boolean => stopped;
  const send = (operation: string, value: unknown): Promise<unknown> => chrome.tabs.sendMessage(plan.tabId,
    {kind: "FIXED_DOM_READONLY", operation, value}, {documentId: identity.documentId});
  const stop = async (): Promise<void> => {
    if (stopped) return; stopped = true;
    chrome.runtime.onMessage.removeListener(listener); chrome.tabs.onRemoved.removeListener(removed);
    chrome.tabs.onUpdated.removeListener(updated);
    await send("STOP", identity.captureId).catch(() => undefined);
  };
  const listener = (message: unknown, sender: chrome.runtime.MessageSender): void => {
    if (stopped || !handleCaptureMessage(message, sender, identity, chrome.runtime.id)) return;
    const code = (message as {code: string}).code;
    if (code === "RECAPTURE") callbacks.onRecapture();
    else { callbacks.onInvalidation(code); if (["NAVIGATED", "HIDDEN", "PROFILE_EXPIRED"].includes(code)) void stop(); }
  };
  const removed = (tabId: number): void => { if (tabId === plan.tabId) { callbacks.onInvalidation("NAVIGATED"); void stop(); } };
  const updated = (tabId: number, change: chrome.tabs.OnUpdatedInfo): void => {
    if (tabId === plan.tabId && (change.discarded === true || change.status === "loading" || (change.url !== undefined && change.url !== plan.exactUrl))) removed(tabId);
  };
  chrome.runtime.onMessage.addListener(listener); chrome.tabs.onRemoved.addListener(removed); chrome.tabs.onUpdated.addListener(updated);
  try {
    const ready = await send("INIT", {captureId: identity.captureId, profileHash: plan.profileHash,
      bindingRevision: plan.bindingRevision, documentEpoch: plan.documentEpoch, exactUrl: plan.exactUrl,
      leaseMs: Math.min(plan.leaseMs, Date.parse(plan.expiresAt) - Date.now()), selectors: plan.selectors});
    if (!ready || (ready as {status: string}).status !== "READY") throw Error("E_CAPTURE_INIT");
  } catch { await stop(); throw Error("E_CAPTURE_INIT"); }
  return {identity, stop, request: async (challenge: string): Promise<void> => {
    if (stopped) throw Error("E_CAPTURE_STOPPED");
    try {
      const response = await send("READ", challenge);
      if (isStopped()) throw Error();
      const book = assembleCapture(response, plan, challenge, String(revision + 1n));
      revision++; await callbacks.onBook(book, challenge);
    } catch { callbacks.onInvalidation("DOM_UNSTABLE"); }
  }};
}
