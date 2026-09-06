import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";

export const contractNotImplemented = (): never => {
  throw new Error("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04");
};

export const persistIndexedDbSentinel = async (
  checkpoint: string,
  sentinel = "HD636_INDEXEDDB_SENTINEL",
): Promise<string> => {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("hd636-crash-harness", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("checkpoints");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction("checkpoints", "readwrite");
    transaction.objectStore("checkpoints").put(sentinel, checkpoint);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
  return sentinel;
};

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const vectorIndex = process.argv.indexOf("--vector-id");
  const vectorId = process.argv[vectorIndex + 1];
  if (!vectorId) contractNotImplemented();
  const readyIndex = process.argv.indexOf("--ready");
  const readyPath = process.argv[readyIndex + 1];
  if (readyIndex >= 0 && readyPath) writeFileSync(readyPath, JSON.stringify({ vectorId }));
  if (process.argv.includes("--hold")) setInterval(() => undefined, 1000);
  else process.stdout.write(JSON.stringify({ vectorId }));
}
