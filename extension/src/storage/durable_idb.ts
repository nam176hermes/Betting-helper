/** Shared native IndexedDB completion and exact-copy helpers; no source schemas. */
export const identicalEntry = (left: unknown, right: unknown): boolean => {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  const prototype: unknown = Object.getPrototypeOf(left);
  if ((prototype !== Object.prototype && prototype !== Array.prototype) || Object.getPrototypeOf(right) !== prototype) return false;
  if (Array.isArray(left) && Array.isArray(right) && left.length !== right.length) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) &&
    identicalEntry((left as Record<string, unknown>)[key], (right as Record<string, unknown>)[key]));
};
export const requestValue = <T>(request: IDBRequest<T>): Promise<T> => new Promise((resolve, reject) => {
  request.onsuccess = () => { resolve(request.result); };
  request.onerror = () => { reject(request.error ?? new Error("E_SPOOL_REQUEST")); };
});
export const completion = (transaction: IDBTransaction): Promise<void> => new Promise((resolve, reject) => {
  transaction.oncomplete = () => { resolve(); };
  transaction.onabort = () => { reject(transaction.error ?? new Error("E_SPOOL_ABORT")); };
  transaction.onerror = () => { reject(transaction.error ?? new Error("E_SPOOL_TRANSACTION")); };
});
