/** Offline-only closed frames. Imported solely by the offline module graph. */
import { canonicalBytes, parseStrictJson } from "../canonical.js";

export const validateOfflineFrame = (value: unknown, validateSchema: (value: unknown) => void): void => {
  try {
    validateSchema(value);
    const frame = value as { counter: string; message_type: string; body: {
      run_id: string; browser_run_id: string; stream_id: string; generation: string;
      first_sequence: string; last_sequence: string; observations: {
        discovery_run_id: string; context: { browser_run_id: string }; stream_id: string;
        generation: string; sequence: string;
      }[];
    } };
    const maximum = 9223372036854775807n;
    if (BigInt(frame.counter) > maximum) throw new Error();
    if (frame.message_type === "BATCH") {
      const body = frame.body;
      const first = BigInt(body.first_sequence), last = BigInt(body.last_sequence);
      if (first < 1n || last < first || last > maximum || BigInt(body.generation) > maximum ||
          last - first + 1n !== BigInt(body.observations.length)) throw new Error();
      for (const [index, raw] of body.observations.entries()) {
        if (raw.discovery_run_id !== body.run_id || raw.context.browser_run_id !== body.browser_run_id ||
            raw.stream_id !== body.stream_id || raw.generation !== body.generation ||
            raw.sequence !== String(first + BigInt(index)) ||
            new TextEncoder().encode(JSON.stringify(raw)).byteLength > 65536) throw new Error();
      }
    }
    if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 262144) throw new Error();
  } catch { throw new Error("E_OFFLINE_SCHEMA"); }
};

export type OfflineFrame = {
  protocol: "BH_OFFLINE_WIRE_V1"; session_id: string;
  direction: "CLIENT_TO_BACKEND" | "BACKEND_TO_CLIENT"; counter: string;
  message_type: string; body: Record<string, unknown>; mac: string;
};
type SchemaValidator = (value: unknown) => void;
const preimage = (frame: Omit<OfflineFrame, "mac">): Uint8Array<ArrayBuffer> => {
  const prefix = new TextEncoder().encode("BH-OFFLINE-WIRE/v1\0");
  const bytes = canonicalBytes(frame);
  const result = new Uint8Array(prefix.byteLength + bytes.byteLength);
  result.set(prefix); result.set(bytes, prefix.byteLength);
  return result;
};
const hmacKey = (key: Uint8Array): Promise<CryptoKey> => {
  if (key.byteLength !== 32) throw new Error("E_OFFLINE_KEY_OR_FRAME");
  return crypto.subtle.importKey("raw", new Uint8Array(key), {name: "HMAC", hash: "SHA-256"}, false, ["sign", "verify"]);
};
export const encodeFrame = async (frame: Omit<OfflineFrame, "mac">, key: Uint8Array,
  validateSchema: SchemaValidator): Promise<string> => {
  if (Object.hasOwn(frame, "mac")) throw new Error("E_OFFLINE_KEY_OR_FRAME");
  validateOfflineFrame({...frame, mac: "0".repeat(64)}, validateSchema);
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", await hmacKey(key), preimage(frame)));
  const mac = Array.from(signature, value => value.toString(16).padStart(2, "0")).join("");
  return new TextDecoder().decode(canonicalBytes({...frame, mac}));
};

export class SessionState {
  public inCounter = 0n;
  public outCounter = 0n;
  private stage = 0;
  private clientNonce: string | undefined;
  private serverNonce: string | undefined;
  private readonly started: number;
  constructor(public readonly sessionId: string, public readonly runId: string,
    public readonly role: "CLIENT" | "BACKEND", public readonly validateSchema: SchemaValidator,
    private readonly now: () => number = () => performance.now() / 1000) {
    this.started = now();
  }
  get ready(): boolean { return this.stage === 4; }
  public accept(frame: Omit<OfflineFrame, "mac">, incoming: boolean): void {
    const outgoing = this.role === "CLIENT" ? "CLIENT_TO_BACKEND" : "BACKEND_TO_CLIENT";
    const direction = incoming ? (outgoing === "CLIENT_TO_BACKEND" ? "BACKEND_TO_CLIENT" : "CLIENT_TO_BACKEND") : outgoing;
    const next = (incoming ? this.inCounter : this.outCounter) + 1n;
    if (frame.session_id !== this.sessionId || frame.direction !== direction || frame.counter !== String(next)) {
      throw new Error("E_OFFLINE_SESSION_COUNTER");
    }
    const body = frame.body;
    if (Object.hasOwn(body, "run_id") && body.run_id !== this.runId) throw new Error("E_OFFLINE_SOURCE_BINDING");
    let stage = this.stage, client = this.clientNonce, server = this.serverNonce;
    if (stage < 4) {
      if (this.now() - this.started > 5) throw new Error("E_OFFLINE_HANDSHAKE_TIMEOUT");
      const types = ["HELLO", "WELCOME", "READY", "READY_ACK"];
      const expectedIncoming = this.role === "CLIENT" ? stage % 2 === 1 : stage % 2 === 0;
      if (frame.message_type !== types[stage] || incoming !== expectedIncoming) throw new Error("E_OFFLINE_HANDSHAKE_ORDER");
      for (const name of ["client_nonce", "server_nonce"]) {
        if (Object.hasOwn(body, name)) {
          const nonce = body[name];
          if (typeof nonce !== "string") throw new Error("E_OFFLINE_NONCE");
          const decoded = atob(nonce.replaceAll("-", "+").replaceAll("_", "/") + "=");
          if (decoded.length !== 32 || btoa(decoded).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "") !== nonce) {
            throw new Error("E_OFFLINE_NONCE");
          }
        }
      }
      if (stage === 0) client = body.client_nonce as string;
      else if (body.client_nonce !== client) throw new Error("E_OFFLINE_NONCE");
      if (stage === 1) {
        server = body.server_nonce as string;
        if (server === client) throw new Error("E_OFFLINE_NONCE");
      } else if (stage >= 2 && body.server_nonce !== server) throw new Error("E_OFFLINE_NONCE");
      stage++;
    } else if (stage !== 4 || ["HELLO", "WELCOME", "READY", "READY_ACK"].includes(frame.message_type)) {
      throw new Error("E_OFFLINE_HANDSHAKE_ORDER");
    } else if (frame.message_type === "STOP") stage = 5;
    this.stage = stage; this.clientNonce = client; this.serverNonce = server;
    if (incoming) this.inCounter = next; else this.outCounter = next;
  }
  async send(messageType: string, body: Record<string, unknown>, key: Uint8Array): Promise<string> {
    const frame: Omit<OfflineFrame, "mac"> = {protocol: "BH_OFFLINE_WIRE_V1", session_id: this.sessionId,
      direction: this.role === "CLIENT" ? "CLIENT_TO_BACKEND" : "BACKEND_TO_CLIENT",
      counter: String(this.outCounter + 1n), message_type: messageType, body};
    const encoded = await encodeFrame(frame, key, this.validateSchema);
    this.accept(frame, false);
    return encoded;
  }
}

export const verifyFrame = async (data: string, key: Uint8Array, session: SessionState): Promise<OfflineFrame> => {
  const bytes = new TextEncoder().encode(data);
  if (bytes.byteLength > 262144) throw new Error("E_OFFLINE_FRAME_SIZE_OR_KEY");
  let frame: OfflineFrame;
  try {
    const value = parseStrictJson(bytes);
    validateOfflineFrame(value, session.validateSchema);
    frame = value as OfflineFrame;
  } catch { throw new Error("E_OFFLINE_SCHEMA"); }
  const {mac, ...content} = frame;
  const signature = new Uint8Array(mac.match(/../g)?.map(value => Number.parseInt(value, 16)) ?? []);
  if (!await crypto.subtle.verify("HMAC", await hmacKey(key), signature, preimage(content))) throw new Error("E_OFFLINE_MAC");
  session.accept(frame, true);
  return frame;
};
