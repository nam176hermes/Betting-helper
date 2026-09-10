/** One service-worker transport per role; no provider credentials or API loops. */
import { canonicalBytes } from "../canonical.js";
import type { LiveCaptureSpool } from "./spool.js";
import { LiveSession, type LiveFrame, type LiveRole, type Validators } from "./protocol.js";

export type PairingInput = {sessionId: string; runId: string; role: LiveRole; key: Uint8Array; durationSeconds: number};
type Pending = {batchId: string; runId: string; streamId: string; generation: string; last: string;
  spool: LiveCaptureSpool; resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout>};
export class LiveTransport {
  private retired = false;
  private socket: WebSocket | undefined;
  private session: LiveSession | undefined;
  private key: Uint8Array | undefined;
  private tx: Promise<void> = Promise.resolve();
  private rx: Promise<void> = Promise.resolve();
  private queued = 0;
  private incoming = 0;
  private pending: Pending | undefined;
  private readyResolve: (() => void) | undefined;
  private readyReject: ((error: Error) => void) | undefined;
  constructor(private readonly validators: Validators,
    private readonly onProjection: (body: Record<string, unknown>) => void,
    private readonly onHealth: (code: string) => void) {}

  async connect(ticket: PairingInput): Promise<void> {
    if (this.retired || this.socket !== undefined || ticket.key.byteLength !== 32 || !Number.isInteger(ticket.durationSeconds) ||
        ticket.durationSeconds < 1 || ticket.durationSeconds > 7200) throw new Error("E_LIVE_TRANSPORT_PAIRING");
    this.session = new LiveSession(ticket.sessionId, ticket.runId, "CLIENT", ticket.role,
      this.validators, performance.now() / 1000 + ticket.durationSeconds);
    this.key = new Uint8Array(ticket.key);
    const ready = new Promise<void>((resolve, reject) => { this.readyResolve = resolve; this.readyReject = reject; });
    const socket = new WebSocket("ws://127.0.0.1:8765/live"); this.socket = socket;
    const timer = setTimeout(() => { this.close(); }, 5000);
    socket.onopen = () => {
      const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
      void this.send("HELLO", {run_id: ticket.runId, role: ticket.role, client_nonce: nonce}).catch(() => { this.close(); });
    };
    socket.onmessage = event => {
      if (typeof event.data !== "string" || new TextEncoder().encode(event.data).byteLength > 262144 || this.incoming >= 8) { this.close(); return; }
      const text = event.data; this.incoming++;
      this.rx = this.rx.then(async () => {
        if (!this.session || !this.key) throw new Error("E_LIVE_TRANSPORT_CLOSED");
        const frame = await this.session.receive(text, this.key);
        await this.receive(frame);
      }).catch(() => { this.close(); }).finally(() => { this.incoming--; });
    };
    socket.onerror = () => { this.close(); };
    socket.onclose = () => { this.close(); };
    try { await ready; } finally { clearTimeout(timer); }
  }
  private send(kind: string, body: Record<string, unknown>): Promise<void> {
    if (this.queued >= 8) return Promise.reject(new Error("E_LIVE_TRANSPORT_BACKPRESSURE"));
    this.queued++;
    const task = this.tx.then(async () => {
      const socket = this.socket, session = this.session, key = this.key;
      if (!socket || !session || !key || socket.readyState !== WebSocket.OPEN) throw new Error("E_LIVE_TRANSPORT_CLOSED");
      const encoded = await session.send(kind, body, key);
      if (socket.bufferedAmount + new TextEncoder().encode(encoded).byteLength > 8388608) throw new Error("E_LIVE_TRANSPORT_BACKPRESSURE");
      socket.send(encoded);
    }).finally(() => { this.queued--; });
    this.tx = task.catch(() => { this.close(); }); return task;
  }
  private async receive(frame: LiveFrame): Promise<void> {
    const body = frame.body;
    if (frame.message_type === "WELCOME") { await this.send("READY", body); return; }
    if (frame.message_type === "READY_ACK") {
      this.readyResolve?.(); this.readyResolve = undefined; this.readyReject = undefined; return;
    }
    if (frame.message_type === "PING") { await this.send("PONG", body); return; }
    if (frame.message_type === "PONG") return;
    if (frame.message_type === "PROJECTION") { this.onProjection(structuredClone(body)); return; }
    const pending = this.pending;
    if (!pending || body["batch_id"] !== pending.batchId || body["run_id"] !== pending.runId ||
        body["stream_id"] !== pending.streamId || body["generation"] !== pending.generation) throw new Error("E_LIVE_TRANSPORT_ACK_BINDING");
    if (frame.message_type === "NACK") {
      clearTimeout(pending.timer); this.pending = undefined;
      pending.reject(new Error("E_LIVE_TRANSPORT_CAPTURE_REJECTED")); this.close(); return;
    }
    if (frame.message_type !== "ACK" || BigInt(body["sequence"] as string) > BigInt(pending.last)) throw new Error("E_LIVE_TRANSPORT_ACK_BINDING");
    await pending.spool.acknowledge(pending.runId, pending.streamId, pending.generation,
      body["sequence"] as string, body["content_hash"] as string);
    if (body["sequence"] === pending.last) {
      clearTimeout(pending.timer); this.pending = undefined; pending.resolve();
    }
  }
  async sendCapture(spool: LiveCaptureSpool): Promise<void> {
    if (this.pending || !this.session?.ready || this.session.role !== "CAPTURE_PRODUCER") throw new Error("E_LIVE_TRANSPORT_CAPTURE_OWNER");
    const events = await spool.readPending();
    const first = events[0]; if (!first) return;
    const body: Record<string, unknown> = {run_id: first.run_id, stream_id: first.stream_id,
      generation: first.generation, batch_id: crypto.randomUUID(), first_sequence: first.sequence,
      last_sequence: events.at(-1)?.sequence, events};
    while (canonicalBytes(body).byteLength > 250000 && events.length > 1) {
      events.pop(); body["last_sequence"] = events.at(-1)?.sequence;
    }
    // No second caller can claim the owner after the asynchronous durable read.
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- TypeScript does not model another caller changing this field across await.
    if (this.pending) throw new Error("E_LIVE_TRANSPORT_CAPTURE_OWNER");
    const ack = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { this.close(); }, 15000);
      this.pending = {batchId: body["batch_id"] as string, runId: first.run_id, streamId: first.stream_id,
        generation: first.generation, last: body["last_sequence"] as string, spool, resolve, reject, timer};
    });
    try { await this.send("CAPTURE_BATCH", body); } catch { this.close(); }
    await ack;
  }
  sendUi(kind: "WATCHLIST_ADD" | "WATCHLIST_REMOVE" | "SELECT_ACTIVE" | "REFRESH" | "STOP_SESSION", bindingId?: string): Promise<void> {
    if (!this.session?.ready || this.session.role !== "UI_SUBSCRIBER") return Promise.reject(new Error("E_LIVE_TRANSPORT_ROLE"));
    return this.send(kind, {run_id: this.session.runId, ...(kind === "STOP_SESSION" ? {} : {binding_id: bindingId})});
  }
  sendHealth(bindingId: string | null, code: "HIDDEN" | "NAVIGATED" | "DOM_UNSTABLE" | "PROFILE_EXPIRED" | "SPOOL_CAPACITY" | "WORKER_RESTART" | "CAPTURE_REJECTED"): Promise<void> {
    if (!this.session?.ready || this.session.role !== "CAPTURE_PRODUCER") return Promise.reject(new Error("E_LIVE_TRANSPORT_ROLE"));
    return this.send("HEALTH", {run_id: this.session.runId, binding_id: bindingId, code});
  }
  stopCapture(bindingId: string): Promise<void> {
    if (!this.session?.ready || this.session.role !== "CAPTURE_PRODUCER") return Promise.reject(new Error("E_LIVE_TRANSPORT_ROLE"));
    return this.send("STOP_CAPTURE", {run_id: this.session.runId, binding_id: bindingId});
  }
  close(): void {
    this.retired = true;
    const socket = this.socket; this.socket = undefined;
    if (socket) { socket.onopen = null; socket.onclose = null; socket.onmessage = null; socket.onerror = null; socket.close(1000, "TRANSPORT_CLOSED"); }
    this.key?.fill(0); this.key = undefined; this.session = undefined;
    this.readyReject?.(new Error("E_LIVE_TRANSPORT_CLOSED")); this.readyReject = undefined; this.readyResolve = undefined;
    if (this.pending) {
      clearTimeout(this.pending.timer); this.pending.reject(new Error("E_LIVE_TRANSPORT_UNACKNOWLEDGED")); this.pending = undefined;
    }
    if (socket) this.onHealth("TRANSPORT_CLOSED");
  }
}
