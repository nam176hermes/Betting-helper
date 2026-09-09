import { ContractNotImplementedError } from "../errors.js";
import {parseStrictJson} from "../canonical.js";
import type {OfflineRunContext} from "../offline/context.js";
import {SessionState, verifyFrame, type OfflineFrame} from "../offline/protocol.js";
import type {Spool} from "../spool.js";

export type OfflineClientOptions = {
  context: OfflineRunContext; spool: Spool;
  batchSize?: 1 | 32;
  credentials: () => Promise<{sessionId: string; key: Uint8Array}>;
  validateContext: (value: unknown) => void; validateFrame: (value: unknown) => void;
};

export class AuthenticatedLoopback {
  readonly taskId = "SEC0-T06";
  private readonly options: OfflineClientOptions;
  private socket: WebSocket | undefined;
  private state: SessionState | undefined;
  private key: Uint8Array | undefined;
  private readonly sessions = new Set<string>();
  private inbox: string[] = [];
  private wake: (() => void) | undefined;
  private failure: Error | undefined;
  private stopped = false;
  private queue: Promise<void> = Promise.resolve();
  private readonly started = performance.now();

  constructor(options?: OfflineClientOptions) {
    if (!options) throw new ContractNotImplementedError("SEC0-T06");
    try {
      options.validateContext(options.context);
      const context = options.context as unknown as Record<string, unknown>;
      if (context.backend_url !== "ws://127.0.0.1:8765/offline" ||
          context.source_kind !== "SYNTHETIC_TEST" || context.live_authority ||
          context.money_authority || context.provider_authority) throw new Error();
    } catch { throw new Error("E_OFFLINE_CONTEXT"); }
    this.options = {...options, context: Object.freeze({...options.context})};
  }

  private fail(code: string): void {
    this.failure = new Error(code);
    this.wake?.();
  }
  private async receive(timeout = 30000): Promise<OfflineFrame> {
    const deadline = performance.now() + timeout;
    while (!this.inbox.length) {
      if (this.failure) throw this.failure;
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error("E_OFFLINE_TRANSPORT");
      await new Promise<void>(resolve => {
        const timer = setTimeout(() => {this.wake = undefined; resolve();}, remaining);
        this.wake = () => {clearTimeout(timer); this.wake = undefined; resolve();};
      });
    }
    const data = this.inbox.shift();
    if (data === undefined || !this.key || !this.state) throw new Error("E_OFFLINE_STATE");
    return verifyFrame(data, this.key, this.state);
  }
  private async send(type: string, body: Record<string, unknown>): Promise<void> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !this.state || !this.key) {
      throw new Error("E_OFFLINE_TRANSPORT");
    }
    this.socket.send(await this.state.send(type, body, this.key));
  }
  private async connect(): Promise<void> {
    this.socket?.close();
    this.key?.fill(0);
    this.inbox = []; this.failure = undefined;
    const {context, credentials, validateFrame} = this.options;
    const credential = await credentials();
    if (this.sessions.has(credential.sessionId) || credential.key.byteLength !== 32) {
      throw new Error("E_OFFLINE_SESSION_REUSE");
    }
    this.sessions.add(credential.sessionId);
    this.key = new Uint8Array(credential.key);
    this.state = new SessionState(credential.sessionId, context.run_id, "CLIENT", validateFrame);
    const socket = new WebSocket(context.backend_url);
    this.socket = socket;
    socket.onmessage = event => {
      if (this.socket !== socket) return;
      if (typeof event.data !== "string" || new TextEncoder().encode(event.data).length > 262144 || this.inbox.length >= 8) {
        this.fail("E_OFFLINE_FRAME_SIZE"); socket.close(); return;
      }
      this.inbox.push(event.data); this.wake?.();
    };
    socket.onclose = socket.onerror = () => {
      if (this.socket === socket && !this.failure) this.fail("E_OFFLINE_TRANSPORT");
    };
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {socket.close(); reject(new Error("E_OFFLINE_TRANSPORT"));}, 5000);
      socket.onopen = () => {clearTimeout(timer); resolve();};
      socket.addEventListener("error", () => {clearTimeout(timer); reject(new Error("E_OFFLINE_TRANSPORT"));}, {once: true});
    });
    const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))
      .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
    await this.send("HELLO", {run_id: context.run_id, client_nonce: nonce});
    const welcome = await this.receive(5000);
    await this.send("READY", welcome.body);
    await this.receive(5000);
  }
  private serial(work: () => Promise<void>): Promise<void> {
    const result = this.queue.then(async () => {
      if (this.stopped || performance.now() - this.started > 600000) throw new Error("E_OFFLINE_STOPPED");
      try {await work();} catch (error) {this.stopped = true; this.socket?.close(); throw error;}
    });
    this.queue = result.catch(() => undefined);
    return result;
  }
  start(): Promise<void> {return this.serial(async () => {await this.connect();});}

  flushPending(): Promise<void> {
    return this.serial(async () => {
      const {spool, context} = this.options;
      let retryStarted: number | undefined, retry = 0;
      for (;;) {
        if (performance.now() - this.started > 600000) throw new Error("E_OFFLINE_STOPPED");
        try {
          if (!this.state?.ready || this.socket?.readyState !== WebSocket.OPEN) await this.connect();
          const pending = await spool.readPendingObservations(this.options.batchSize ?? 1);
          if (!pending.length) return;
          const identity = {batch_id: crypto.randomUUID(), run_id: context.run_id,
            browser_run_id: context.browser_run_id, producer_id: context.producer_id,
            stream_id: context.stream_id, generation: context.generation};
          const head = pending[0], tail = pending.at(-1);
          if (!head || !tail) throw new Error("E_OFFLINE_STATE");
          const first = head.record.position.sequence, last = tail.record.position.sequence;
          await this.send("BATCH", {...identity, first_sequence: first, last_sequence: last,
            observations: pending.map(row => parseStrictJson(row.canonicalSanitizedBytes))});
          const frame = await this.receive();
          if (Object.entries(identity).some(([name, value]) => frame.body[name] !== value)) throw new Error("E_OFFLINE_ACK_IDENTITY");
          if (frame.message_type === "NACK") throw new Error("E_OFFLINE_NACK");
          const sequence = frame.body.highest_contiguous_sequence;
          if (frame.message_type !== "ACK" || typeof sequence !== "string" ||
              BigInt(sequence) < BigInt(first) || BigInt(sequence) > BigInt(last)) throw new Error("E_OFFLINE_ACK_RANGE");
          await spool.persistVerifiedAck(context.generation, sequence, frame.body.cursor_hash as string);
          if (sequence !== last) {
            const nack = await this.receive();
            if (nack.message_type !== "NACK" || Object.entries(identity).some(([name, value]) => nack.body[name] !== value)) {
              throw new Error("E_OFFLINE_NACK_IDENTITY");
            }
            throw new Error("E_OFFLINE_NACK");
          }
          retryStarted = undefined; retry = 0;
        } catch (error) {
          if (!(error instanceof Error) || error.message !== "E_OFFLINE_TRANSPORT") throw error;
          retryStarted ??= performance.now();
          const delay = Math.min(250 * 2 ** retry++, 4000) + (crypto.getRandomValues(new Uint8Array(1))[0] ?? 0) % 101;
          if (performance.now() - retryStarted + delay > 30000) throw new Error("E_OFFLINE_RECONNECT_TIMEOUT", {cause: error});
          await new Promise(resolve => setTimeout(resolve, delay));
          this.state = undefined;
        }
      }
    });
  }
  async close(): Promise<void> {
    this.stopped = true; this.socket?.close(); this.fail("E_OFFLINE_STOPPED");
    await this.queue; this.key?.fill(0); this.key = undefined;
  }
}
