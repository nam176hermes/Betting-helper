import { Spool } from "../src/spool.js";

type SentinelRecord = Readonly<{
  sentinel: string;
  profileId: string;
}>;

type ProbeEvidence = Readonly<{
  extensionId: string;
  moduleSha256: string;
  moduleUrl: string;
  origin: string;
  profileId: string;
  protocol: string;
  sentinel: string | undefined;
  spoolConstructor: string;
}>;

const databaseName = "bh-r04-indexeddb-repair-probe";
const storeName = "sentinels";
const sentinelKey = "durability-sentinel";
const moduleUrl = new URL("../src/spool.js", import.meta.url).href;

const openDatabase = (): Promise<IDBDatabase> =>
  new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(storeName);
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("E_INDEXEDDB_OPEN"));
    };
  });

const moduleSha256 = async (): Promise<string> => {
  const bytes = await (await fetch(moduleUrl)).arrayBuffer();
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (value) => value.toString(16).padStart(2, "0")).join("");
};

const readRecord = async (): Promise<SentinelRecord | undefined> => {
  const database = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const request = database.transaction(storeName).objectStore(storeName).get(sentinelKey);
      request.onsuccess = () => {
        resolve(request.result as SentinelRecord | undefined);
      };
      request.onerror = () => {
        reject(request.error ?? new Error("E_INDEXEDDB_READ"));
      };
    });
  } finally {
    database.close();
  }
};

const evidence = async (
  record: SentinelRecord | undefined,
  profileId: string,
): Promise<ProbeEvidence> => ({
  extensionId: chrome.runtime.id,
  moduleSha256: await moduleSha256(),
  moduleUrl,
  origin: location.origin,
  profileId: record?.profileId ?? profileId,
  protocol: location.protocol,
  sentinel: record?.sentinel,
  spoolConstructor: Spool.name,
});

const writeSentinel = async (sentinel: string, profileId: string): Promise<ProbeEvidence> => {
  const database = await openDatabase();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(storeName, "readwrite");
      transaction.objectStore(storeName).put({ sentinel, profileId }, sentinelKey);
      transaction.oncomplete = () => {
        resolve();
      };
      transaction.onabort = () => {
        reject(transaction.error ?? new Error("E_INDEXEDDB_ABORT"));
      };
      transaction.onerror = () => {
        reject(transaction.error ?? new Error("E_INDEXEDDB_WRITE"));
      };
    });
  } finally {
    database.close();
  }
  return evidence(await readRecord(), profileId);
};

const readSentinel = async (profileId: string): Promise<ProbeEvidence> =>
  evidence(await readRecord(), profileId);

declare global {
  interface Window {
    repairProbe: Readonly<{
      readSentinel: typeof readSentinel;
      writeSentinel: typeof writeSentinel;
      startWorker: typeof startWorker;
      terminateWorker: typeof terminateWorker;
      beginWorker: typeof beginWorker;
      waitWorker: typeof waitWorker;
    }>;
  }
}

let ownedWorker: { id: string; worker: Worker } | undefined;
let workerResult: Promise<unknown> | undefined;
const beginWorker = (workerId: string, input: unknown): object => {
  workerResult = startWorker(workerId, input);
  return { worker_id: workerId };
};
const waitWorker = async (): Promise<unknown> => {
  if (!workerResult) throw new Error("E_TEST_WORKER_MISSING");
  return await workerResult;
};
const startWorker = (workerId: string, input: unknown): Promise<unknown> => {
  if (ownedWorker) throw new Error("E_TEST_WORKER_ALREADY_OWNED");
  const worker = new Worker(`indexeddb-crash-child.js?worker_id=${encodeURIComponent(workerId)}`, { type: "module" });
  ownedWorker = { id: workerId, worker };
  return new Promise((resolve, reject) => {
    worker.onmessage = event => { resolve(event.data as unknown); };
    worker.onerror = event => { reject(new Error(event.message)); };
    worker.postMessage(input);
  });
};
const terminateWorker = (workerId: string): Readonly<{ method: string; worker_id: string }> => {
  if (!ownedWorker || ownedWorker.id !== workerId) throw new Error("E_TEST_WORKER_IDENTITY");
  ownedWorker.worker.terminate();
  ownedWorker = undefined;
  return { method: "Worker.terminate", worker_id: workerId };
};

window.repairProbe = Object.freeze({ readSentinel, writeSentinel, startWorker, terminateWorker, beginWorker, waitWorker });
