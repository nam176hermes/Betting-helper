import type {CanonicalRegistry} from "../canonical.js";
import {Spool} from "../spool.js";
import {AuthenticatedLoopback} from "../security/loopback.js";
import {projectBeforePersistence, type ProjectionContext, type PersistableSanitizedObservationV1} from "../security/redaction.js";
import type {OfflineRunContext} from "./context.js";
import {validateRaw, validateFrame, validateContext} from "./validators.js";
import {SessionState, verifyFrame} from "./protocol.js";

const checked = (validate: (value: unknown) => boolean) => (value: unknown): void => {
  if (!validate(value)) throw new Error("E_OFFLINE_SCHEMA");
};
export async function startOfflineSession(context: OfflineRunContext,
  credentials: {sessionId: string; key: number[]}[], batchSize: 1 | 32 = 1) {
  checked(validateContext)(context);
  if (location.origin !== context.allowed_extension_origin) throw new Error("E_OFFLINE_ORIGIN");
  const registry = await (await fetch(new URL("./canonical-registry.json", import.meta.url))).json() as CanonicalRegistry;
  const spool = new Spool({browser_run_id: context.browser_run_id, producer_id: context.producer_id,
    stream_id: context.stream_id, generation: context.generation, registry,
    normalByteLimit: BigInt(context.normal_spool_limit_bytes), validateRaw: checked(validateRaw)});
  const projection: ProjectionContext = {sourceKind: context.source_kind, runId: context.run_id,
    browserRunId: context.browser_run_id, streamId: context.stream_id, generation: context.generation,
    allowedKinds: ["TERMINAL"], canonicalRegistry: registry, validateRaw: checked(validateRaw)};
  const client = new AuthenticatedLoopback({context, spool, batchSize, validateContext: checked(validateContext),
    validateFrame: checked(validateFrame), credentials: () => {
      const value = credentials.shift();
      if (!value) throw new Error("E_OFFLINE_CREDENTIALS_EXHAUSTED");
      const key = new Uint8Array(value.key); value.key.fill(0);
      return Promise.resolve({sessionId: value.sessionId, key});
    }});
  return {spool, client, projection};
}

type Command = {operation: string; context?: OfflineRunContext;
  credentials?: {sessionId: string; key: number[]}[]; observations?: unknown[]; batchSize?: 1 | 32};

/** Adversarial browser peer uses the real codec/transport; it never impersonates Spool. */
async function wireProbe(request: Command): Promise<unknown[]> {
  const context = request.context, credential = request.credentials?.[0], rows = request.observations;
  if (!context || !credential || !rows?.length) throw new Error("E_OFFLINE_COMMAND");
  checked(validateContext)(context);
  const key = new Uint8Array(credential.key); credential.key.fill(0);
  const state = new SessionState(credential.sessionId, context.run_id, "CLIENT", checked(validateFrame));
  const socket = new WebSocket(context.backend_url);
  const inbox: string[] = [];
  let wake: (() => void) | undefined, closed = false;
  socket.onmessage = event => {
    if (typeof event.data !== "string" || inbox.length >= 8) {socket.close(); return;}
    inbox.push(event.data); wake?.();
  };
  socket.onclose = () => {closed = true; wake?.();};
  const receive = async () => {
    if (!inbox.length && !closed) await new Promise<void>(resolve => {
      const timer = setTimeout(() => {closed = true; resolve();}, 5000);
      wake = () => {clearTimeout(timer); wake = undefined; resolve();};
    });
    const data = inbox.shift();
    if (data === undefined) throw new Error("E_OFFLINE_TRANSPORT");
    return verifyFrame(data, key, state);
  };
  try {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {reject(new Error("E_OFFLINE_TRANSPORT"));}, 5000);
      socket.onopen = () => {clearTimeout(timer); resolve();};
      socket.onerror = () => {clearTimeout(timer); reject(new Error("E_OFFLINE_TRANSPORT"));};
    });
    const nonce = btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))
      .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
    socket.send(await state.send("HELLO", {run_id:context.run_id, client_nonce:nonce}, key));
    const welcome = await receive();
    socket.send(await state.send("READY", welcome.body, key));
    await receive();
    const positions = rows as {sequence: string}[];
    socket.send(await state.send("BATCH", {batch_id:crypto.randomUUID(), run_id:context.run_id,
      browser_run_id:context.browser_run_id, producer_id:context.producer_id, stream_id:context.stream_id,
      generation:context.generation, first_sequence:positions[0]?.sequence,
      last_sequence:positions.at(-1)?.sequence, observations:rows}, key));
    const result = [], first = await receive(); result.push(first);
    if (first.message_type === "ACK" && first.body.highest_contiguous_sequence !== positions.at(-1)?.sequence) result.push(await receive());
    return result;
  } finally {socket.close(); key.fill(0);}
}
if (typeof document === "undefined") {
  const workerId = crypto.randomUUID();
  let active: Awaited<ReturnType<typeof startOfflineSession>> | undefined;
  let queue = Promise.resolve();
  self.onmessage = (event: MessageEvent<Command>) => {
    queue = queue.then(async () => {
      try {
        const request = event.data;
        if (request.operation === "INIT" && request.context && request.credentials && !active) {
          active = await startOfflineSession(request.context, request.credentials, request.batchSize);
        } else if (request.operation === "WIRE" && active) {
          self.postMessage({status: "OK", origin: location.origin, workerId,
            frames: await wireProbe(request)});
          return;
        } else if (["APPEND", "APPEND_PRECOMMIT", "FORGED"].includes(request.operation) && active && request.observations) {
          if (request.operation === "APPEND_PRECOMMIT") {
            // eslint-disable-next-line @typescript-eslint/unbound-method -- preserve native receiver.
            const add = IDBObjectStore.prototype.add;
            IDBObjectStore.prototype.add = function (...args: Parameters<typeof add>): IDBRequest<IDBValidKey> {
              const result = add.apply(this, args);
              if (this.name === "spool_entries_v1") result.addEventListener("success", () => {
                self.postMessage({status: "CHECKPOINT", stage: "BEFORE_IDB_COMMIT", workerId,
                  runId: active?.projection.runId, origin: location.origin});
                for (;;) { /* Actual transaction callback held until owned worker termination. */ }
              });
              return result;
            };
          }
          if (request.operation === "FORGED") {
            for (const row of request.observations) {
              const bytes = new TextEncoder().encode(JSON.stringify(row));
              await active.spool.append({canonicalSanitizedBytes: bytes,
                validatedRawObservation: {canonicalBytes: bytes}} as PersistableSanitizedObservationV1);
            }
          } else {
          for (const row of request.observations) await active.spool.append(await projectBeforePersistence(row, active.projection));
          }
        } else if (request.operation === "PIPELINE" && active && request.observations) {
          const session = active, rows = request.observations;
          for (const row of rows.slice(0, 32)) await session.spool.append(await projectBeforePersistence(row, session.projection));
          let failure: Error | undefined;
          const writer = (async () => {
            for (const row of rows.slice(32)) {
              if (failure) break;
              await session.spool.append(await projectBeforePersistence(row, session.projection));
            }
          })().catch((error: unknown) => {failure = error instanceof Error ? error : new Error("E_OFFLINE_PIPELINE");});
          const delivery = session.client.flushPending().catch((error: unknown) => {failure = error instanceof Error ? error : new Error("E_OFFLINE_PIPELINE");});
          await Promise.all([writer, delivery]);
          if (failure) throw failure;
          await session.client.flushPending();
        } else if (request.operation === "CONCURRENT_APPEND_ACK" && active && request.observations?.[0]) {
          const pending = await active.spool.readPendingObservations(32), last = pending.at(-1)?.record;
          if (!last) throw new Error("E_OFFLINE_TEST_PENDING");
          const input = await projectBeforePersistence(request.observations[0], active.projection);
          await Promise.all([active.spool.append(input), active.spool.persistVerifiedAck(
            last.position.generation_key.generation, last.position.sequence, last.cursor_hash)]);
        } else if (request.operation === "FLUSH_PREACK" && active) {
          active.spool.persistVerifiedAck = (generation, sequence, cursorHash): Promise<void> => {
            self.postMessage({status: "CHECKPOINT", stage: "AFTER_ACK_BEFORE_LOCAL_PERSIST",
              workerId, runId: active?.projection.runId, origin: location.origin,
              generation, sequence, cursorHash});
            for (;;) { /* Owned worker dies after actual ACK delivery, before local persistence. */ }
          };
          await active.client.flushPending();
        } else if (request.operation === "FLUSH" && active) {
          await active.client.flushPending();
        } else if (request.operation === "TAMPER_REGISTRY" && active) {
          const domain = active.projection.canonicalRegistry.domains.find(row => row.artifact_type === "RawObservation");
          if (!domain) throw new Error("E_OFFLINE_TEST_REGISTRY");
          (domain as {domain: string}).domain = "changed-domain";
        } else if (request.operation === "TAMPER_RECORD" && active) {
          const browserRunId = active.projection.browserRunId;
          const database = await new Promise<IDBDatabase>((resolve, reject) => {
            const open = indexedDB.open(`hybrid-discovery-v6.2-working-${browserRunId}`, 1);
            open.onsuccess = () => {resolve(open.result);};
            open.onerror = () => {reject(new Error("E_OFFLINE_TEST_OPEN"));};
          });
          try {
            await new Promise<void>((resolve, reject) => {
              const transaction = database.transaction("spool_entries_v1", "readwrite", {durability:"strict"});
              const cursor = transaction.objectStore("spool_entries_v1").openCursor();
              cursor.onsuccess = () => {
                if (!cursor.result) {transaction.abort(); return;}
                const row = cursor.result.value as {spool_record: {cursor_hash: string}};
                row.spool_record.cursor_hash = "f".repeat(64); cursor.result.update(row);
              };
              transaction.oncomplete = () => {resolve();};
              transaction.onabort = () => {reject(new Error("E_OFFLINE_TEST_MUTATION"));};
            });
          } finally {database.close();}
        } else if (request.operation === "CLOSE" && active) {
          await active.client.close();
        } else if (request.operation !== "READ" || !active) throw new Error("E_OFFLINE_COMMAND");
        self.postMessage({status: "OK", origin: location.origin, workerId,
          state: await active.spool.readVerifiedStreamState(),
          retained: (await active.spool.exportRetainedObservations()).map(bytes => new TextDecoder().decode(bytes))});
      } catch (error) {
        const code = error instanceof Error && /^E_[A-Z0-9_]+$/.test(error.message) ? error.message : "E_OFFLINE_COMMAND";
        self.postMessage({status: "REJECTED", code});
      }
    });
  };
} else {
  let worker = new Worker(new URL(import.meta.url), {type: "module"});
  const checkpoints: unknown[] = [];
  let cancel: (() => void) | undefined;
  let queue = Promise.resolve<unknown>(undefined);
  const command = (request: Command): Promise<unknown> => {
    queue = queue.then(() => new Promise((resolve, reject) => {
      const timer = setTimeout(() => {reject(new Error("E_OFFLINE_WORKER_TIMEOUT"));}, 120000);
      cancel = () => {clearTimeout(timer); reject(new Error("E_OFFLINE_WORKER_TERMINATED"));};
      worker.onmessage = event => {
        const value = event.data as {status?: string};
        if (value.status === "CHECKPOINT") {checkpoints.push(value); return;}
        clearTimeout(timer); cancel = undefined; resolve(value);
      };
      worker.onerror = () => {clearTimeout(timer); reject(new Error("E_OFFLINE_WORKER"));};
      worker.postMessage(request);
    }));
    return queue;
  };
  Object.assign(globalThis, {offlineProbe: {command, checkpoints, restartWorker: () => {
    cancel?.(); cancel = undefined;
    worker.terminate(); worker = new Worker(new URL(import.meta.url), {type: "module"});
    queue = Promise.resolve(); return {status: "WORKER_TERMINATED"};
  }}});
}
