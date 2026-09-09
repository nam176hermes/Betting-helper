import { canonicalBytes, parseStrictJson } from "../canonical.js";
import { validateLiveRecord, type LiveEvent, type SchemaValidator } from "./contracts.js";

export type LiveRole = "CAPTURE_PRODUCER" | "UI_SUBSCRIBER";
export type Validators = { record: SchemaValidator; frame: (value: unknown) => boolean };
export type LiveFrame = {
  protocol: "BH_LIVE_WIRE_V1"; session_id: string;
  direction: "CLIENT_TO_BACKEND" | "BACKEND_TO_CLIENT"; counter: string;
  message_type: string; body: Record<string, unknown>; mac: string;
};
const maximum = 9223372036854775807n;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const clientTypes: Record<LiveRole, readonly string[]> = {
  CAPTURE_PRODUCER: ["CAPTURE_BATCH", "HEALTH", "STOP_CAPTURE", "PING", "PONG"],
  UI_SUBSCRIBER: ["WATCHLIST_ADD", "WATCHLIST_REMOVE", "SELECT_ACTIVE", "REFRESH", "STOP_SESSION", "PING", "PONG"],
};
const backendTypes = ["ACK", "NACK", "PROJECTION", "PING", "PONG"];
const preimage = (domain: "BH-LIVE-WIRE/v1\0" | "BH-LIVE-READONLY/Event/v1\0", value: unknown): Uint8Array<ArrayBuffer> => {
  const prefix = new TextEncoder().encode(domain), bytes = canonicalBytes(value);
  const result = new Uint8Array(prefix.byteLength + bytes.byteLength);
  result.set(prefix); result.set(bytes, prefix.byteLength); return result;
};
const hex = (bytes: ArrayBuffer): string => Array.from(new Uint8Array(bytes), v => v.toString(16).padStart(2, "0")).join("");
export const liveEventHash = async (value: unknown, validator: SchemaValidator): Promise<string> => {
  const event = validateLiveRecord(value, "LiveEvent", validator);
  delete event["content_hash"];
  return hex(await crypto.subtle.digest("SHA-256", preimage("BH-LIVE-READONLY/Event/v1\0", event)));
};
export const validateLiveFrame = async (value: unknown, validators: Validators): Promise<LiveFrame> => {
  try {
    if (!validators.frame(value) || canonicalBytes(value).byteLength > 262144) throw new Error();
    const frame = value as LiveFrame, body = frame.body;
    if (BigInt(frame.counter) > maximum) throw new Error();
    if (frame.message_type === "CAPTURE_BATCH") {
      const first = BigInt(body["first_sequence"] as string), last = BigInt(body["last_sequence"] as string);
      const events = body["events"] as LiveEvent[];
      if (first < 1n || last > maximum || BigInt(body["generation"] as string) > maximum || last - first + 1n !== BigInt(events.length)) throw new Error();
      for (const [index, raw] of events.entries()) {
        const event = validateLiveRecord(raw, "LiveEvent", validators.record) as LiveEvent;
        if (event.source_kind !== "OPERATOR" || event.payload_type !== "MarketBook" ||
            event.run_id !== body["run_id"] || event.stream_id !== body["stream_id"] ||
            event.generation !== body["generation"] || event.sequence !== String(first + BigInt(index)) ||
            event.content_hash !== await liveEventHash(event, validators.record)) throw new Error();
      }
    }
    // Validate counters and nested record semantics even on backend projections.
    if (frame.message_type === "PROJECTION") {
      const binding = validateLiveRecord(body["binding"], "FixtureBinding", validators.record);
      if (body["provider_state"] !== null) {
        const provider = validateLiveRecord(body["provider_state"], "ProviderState", validators.record);
        if (provider["fixture_id"] !== binding["provider_fixture_id"]) throw new Error();
      }
      const horizons = new Set<unknown>();
      for (const raw of body["books"] as unknown[]) {
        const book = validateLiveRecord(raw, "MarketBook", validators.record);
        if (book["binding_id"] !== binding["binding_id"] || book["binding_revision"] !== binding["revision"] || horizons.has(book["horizon"])) throw new Error();
        horizons.add(book["horizon"]);
      }
    }
    for (const name of ["generation", "sequence", "revision", "monotonic_us"]) {
      if (typeof body[name] === "string" && BigInt(body[name]) > maximum) throw new Error();
    }
    return structuredClone(frame);
  } catch { throw new Error("E_LIVE_WIRE_SCHEMA"); }
};
const hmacKey = (key: Uint8Array): Promise<CryptoKey> => {
  if (key.byteLength !== 32) throw new Error("E_LIVE_WIRE_KEY");
  return crypto.subtle.importKey("raw", new Uint8Array(key), {name: "HMAC", hash: "SHA-256"}, false, ["sign", "verify"]);
};
export const encodeFrame = async (content: Omit<LiveFrame, "mac">, key: Uint8Array, validators: Validators): Promise<string> => {
  if (Object.hasOwn(content, "mac")) throw new Error("E_LIVE_WIRE_FRAME");
  await validateLiveFrame({...content, mac: "0".repeat(64)}, validators);
  const mac = hex(await crypto.subtle.sign("HMAC", await hmacKey(key), preimage("BH-LIVE-WIRE/v1\0", content)));
  return new TextDecoder().decode(canonicalBytes({...content, mac}));
};
export class LiveSession {
  public inCounter = 0n;
  public outCounter = 0n;
  private stage = 0;
  private clientNonce: string | undefined;
  private serverNonce: string | undefined;
  private readonly started: number;
  constructor(public readonly sessionId: string, public readonly runId: string,
    public readonly side: "CLIENT" | "BACKEND", public readonly role: LiveRole,
    public readonly validators: Validators, private readonly deadline: number,
    private readonly now: () => number = () => performance.now() / 1000) {
    this.started = now();
    if (!uuid.test(sessionId) || !uuid.test(runId) || !Object.hasOwn(clientTypes, role) ||
        !Number.isFinite(deadline) || deadline - this.started <= 0 || deadline - this.started > 7200) throw new Error("E_LIVE_WIRE_SCOPE");
  }
  get ready(): boolean { return this.stage === 4 && this.now() < this.deadline; }
  private accept(frame: LiveFrame, incoming: boolean): void {
    const now = this.now();
    if (now < this.started || now >= this.deadline) throw new Error("E_LIVE_WIRE_LEASE");
    const outgoing = this.side === "CLIENT" ? "CLIENT_TO_BACKEND" : "BACKEND_TO_CLIENT";
    const direction = incoming ? (outgoing === "CLIENT_TO_BACKEND" ? "BACKEND_TO_CLIENT" : "CLIENT_TO_BACKEND") : outgoing;
    const next = (incoming ? this.inCounter : this.outCounter) + 1n;
    if (frame.session_id !== this.sessionId || frame.direction !== direction || frame.counter !== String(next) || frame.body["run_id"] !== this.runId) throw new Error("E_LIVE_WIRE_SESSION_COUNTER");
    const body = frame.body;
    let stage = this.stage, client = this.clientNonce, server = this.serverNonce;
    if (stage < 4) {
      if (now - this.started > 5) throw new Error("E_LIVE_WIRE_HANDSHAKE_TIMEOUT");
      const types = ["HELLO", "WELCOME", "READY", "READY_ACK"];
      if (frame.message_type !== types[stage] || incoming !== (stage % 2 === (this.side === "CLIENT" ? 1 : 0))) throw new Error("E_LIVE_WIRE_HANDSHAKE_ORDER");
      for (const name of ["client_nonce", "server_nonce"]) {
        if (Object.hasOwn(body, name)) {
          const nonce = body[name] as string, decoded = atob(nonce.replaceAll("-", "+").replaceAll("_", "/") + "=");
          if (decoded.length !== 32 || btoa(decoded).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "") !== nonce) throw new Error("E_LIVE_WIRE_NONCE");
        }
      }
      if (stage === 0) {
        if (body["role"] !== this.role) throw new Error("E_LIVE_WIRE_ROLE");
        client = body["client_nonce"] as string;
      } else if (body["client_nonce"] !== client) throw new Error("E_LIVE_WIRE_NONCE");
      if (stage === 1) {
        server = body["server_nonce"] as string;
        if (client === server) throw new Error("E_LIVE_WIRE_NONCE");
      } else if (stage >= 2 && body["server_nonce"] !== server) throw new Error("E_LIVE_WIRE_NONCE");
      stage++;
    } else if (!(direction === "CLIENT_TO_BACKEND" ? clientTypes[this.role] : backendTypes).includes(frame.message_type)) throw new Error("E_LIVE_WIRE_ROLE_DENIED");
    this.stage = stage; this.clientNonce = client; this.serverNonce = server;
    if (incoming) this.inCounter = next; else this.outCounter = next;
  }
  async send(kind: string, body: Record<string, unknown>, key: Uint8Array): Promise<string> {
    const content: Omit<LiveFrame, "mac"> = {protocol: "BH_LIVE_WIRE_V1", session_id: this.sessionId,
      direction: this.side === "CLIENT" ? "CLIENT_TO_BACKEND" : "BACKEND_TO_CLIENT",
      counter: String(this.outCounter + 1n), message_type: kind, body};
    const encoded = await encodeFrame(content, key, this.validators);
    this.accept({...content, mac: "0".repeat(64)}, false); return encoded;
  }
  async receive(data: string, key: Uint8Array): Promise<LiveFrame> {
    const bytes = new TextEncoder().encode(data);
    if (bytes.byteLength > 262144) throw new Error("E_LIVE_WIRE_FRAME");
    const frame = await validateLiveFrame(parseStrictJson(bytes), this.validators);
    const {mac, ...content} = frame;
    const signature = new Uint8Array(mac.match(/../g)?.map(v => Number.parseInt(v, 16)) ?? []);
    if (!await crypto.subtle.verify("HMAC", await hmacKey(key), signature, preimage("BH-LIVE-WIRE/v1\0", content))) throw new Error("E_LIVE_WIRE_AUTHENTICATION");
    this.accept(frame, true); return frame;
  }
}
