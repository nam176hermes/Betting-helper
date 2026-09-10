/** One bound document, a fixed reader and a backend-issued freshness challenge. */
import type {MarketBook, Period, Score} from "./contracts.js";
import {handleCaptureMessage} from "./background.js";
import {parseStrictJson} from "../canonical.js";

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
export type DiscoveryPlan = {tabId: number; exactUrl: string; sourceKind: "SYNTHETIC_TEST" | "OBSERVED_REAL";
  fieldMapHash: string; expiresAt: string; leaseMs: number; selectors: Record<string, string | null>};

/** Authenticated one-shot loopback exchange. No reconnect, URL input or provider key. */
export async function runDiscoveryTicket(ticketText: string, tabId: number): Promise<void> {
  const ticket = parseStrictJson(new TextEncoder().encode(ticketText)) as Record<string, unknown> | null;
  if (!ticket || Object.keys(ticket).sort().join() !== "key,kind,runId" || ticket["kind"] !== "OPERATOR_DISCOVERY" ||
      typeof ticket["runId"] !== "string" || !uuid.test(ticket["runId"]) ||
      typeof ticket["key"] !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(ticket["key"]) ||
      !Number.isSafeInteger(tabId) || tabId < 0) throw Error("E_DISCOVERY_TICKET");
  const bytes = Uint8Array.from(atob(ticket["key"].replaceAll("-", "+").replaceAll("_", "/") + "="), c => c.charCodeAt(0));
  if (bytes.length !== 32) throw Error("E_DISCOVERY_TICKET");
  const key = await crypto.subtle.importKey("raw", bytes, {name: "HMAC", hash: "SHA-256"}, false, ["sign", "verify"]);
  bytes.fill(0);
  const socket = new WebSocket("ws://127.0.0.1:8765/operator-discovery");
  const timeout = setTimeout(() => { socket.close(); }, 600000);
  let nonce = "";
  const preimage = (kind: "AUTH" | "PLAN" | "SAMPLE" | "ACK", payload = ""): Uint8Array<ArrayBuffer> =>
    new TextEncoder().encode(`BH-DISCOVERY/v1\0${kind}\0${String(ticket["runId"])}\0${nonce}\0${payload}`);
  const mac = async (kind: "AUTH" | "SAMPLE", payload = ""): Promise<string> =>
    Array.from(new Uint8Array(await crypto.subtle.sign("HMAC", key, preimage(kind, payload))), n => n.toString(16).padStart(2, "0")).join("");
  const requireOpen = (): void => {
    if (socket.readyState !== WebSocket.OPEN) throw Error("E_DISCOVERY_CONNECTION");
  };
  const receive = (): Promise<Record<string, unknown>> => new Promise((resolve, reject) => {
    if (socket.readyState === WebSocket.CLOSING || socket.readyState === WebSocket.CLOSED) {
      reject(Error("E_DISCOVERY_CONNECTION")); return;
    }
    socket.onclose = socket.onerror = () => { reject(Error("E_DISCOVERY_CONNECTION")); };
    socket.onmessage = (event: MessageEvent<unknown>) => {
      try {
        if (typeof event.data !== "string" || new TextEncoder().encode(event.data).length > 16384) throw Error();
        const value = parseStrictJson(new TextEncoder().encode(event.data)) as Record<string, unknown> | null;
        if (!value || typeof value !== "object" || Array.isArray(value)) throw Error();
        resolve(value);
      } catch { reject(Error("E_DISCOVERY_MESSAGE")); }
    };
  });
  const verified = async (kind: "PLAN" | "ACK"): Promise<Record<string, unknown>> => {
    const frame = await receive();
    if (Object.keys(frame).sort().join() !== "mac,payload" || typeof frame["payload"] !== "string" ||
        typeof frame["mac"] !== "string" || !/^[a-f0-9]{64}$/.test(frame["mac"])) throw Error("E_DISCOVERY_FRAME");
    const signature = Uint8Array.from(frame["mac"].match(/../g) ?? [], h => parseInt(h, 16));
    if (!await crypto.subtle.verify("HMAC", key, signature, preimage(kind, frame["payload"]))) throw Error("E_DISCOVERY_MAC");
    return parseStrictJson(new TextEncoder().encode(frame["payload"])) as Record<string, unknown>;
  };
  try {
    // Install the first receiver before open, so the greeting cannot race registration.
    const greeting = await receive();
    if (Object.keys(greeting).sort().join() !== "nonce,run_id" || greeting["run_id"] !== ticket["runId"] ||
        typeof greeting["nonce"] !== "string" || !/^[a-f0-9]{64}$/.test(greeting["nonce"])) throw Error("E_DISCOVERY_GREETING");
    nonce = greeting["nonce"];
    const planPromise = verified("PLAN"); void planPromise.catch(() => undefined);
    const authMac = await mac("AUTH"); requireOpen();
    socket.send(JSON.stringify({mac: authMac}));
    const plan = await planPromise;
    requireOpen();
    if (Object.hasOwn(plan, "tabId")) throw Error("E_DISCOVERY_PLAN");
    const sample = await takeDiscoverySample({...plan, tabId} as DiscoveryPlan);
    const payload = JSON.stringify(sample), ackPromise = verified("ACK"); void ackPromise.catch(() => undefined);
    const sampleMac = await mac("SAMPLE", payload); requireOpen();
    socket.send(JSON.stringify({payload, mac: sampleMac}));
    const ack = await ackPromise;
    if (Object.keys(ack).join() !== "status" || ack["status"] !== "UNADMITTED_SAMPLE_SAVED") throw Error("E_DISCOVERY_ACK");
  } finally { clearTimeout(timeout); socket.close(); }
}

/** One unadmitted sample. The caller must first obtain reviewed, user-confirmed scope.
 * This is deliberately separate from accepted-profile capture and never creates a book. */
export async function takeDiscoverySample(input: DiscoveryPlan): Promise<Record<string, unknown>> {
  const plan = structuredClone(input), url = new URL(plan.exactUrl), start = performance.now(), wall = Date.now();
  const selectors = plan.selectors as Record<string, string | null> | null;
  if (Object.keys(plan).sort().join() !== "exactUrl,expiresAt,fieldMapHash,leaseMs,selectors,sourceKind,tabId" ||
      !(plan.sourceKind === "SYNTHETIC_TEST" && url.protocol === "http:" && url.hostname === "127.0.0.1" ||
        plan.sourceKind === "OBSERVED_REAL" && url.origin === "https://miseojeuplus.espacejeux.com") ||
      url.username || url.password || url.search || url.hash || url.href !== plan.exactUrl ||
      !Number.isSafeInteger(plan.tabId) || plan.tabId < 0 || !/^[a-f0-9]{64}$/.test(plan.fieldMapHash) ||
      !Number.isFinite(Date.parse(plan.expiresAt)) || Date.parse(plan.expiresAt) <= wall ||
      !Number.isSafeInteger(plan.leaseMs) || plan.leaseMs < 1 || plan.leaseMs > 600000 ||
      !selectors || Object.keys(selectors).sort().join() !== [...rawFields, "match_root"].sort().join() ||
      typeof selectors["match_root"] !== "string") throw Error("E_DISCOVERY_SCOPE");
  for (const value of Object.values(plan.selectors)) {
    if (value !== null && (typeof value !== "string" || value.length < 1 || value.length > 512 ||
        /password|passwd|token|cookie|account|balance|betslip|cashout|login|email|username|wallet|form|input|textarea|iframe|contenteditable/i.test(value))) throw Error("E_DISCOVERY_SELECTOR");
  }
  const remaining = (): number => {
    const ms = Math.floor(Math.min(plan.leaseMs - (performance.now() - start), Date.parse(plan.expiresAt) - Date.now()));
    if (Date.now() < wall || ms <= 0) throw Error("E_DISCOVERY_EXPIRED");
    return ms;
  };
  const bounded = async <T>(action: () => Promise<T>): Promise<T> => {
    const ms = remaining(); let timer: ReturnType<typeof setTimeout> | undefined;
    try { return await Promise.race([action(), new Promise<never>((_, reject) => {
      timer = setTimeout(() => { reject(Error("E_DISCOVERY_EXPIRED")); }, ms);
    })]); } finally { clearTimeout(timer); }
  };
  const tab = await bounded(() => chrome.tabs.get(plan.tabId));
  if (tab.url !== plan.exactUrl || !tab.active || tab.discarded) throw Error("E_DISCOVERY_TAB");
  const injection = await bounded(() => chrome.scripting.executeScript({target: {tabId: plan.tabId, frameIds: [0]},
    files: ["src/live/dom_reader.js"], world: "ISOLATED"}));
  const documentId = injection[0]?.documentId;
  if (injection.length !== 1 || injection[0]?.frameId !== 0 || !documentId) throw Error("E_DISCOVERY_DOCUMENT");
  const captureId = crypto.randomUUID(), documentEpoch = crypto.randomUUID();
  let replaced = false;
  const isReplaced = (): boolean => replaced;
  const changed = (id: number, change: chrome.tabs.OnUpdatedInfo): void => {
    if (id === plan.tabId && (change.status === "loading" || change.discarded === true || change.url !== undefined)) replaced = true;
  };
  const removed = (id: number): void => { if (id === plan.tabId) replaced = true; };
  chrome.tabs.onUpdated.addListener(changed); chrome.tabs.onRemoved.addListener(removed);
  const send = (operation: string, value: unknown): Promise<unknown> => chrome.tabs.sendMessage(plan.tabId,
    {kind: "FIXED_DOM_READONLY", operation, value}, {documentId});
  try {
    const ready = await bounded(() => send("DISCOVERY_INIT", {captureId, profileHash: plan.fieldMapHash,
      bindingRevision: "0", documentEpoch, exactUrl: plan.exactUrl, leaseMs: remaining(), selectors: plan.selectors}));
    if (!ready || (ready as {status: string}).status !== "READY") throw Error("E_DISCOVERY_INIT");
    const challenge = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2, "0")).join("");
    const reply = await bounded(() => send("READ", challenge)) as Record<string, unknown> | null;
    if (!reply || Object.keys(reply).sort().join() !== "browserMonoUs,challenge,first,firstReadMonoUs,observedAtUtc,second,status" ||
        reply["status"] !== "DISCOVERY_SAMPLE" || reply["challenge"] !== challenge) throw Error("E_DISCOVERY_SAMPLE");
    const observed = [reply["first"], reply["second"]] as (Record<string, unknown> | null)[];
    for (const fields of observed) {
      if (!fields || Object.keys(fields).sort().join() !== [...rawFields].sort().join()) throw Error("E_DISCOVERY_FIELDS");
      for (const value of Object.values(fields)) if (value !== null) text(value);
    }
    const interval = counter(reply["browserMonoUs"]) - counter(reply["firstReadMonoUs"]);
    if (rawFields.some(name => observed[0]?.[name] !== observed[1]?.[name]) || interval < 100000n || interval > 1000000n ||
        !Number.isFinite(Date.parse(text(reply["observedAtUtc"])))) throw Error("E_DISCOVERY_UNSTABLE");
    const current = await bounded(() => chrome.tabs.get(plan.tabId));
    remaining();
    if (isReplaced() || current.url !== plan.exactUrl || !current.active || current.discarded) throw Error("E_DISCOVERY_TAB_CHANGED");
    return {status: "UNADMITTED_SAMPLE", source_kind: plan.sourceKind, exact_url: plan.exactUrl,
      field_map_hash: plan.fieldMapHash, tab_id: plan.tabId, document_id: documentId, document_epoch: documentEpoch,
      fields: observed[1], observed_at_utc: reply["observedAtUtc"], browser_mono_us: reply["browserMonoUs"],
      profile_accepted: false, binding_verified: false};
  } finally {
    chrome.tabs.onUpdated.removeListener(changed); chrome.tabs.onRemoved.removeListener(removed);
    // A dead document cannot acknowledge STOP; its reader lease independently expires.
    void send("STOP", captureId).catch(() => undefined);
  }
}
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
