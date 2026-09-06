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
    }>;
  }
}

window.repairProbe = Object.freeze({ readSentinel, writeSentinel });
