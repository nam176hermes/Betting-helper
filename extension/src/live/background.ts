import type {CaptureIdentity} from "./capture.js";

/** Narrow content-script notices; never an evaluation or arbitrary browser-command surface. */
export function handleCaptureMessage(message: unknown, sender: chrome.runtime.MessageSender,
  active: CaptureIdentity, extensionId: string): boolean {
  if (!message || typeof message !== "object") return false;
  const m = message as Record<string, unknown>;
  return Object.keys(m).sort().join() === "bindingRevision,captureId,code,documentEpoch,kind,profileHash" &&
    m["kind"] === "READER_NOTICE" && sender.id === extensionId && sender.tab?.id === active.tabId &&
    sender.documentId === active.documentId && sender.frameId === 0 && sender.url === active.exactUrl &&
    m["captureId"] === active.captureId && m["profileHash"] === active.profileHash &&
    m["bindingRevision"] === active.bindingRevision && m["documentEpoch"] === active.documentEpoch &&
    typeof m["code"] === "string" && ["DIRTY", "RECAPTURE", "NAVIGATED", "HIDDEN", "PROFILE_EXPIRED"].includes(m["code"]);
}
if (typeof chrome !== "undefined") {
  chrome.action.onClicked.addListener(tab => {
    if (tab.id !== undefined) void chrome.sidePanel.open({tabId: tab.id}).catch(() => undefined);
  });
}

import {startReadOnlyCapture} from "./capture.js";
import type {CapturePlan} from "./capture.js";
import type {MarketBook, LiveEvent} from "./contracts.js";
import {LiveCaptureSpool} from "./spool.js";
import {LiveTransport} from "./transport.js";
import type {PairingInput} from "./transport.js";
import {liveEventHash} from "./protocol.js";
import type {Validators} from "./protocol.js";
import {parseStrictJson} from "../canonical.js";
import {exactLink} from "./panel.js";
import type {Projection, SharedView, Command} from "./panel.js";

export function parsePairingTicket(text: string): [PairingInput, PairingInput] {
  try {
    if (text.length > 4096) throw Error();
    const ticket = parseStrictJson(new TextEncoder().encode(text)) as Record<string, unknown>;
    if (Object.keys(ticket).sort().join() !== "capture,durationSeconds,runId,ui,version" || ticket["version"] !== 1 ||
        typeof ticket["runId"] !== "string" || !Number.isInteger(ticket["durationSeconds"]) ||
        (ticket["durationSeconds"] as number) < 1 || (ticket["durationSeconds"] as number) > 7200) throw Error();
    const read = (name: "ui" | "capture"): PairingInput => {
      const part = ticket[name] as Record<string, unknown>;
      if (Object.keys(part).sort().join() !== "key,sessionId" || typeof part["sessionId"] !== "string" ||
          typeof part["key"] !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(part["key"])) throw Error();
      const key = Uint8Array.from(atob(part["key"].replaceAll("-", "+").replaceAll("_", "/") + "="), c => c.charCodeAt(0));
      if (key.length !== 32) throw Error();
      return {sessionId: part["sessionId"], key, runId: ticket["runId"] as string,
        durationSeconds: ticket["durationSeconds"] as number, role: name === "ui" ? "UI_SUBSCRIBER" : "CAPTURE_PRODUCER"};
    };
    const ui = read("ui"), capture = read("capture");
    if (ui.sessionId === capture.sessionId || ui.key.every((v, i) => v === capture.key[i])) throw Error();
    return [ui, capture];
  } catch { throw Error("E_PAIRING_TICKET"); }
}
export async function captureObservationId(challenge: string, horizon: string): Promise<string> {
  if (!/^[a-f0-9]{64}$/.test(challenge) || !["FT", "H1", "H2"].includes(horizon)) throw Error("E_CAPTURE_CHALLENGE");
  const namespace = "8aa7e4746a014ae991d8d4770a55b3e4";
  const bytes = Uint8Array.from(namespace.match(/../g) ?? [], b => Number.parseInt(b, 16));
  const name = new TextEncoder().encode(challenge + ":" + horizon), input = new Uint8Array(16 + name.length);
  input.set(bytes); input.set(name, 16);
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-1", input)).slice(0, 16);
  hash[6] = ((hash[6] ?? 0) & 15) | 80; hash[8] = ((hash[8] ?? 0) & 63) | 128;
  const hex = Array.from(hash, b => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// The build entry supplies pinned standalone validators via static imports (MV3 forbids dynamic imports).
let workspaceStarted = false;
export function startLiveWorkspace(verifiedValidators: Validators): void {
  if (workspaceStarted) throw Error("E_WORKSPACE_OWNER");
  workspaceStarted = true;
  const ports = new Set<chrome.runtime.Port>(), matches = new Map<string, {value: Projection; received: number}>();
  const captures = new Map<string, Awaited<ReturnType<typeof startReadOnlyCapture>>>();
  let active: string | null = null, connection = "DISCONNECTED", runId: string | null = null, notice = "";
  let ui: LiveTransport | undefined, producer: LiveTransport | undefined;
  const validators = verifiedValidators;
  let maxMatches: number | undefined;
  let operations: Promise<void> = Promise.resolve(), queued = 0;
  let captureWrites: Promise<void> = Promise.resolve(), captureQueued = 0;
  let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
  const broadcast = (): void => {
    const view: SharedView = {matches: Array.from(matches.values(), ({value, received}) => {
      const copy = structuredClone(value), d = copy.display, age = Math.max(0, Math.floor((performance.now() - received) * 1000));
      if (d) {
        if (d.provider_receipt_age_us !== null) d.provider_receipt_age_us += age;
        if (d.provider_content_age_us !== null) d.provider_content_age_us += age;
        for (const market of Object.values(d.markets)) {
          if (market.receipt_age_us !== null) market.receipt_age_us += age;
          if (market.content_age_us !== null) market.content_age_us += age;
          if (market.status === "CURRENT_DISPLAY_ONLY" && (market.receipt_age_us ?? Infinity) > 35000000) market.status = "STALE_MARKET";
        }
        const interval = ["HALFTIME", "PREGAME"].includes(copy.provider_state?.period ?? "") ? 125000000 : 45000000;
        if (d.status === "CURRENT_DISPLAY_ONLY" && (d.provider_receipt_age_us ?? Infinity) > interval) d.status = "STALE_PROVIDER";
        if (connection !== "CONNECTED") { d.status = "PAUSED"; d.capture_connection = "DISCONNECTED"; d.provider_connection = "WAITING"; }
      }
      return copy;
    }), active, connection, notice};
    for (const port of ports) { try { port.postMessage(view); } catch { ports.delete(port); } }
  };
  const stopReaders = (): void => { for (const capture of captures.values()) void capture.stop(); captures.clear(); };
  const close = (): void => {
    clearTimeout(deadlineTimer); stopReaders(); connection = "DISCONNECTED";
    const oldUi = ui, oldProducer = producer; ui = undefined; producer = undefined;
    oldUi?.close(); oldProducer?.close(); broadcast();
  };
  const safeError = (error: unknown): void => {
    const code = error instanceof Error && /^E_[A-Z_]{1,64}$/.test(error.message) ? error.message : "E_UI_REJECTED";
    notice = code; broadcast();
  };
  const enqueue = (work: () => Promise<void>): void => {
    if (queued >= 8) { close(); return; } queued++;
    operations = operations.then(work).catch(safeError).finally(() => { queued--; });
  };
  const accept = (raw: Record<string, unknown>, captureRole: boolean): void => {
    const value = raw as unknown as Projection;
    if (value.run_id !== runId || !value.display || !value.capture_scope) { close(); return; }
    const id = value.binding.binding_id, old = matches.get(id);
    if (old && BigInt(value.revision) < BigInt(old.value.revision)) return;
    maxMatches ??= value.display.max_matches;
    if (maxMatches !== value.display.max_matches || (!old && matches.size >= maxMatches)) { close(); return; }
    if (old && (old.value.binding.revision !== value.binding.revision || old.value.capture_scope?.profile_hash !== value.capture_scope.profile_hash || old.value.capture_scope.document_epoch !== value.capture_scope.document_epoch)) {
      void captures.get(id)?.stop(); captures.delete(id);
    }
    matches.set(id, {value, received: performance.now()}); active ??= id;
    if (!value.display.selected || ["STOPPED", "PROFILE_EXPIRED", "OUT_OF_SCOPE"].includes(value.display.status)) {
      void captures.get(id)?.stop(); captures.delete(id);
    }
    if (captureRole && value.health.reason === "CAPTURE_REQUEST_STARTED") {
      const challenge = value.health.evidence_hashes[0], capture = captures.get(id);
      if (challenge && capture) enqueue(() => capture.request(challenge));
    }
    broadcast();
  };
  const pair = async (ticket: string): Promise<void> => {
    if (ui || producer) throw Error("E_PAIRING_ALREADY_ACTIVE");
    const [uiTicket, producerTicket] = parsePairingTicket(ticket);
    try {
      runId = uiTicket.runId; matches.clear(); active = null; maxMatches = undefined; connection = "PAIRING"; notice = "";
      ui = new LiveTransport(validators, value => { accept(value, false); }, close);
      producer = new LiveTransport(validators, value => { accept(value, true); }, close);
      await ui.connect(uiTicket); await producer.connect(producerTicket);
      connection = "CONNECTED"; deadlineTimer = setTimeout(close, Math.min(uiTicket.durationSeconds, producerTicket.durationSeconds) * 1000);
      await producer.sendHealth(null, "WORKER_RESTART");
      const saved = (await chrome.storage.local.get("liveWatchlistIntent"))["liveWatchlistIntent"] as {active?: string; bindings?: {bindingId: string; profileHash: string}[]} | undefined;
      const prior = saved?.active && matches.get(saved.active)?.value;
      if (prior && saved.bindings?.some(b => b.bindingId === prior.binding.binding_id && b.profileHash === prior.capture_scope?.profile_hash)) active = prior.binding.binding_id;
      broadcast();
    } catch (error) { close();
      if (error instanceof Error && /^E_[A-Z_]{1,64}$/.test(error.message)) throw error;
      // eslint-disable-next-line preserve-caught-error -- Raw transport exceptions must not retain credential-bearing data.
      throw Error("E_PAIRING_REJECTED"); }
    finally { uiTicket.key.fill(0); producerTicket.key.fill(0); }
  };
  const start = async (value: Projection): Promise<void> => {
    const scope = value.capture_scope, b = value.binding;
    if (!scope || !producer || !value.display?.selected || captures.has(b.binding_id) ||
        scope.profile_status !== "ACCEPTED" || value.display.source_kind !== "OBSERVED_REAL") throw Error("E_CAPTURE_ADMISSION");
    const url = exactLink(b.operator_match_url);
    if (!url || !await chrome.permissions.contains({origins: [new URL(url).origin + "/*"]})) throw Error("E_CAPTURE_PERMISSION");
    const tabs = await chrome.tabs.query({active: true, currentWindow: true}), tab = tabs[0];
    if (tabs.length !== 1 || tab?.id === undefined || tab.url !== url) throw Error("E_CAPTURE_TAB");
    const spool = new LiveCaptureSpool({runId: value.run_id, streamId: scope.stream_id, generation: scope.generation,
      bindingId: b.binding_id, documentEpoch: scope.document_epoch, profileHash: scope.profile_hash, validate: validators.record});
    const retained = await spool.retained(), key = "live-document:" + value.run_id + ":" + scope.stream_id;
    const saved = (await chrome.storage.session.get(key))[key] as {documentId: string; clockDomainId: string} | undefined;
    if (retained.length && !saved) throw Error("E_CAPTURE_FRESH_ADMISSION_REQUIRED");
    const plan: CapturePlan = {tabId: tab.id, exactUrl: url, sourceKind: "OBSERVED_REAL", profileStatus: scope.profile_status,
      profileHash: scope.profile_hash, expiresAt: scope.expires_at, leaseMs: scope.max_duration_seconds * 1000,
      bindingId: b.binding_id, bindingRevision: b.revision, operatorFixtureId: b.operator_fixture_id,
      homeId: b.operator_home_id, awayId: b.operator_away_id, documentEpoch: scope.document_epoch,
      clockDomainId: saved?.clockDomainId ?? crypto.randomUUID(), captureRevision: retained.at(-1)?.payload["capture_revision"] as string | undefined ?? "0",
      priceParser: scope.price_parser, selectors: scope.selectors, markets: scope.markets};
    const health = (reason: string): void => {
      const code = reason === "DIRTY" ? "DOM_UNSTABLE" : ["HIDDEN", "NAVIGATED", "PROFILE_EXPIRED"].includes(reason) ? reason as "HIDDEN" | "NAVIGATED" | "PROFILE_EXPIRED" : "DOM_UNSTABLE";
      void producer?.sendHealth(b.binding_id, code).catch(close);
    };
    const capture = await startReadOnlyCapture(plan, {onInvalidation: health,
      onRecapture: () => { void producer?.sendHealth(b.binding_id, "CAPTURE_REJECTED").catch(close); },
      onBook: async (book: MarketBook, challenge: string): Promise<void> => {
        if (captureQueued >= 8) { close(); throw Error("E_CAPTURE_BACKPRESSURE"); } captureQueued++;
        const work = captureWrites.then(async () => {
          if (!producer) throw Error("E_CAPTURE_DISCONNECTED");
          const rows = await spool.retained(), prior = rows.at(-1);
          const event: LiveEvent = {protocol: "BH_LIVE_READONLY_V1", run_id: value.run_id, source_kind: "OPERATOR",
            stream_id: scope.stream_id, generation: scope.generation, sequence: String(BigInt(prior?.sequence ?? "0") + 1n),
            observation_id: await captureObservationId(challenge, book.horizon), observed_at_utc: book.observed_at_utc,
            received_mono_us: book.browser_mono_us, previous_hash: prior?.content_hash ?? "0".repeat(64),
            content_hash: "0".repeat(64), payload_type: "MarketBook", payload: book};
          event.content_hash = await liveEventHash(event, validators.record); await spool.append(event);
          while ((await spool.readPending()).length) await producer.sendCapture(spool);
        }).finally(() => { captureQueued--; });
        captureWrites = work.catch(close); await work;
      }}, saved?.documentId);
    await chrome.storage.session.set({[key]: {documentId: capture.identity.documentId, clockDomainId: plan.clockDomainId}});
    captures.set(b.binding_id, capture);
    while ((await spool.readPending()).length) await producer.sendCapture(spool);
    await producer.sendHealth(b.binding_id, "CAPTURE_REJECTED");
  };
  const command = async (operation: Command, bindingId: string): Promise<void> => {
    const value = matches.get(bindingId)?.value;
    if (!value || !ui || connection !== "CONNECTED") throw Error("E_UI_SCOPE");
    if (operation === "START_CAPTURE") { await start(value); return; }
    if (operation === "OPEN_OPERATOR" || operation === "OPEN_LIVESCORE") {
      const url = exactLink(operation === "OPEN_OPERATOR" ? value.binding.operator_match_url : value.binding.livescore_match_url);
      if (!url || value.binding.orientation_status !== "VERIFIED") throw Error("E_UI_LINK");
      await chrome.tabs.create({url}); return;
    }
    if (operation === "WATCHLIST_REMOVE" || operation === "STOP_SESSION") {
      if (operation === "STOP_SESSION") stopReaders(); else { await captures.get(bindingId)?.stop(); captures.delete(bindingId); }
    }
    await ui.sendUi(operation, bindingId);
    if (operation === "SELECT_ACTIVE") active = bindingId;
    await chrome.storage.local.set({liveWatchlistIntent: {active, bindings: Array.from(matches.values(), ({value: m}) =>
      ({bindingId: m.binding.binding_id, profileHash: m.capture_scope?.profile_hash}))}});
    if (operation === "STOP_SESSION") close(); else broadcast();
  };
  chrome.runtime.onConnect.addListener(port => {
    if (port.name !== "BH_LIVE_UI" || port.sender?.id !== chrome.runtime.id ||
        ![chrome.runtime.getURL("src/live/panel.html"), chrome.runtime.getURL("src/live/workspace.html")].includes(port.sender.url ?? "") || ports.size >= 8) { port.disconnect(); return; }
    ports.add(port); broadcast(); port.onDisconnect.addListener(() => { ports.delete(port); });
    port.onMessage.addListener((message: unknown) => {
      if (!message || typeof message !== "object") return;
      const m = message as Record<string, unknown>;
      if (Object.keys(m).sort().join() === "operation,ticket" && m["operation"] === "PAIR" && typeof m["ticket"] === "string") {
        const ticket = m["ticket"]; enqueue(() => pair(ticket));
      } else if (Object.keys(m).sort().join() === "bindingId,operation" && typeof m["bindingId"] === "string" && typeof m["operation"] === "string" &&
        ["START_CAPTURE", "WATCHLIST_ADD", "WATCHLIST_REMOVE", "SELECT_ACTIVE", "REFRESH", "STOP_SESSION", "OPEN_OPERATOR", "OPEN_LIVESCORE"].includes(m["operation"])) {
        const operation = m["operation"] as Command, id = m["bindingId"]; enqueue(() => command(operation, id));
      }
    });
  });
  // Display ageing only. This never requests provider data or captures.
  setInterval(broadcast, 1000);
}
