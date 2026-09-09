import type {CanonicalRegistry} from "../canonical.js";
import {Spool} from "../spool.js";
import {AuthenticatedLoopback} from "../security/loopback.js";
import {projectBeforePersistence, type ProjectionContext} from "../security/redaction.js";
import type {OfflineRunContext} from "./context.js";
import {validateRaw, validateFrame, validateContext} from "./validators.js";

const checked = (validate: (value: unknown) => boolean) => (value: unknown): void => {
  if (!validate(value)) throw new Error("E_OFFLINE_SCHEMA");
};
export async function startOfflineSession(context: OfflineRunContext,
  credentials: {sessionId: string; key: number[]}[]) {
  checked(validateContext)(context);
  if (location.origin !== context.allowed_extension_origin) throw new Error("E_OFFLINE_ORIGIN");
  const registry = await (await fetch(new URL("./canonical-registry.json", import.meta.url))).json() as CanonicalRegistry;
  const spool = new Spool({browser_run_id: context.browser_run_id, producer_id: context.producer_id,
    stream_id: context.stream_id, generation: context.generation, registry,
    normalByteLimit: BigInt(context.normal_spool_limit_bytes), validateRaw: checked(validateRaw)});
  const projection: ProjectionContext = {sourceKind: context.source_kind, runId: context.run_id,
    browserRunId: context.browser_run_id, streamId: context.stream_id, generation: context.generation,
    allowedKinds: ["TERMINAL"], canonicalRegistry: registry, validateRaw: checked(validateRaw)};
  const client = new AuthenticatedLoopback({context, spool, validateContext: checked(validateContext),
    validateFrame: checked(validateFrame), credentials: () => {
      const value = credentials.shift();
      if (!value) throw new Error("E_OFFLINE_CREDENTIALS_EXHAUSTED");
      const key = new Uint8Array(value.key); value.key.fill(0);
      return Promise.resolve({sessionId: value.sessionId, key});
    }});
  return {spool, client, projection};
}

type Command = {operation: string; context?: OfflineRunContext;
  credentials?: {sessionId: string; key: number[]}[]; observations?: unknown[]};
if (typeof document === "undefined") {
  let active: Awaited<ReturnType<typeof startOfflineSession>> | undefined;
  let queue = Promise.resolve();
  self.onmessage = (event: MessageEvent<Command>) => {
    queue = queue.then(async () => {
      try {
        const request = event.data;
        if (request.operation === "INIT" && request.context && request.credentials && !active) {
          active = await startOfflineSession(request.context, request.credentials);
        } else if (request.operation === "APPEND" && active && request.observations) {
          for (const row of request.observations) await active.spool.append(await projectBeforePersistence(row, active.projection));
        } else if (request.operation === "FLUSH" && active) {
          await active.client.flushPending();
        } else if (request.operation === "CLOSE" && active) {
          await active.client.close();
        } else if (request.operation !== "READ" || !active) throw new Error("E_OFFLINE_COMMAND");
        self.postMessage({status: "OK", origin: location.origin,
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
  let queue = Promise.resolve<unknown>(undefined);
  const command = (request: Command): Promise<unknown> => {
    queue = queue.then(() => new Promise((resolve, reject) => {
      const timer = setTimeout(() => {reject(new Error("E_OFFLINE_WORKER_TIMEOUT"));}, 120000);
      worker.onmessage = event => {clearTimeout(timer); resolve(event.data as unknown);};
      worker.onerror = () => {clearTimeout(timer); reject(new Error("E_OFFLINE_WORKER"));};
      worker.postMessage(request);
    }));
    return queue;
  };
  Object.assign(globalThis, {offlineProbe: {command, restartWorker: () => {
    worker.terminate(); worker = new Worker(new URL(import.meta.url), {type: "module"});
    queue = Promise.resolve(); return {status: "WORKER_TERMINATED"};
  }}});
}
