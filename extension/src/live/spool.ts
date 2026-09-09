/** New namespace, strict live records and native durable transactions. */
import { canonicalBytes } from "../canonical.js";
import { completion, identicalEntry, requestValue } from "../storage/durable_idb.js";
import { validateLiveRecord, type LiveEvent, type SchemaValidator } from "./contracts.js";
import { liveEventHash } from "./protocol.js";

type State = { next: string; hash: string; ack: string; ackHash: string; bytes: string };
type Options = { runId: string; streamId: string; generation: string; bindingId: string;
  documentEpoch: string; profileHash: string; validate: SchemaValidator; maxBytes?: bigint };
const stores = ["entries", "state"];
const initial = (): State => ({next: "1", hash: "0".repeat(64), ack: "0", ackHash: "0".repeat(64), bytes: "0"});
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const integer = (value: string): bigint => {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) > 9223372036854775807n) throw new Error("E_LIVE_SPOOL_INTEGER");
  return BigInt(value);
};
export class LiveCaptureSpool {
  private writes: Promise<void> = Promise.resolve();
  private readonly options: Options;
  constructor(options: Options) {
    if (![options.runId, options.streamId, options.bindingId, options.documentEpoch].every(v => uuid.test(v)) ||
        !/^[a-f0-9]{64}$/.test(options.profileHash) || typeof options.validate !== "function" ||
        (options.maxBytes ?? 133169152n) < 1024n || (options.maxBytes ?? 133169152n) > 133169152n) throw new Error("E_LIVE_SPOOL_CONFIG");
    integer(options.generation); this.options = {...options};
  }
  private key(sequence?: string): string[] {
    const o = this.options, key = [o.streamId, o.generation.padStart(19, "0")];
    return sequence === undefined ? key : [...key, sequence.padStart(19, "0")];
  }
  private open(): Promise<IDBDatabase> {
    const name = `betting-helper-live-v1-${this.options.runId}`;
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = event => {
        if (event.oldVersion !== 0) { request.transaction?.abort(); return; }
        const entries = request.result.createObjectStore("entries");
        entries.createIndex("observation_id", "observation_id", {unique: true});
        request.result.createObjectStore("state");
      };
      request.onerror = () => { reject(new Error("E_LIVE_SPOOL_OPEN")); };
      request.onblocked = () => { reject(new Error("E_LIVE_SPOOL_BLOCKED")); };
      request.onsuccess = () => {
        const db = request.result;
        if (db.version !== 1 || !identicalEntry(Array.from(db.objectStoreNames), stores)) {
          db.close(); reject(new Error("E_LIVE_SPOOL_SCHEMA")); return;
        }
        db.onversionchange = () => { db.close(); }; resolve(db);
      };
    });
  }
  private async event(value: unknown): Promise<LiveEvent> {
    const event = validateLiveRecord(value, "LiveEvent", this.options.validate) as LiveEvent;
    const o = this.options, book = event.payload;
    if (event.source_kind !== "OPERATOR" || event.payload_type !== "MarketBook" ||
        event.run_id !== o.runId || event.stream_id !== o.streamId || event.generation !== o.generation ||
        book["binding_id"] !== o.bindingId || book["document_epoch"] !== o.documentEpoch ||
        book["profile_hash"] !== o.profileHash || event.observed_at_utc !== book["observed_at_utc"] ||
        event.content_hash !== await liveEventHash(event, o.validate)) throw new Error("E_LIVE_SPOOL_BINDING");
    return event;
  }
  private async snapshot(): Promise<{state: State; entries: LiveEvent[]; total: string}> {
    const db = await this.open();
    try {
      const tx = db.transaction(stores, "readonly"), done = completion(tx);
      const stateRequest = requestValue(tx.objectStore("state").get(this.key()) as IDBRequest<State | undefined>);
      const totalRequest = requestValue(tx.objectStore("state").get("total") as IDBRequest<string | undefined>);
      const allRequest = requestValue(tx.objectStore("entries").getAll() as IDBRequest<LiveEvent[]>);
      const keysRequest = requestValue(tx.objectStore("entries").getAllKeys());
      const [savedState, savedTotal, all, keys] = await Promise.all([stateRequest, totalRequest, allRequest, keysRequest, done]);
      const state = savedState ?? initial(), total = savedTotal ?? "0";
      let used = 0n;
      const chains = new Map<string, {sequence: bigint; hash: string}>();
      const streamIds = new Set<string>();
      for (const [index, row] of all.entries()) {
        validateLiveRecord(row, "LiveEvent", this.options.validate);
        if (row.run_id !== this.options.runId || row.source_kind !== "OPERATOR" || row.payload_type !== "MarketBook" ||
            !identicalEntry(keys[index], [row.stream_id, row.generation.padStart(19, "0"), row.sequence.padStart(19, "0")]) ||
            row.content_hash !== await liveEventHash(row, this.options.validate)) throw new Error("E_LIVE_SPOOL_CHAIN");
        const chainKey = row.stream_id + ":" + row.generation;
        const prior = chains.get(chainKey) ?? {sequence: 0n, hash: "0".repeat(64)};
        if (integer(row.sequence) !== prior.sequence + 1n || row.previous_hash !== prior.hash) throw new Error("E_LIVE_SPOOL_CHAIN");
        chains.set(chainKey, {sequence: integer(row.sequence), hash: row.content_hash});
        streamIds.add(row.stream_id);
        used += BigInt(canonicalBytes(row).byteLength);
      }
      if (streamIds.size > 5 || integer(total) !== used || used > (this.options.maxBytes ?? 133169152n)) throw new Error("E_LIVE_SPOOL_CAPACITY");
      const entries = all.filter(e => e.stream_id === this.options.streamId && e.generation === this.options.generation);
      let previous = "0".repeat(64), bytes = 0n;
      for (const [index, row] of entries.entries()) {
        await this.event(row);
        if (row.sequence !== String(index + 1) || row.previous_hash !== previous) throw new Error("E_LIVE_SPOOL_CHAIN");
        previous = row.content_hash; bytes += BigInt(canonicalBytes(row).byteLength);
      }
      if (!identicalEntry(Object.keys(state).sort(), Object.keys(initial()).sort()) ||
          integer(state.next) !== BigInt(entries.length + 1) || state.hash !== previous ||
          integer(state.bytes) !== bytes || integer(state.ack) > BigInt(entries.length) ||
          state.ackHash !== (state.ack === "0" ? "0".repeat(64) : entries[Number(BigInt(state.ack) - 1n)]?.content_hash)) throw new Error("E_LIVE_SPOOL_CHAIN");
      return {state, entries, total};
    } finally { db.close(); }
  }
  private serialize<T>(work: () => Promise<T>): Promise<T> {
    const task = this.writes.then(work); this.writes = task.then(() => undefined, () => undefined); return task;
  }
  private async write(previous: State, total: string, next: State, entry?: LiveEvent): Promise<void> {
    const db = await this.open();
    try {
      const tx = db.transaction(stores, "readwrite", {durability: "strict"}), done = completion(tx);
      const states = tx.objectStore("state"), state = states.get(this.key()) as IDBRequest<State | undefined>;
      const totalRequest = states.get("total") as IDBRequest<string | undefined>;
      totalRequest.onsuccess = () => {
        if (!identicalEntry(state.result ?? initial(), previous) || (totalRequest.result ?? "0") !== total) { tx.abort(); return; }
        if (entry) {
          tx.objectStore("entries").add(entry, this.key(entry.sequence));
          states.put(String(integer(total) + BigInt(canonicalBytes(entry).byteLength)), "total");
        }
        states.put(next, this.key());
      };
      await done;
    } finally { db.close(); }
  }
  append(value: unknown): Promise<LiveEvent> {
    return this.serialize(async () => {
      const event = await this.event(value);
      for (let attempt = 0; attempt < 2; attempt++) {
        const {state, entries, total} = await this.snapshot();
        const existing = entries.find(e => e.sequence === event.sequence);
        if (existing) {
          if (!identicalEntry(existing, event)) throw new Error("E_LIVE_SPOOL_CONFLICT");
          return structuredClone(existing);
        }
        if (event.sequence !== state.next || event.previous_hash !== state.hash || integer(state.next) === 9223372036854775807n) throw new Error("E_LIVE_SPOOL_SEQUENCE");
        const size = BigInt(canonicalBytes(event).byteLength);
        if (integer(total) + size > (this.options.maxBytes ?? 133169152n)) throw new Error("E_LIVE_SPOOL_CAPACITY");
        try {
          await this.write(state, total, {...state, next: String(integer(state.next) + 1n), hash: event.content_hash, bytes: String(integer(state.bytes) + size)}, event);
        } catch { if (attempt === 0) continue; throw new Error("E_LIVE_SPOOL_WRITE"); }
        const observed = (await this.snapshot()).entries.find(e => e.sequence === event.sequence);
        if (!identicalEntry(observed, event)) throw new Error("E_LIVE_SPOOL_READBACK");
        return structuredClone(event);
      }
      throw new Error("E_LIVE_SPOOL_WRITE");
    });
  }
  async readPending(limit = 32): Promise<LiveEvent[]> {
    if (!Number.isInteger(limit) || limit < 1 || limit > 32) throw new Error("E_LIVE_SPOOL_LIMIT");
    const {state, entries} = await this.snapshot();
    return entries.filter(e => BigInt(e.sequence) > BigInt(state.ack)).slice(0, limit).map(e => structuredClone(e));
  }
  async retained(): Promise<LiveEvent[]> { return (await this.snapshot()).entries; }
  acknowledge(runId: string, streamId: string, generation: string, sequence: string, hash: string): Promise<void> {
    return this.serialize(async () => {
      const {state, entries, total} = await this.snapshot(), o = this.options;
      const number = integer(sequence);
      if (runId !== o.runId || streamId !== o.streamId || generation !== o.generation || number < integer(state.ack) || number > BigInt(entries.length) ||
          hash !== (number === 0n ? "0".repeat(64) : entries[Number(number - 1n)]?.content_hash)) throw new Error("E_LIVE_SPOOL_ACK");
      await this.write(state, total, {...state, ack: sequence, ackHash: hash});
    });
  }
}
