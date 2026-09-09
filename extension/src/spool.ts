import { canonicalBytes, canonicalContentHash, parseStrictJson, type CanonicalRegistry } from "./canonical.js";
import type { PersistableSanitizedObservationV1 } from "./security/redaction.js";

export type SpoolRecord = Readonly<{
  readonly record_type: "SpoolRecord";
  readonly schema_version: "1";
  readonly content_hash: string;
  readonly guarantee: "EFFECTIVELY_ONCE_AFTER_DURABLE_LOCAL_SPOOL_COMMIT";
  readonly spool_record_id: string;
  readonly position: Readonly<{
    readonly generation_key: Readonly<{
      readonly stream: Readonly<{
        readonly browser_run_id: string;
        readonly producer_id: string;
        readonly stream_id: string;
      }>;
      readonly generation: string;
    }>;
    readonly sequence: string;
  }>;
  readonly raw_observation_id: string;
  readonly raw_observation_content_hash: string;
  readonly previous_cursor_hash: string;
  readonly cursor_hash: string;
  readonly cursor_hash_verification: "VERIFIED_HD_CURSOR_STEP_V1";
  readonly spool_state:
    | "VALIDATED"
    | "DURABLY_SPOOLED"
    | "ACK_VERIFIED"
    | "RETAINED_UNTIL_WHOLE_RUN_DESTRUCTION";
  readonly committed_at: string;
  readonly payload_size_bytes: string;
  readonly individual_deletion_eligible: false;
}>;

const H0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c";
const stores: [string, string] = ["stream_state_v1", "spool_entries_v1"];
const maximum = 9223372036854775807n;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const decimal = (value: string): bigint => {
  if (!/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) > maximum) {
    throw new Error("E_SPOOL_INTEGER");
  }
  return BigInt(value);
};

type Options = Readonly<{
  browser_run_id: string;
  producer_id: string;
  stream_id: string;
  generation: string;
  registry: CanonicalRegistry;
  validateRaw: (value: unknown) => void;
  normalByteLimit?: bigint;
}>;
type Observation = Readonly<{
  raw_observation_id: string;
  content_hash: string;
  discovery_run_id: string;
  stream_id: string;
  generation: string;
  sequence: string;
  context: Readonly<{ browser_run_id: string }>;
}>;
type State = {
  storage_schema_version: string;
  producer_id: string;
  stream_id: string;
  active_generation: string;
  next_sequence: string;
  last_cursor_hash: string;
  ack_generation: string;
  ack_sequence: string;
  ack_cursor_hash: string;
  normal_bytes_used: string;
  terminal_reserve_bytes_used: string;
  generation_state: "ACTIVE" | "CLOSED";
};
type Entry = Readonly<{
  storage_schema_version: string;
  spool_record: SpoolRecord;
  sanitized_observation: Observation;
}>;
const same = (left: unknown, right: unknown): boolean =>
  JSON.stringify(left) === JSON.stringify(right);
const requestValue = <T>(request: IDBRequest<T>): Promise<T> => new Promise((resolve, reject) => {
  request.onsuccess = () => { resolve(request.result); };
  request.onerror = () => { reject(request.error ?? new Error("E_SPOOL_REQUEST")); };
});
const completion = (transaction: IDBTransaction): Promise<void> => new Promise((resolve, reject) => {
  transaction.oncomplete = () => { resolve(); };
  transaction.onabort = () => { reject(transaction.error ?? new Error("E_SPOOL_ABORT")); };
  transaction.onerror = () => { reject(transaction.error ?? new Error("E_SPOOL_TRANSACTION")); };
});

/** Offline durable sink. Only the still-gated projector may construct its input. */
export class Spool {
  constructor(private readonly options?: Options) {}

  private configuration(): Options {
    const value = this.options;
    if (!value || ![value.browser_run_id, value.producer_id, value.stream_id].every(id => uuid.test(id))) {
      throw new Error("E_SPOOL_BINDING");
    }
    decimal(value.generation);
    if (typeof value.validateRaw !== "function") throw new Error("E_SPOOL_BINDING");
    const limit = value.normalByteLimit ?? 133169152n;
    if (typeof limit !== "bigint" || limit < 1024n || limit > 133169152n) throw new Error("E_SPOOL_CAPACITY");
    return value;
  }

  private initial(): State {
    const value = this.configuration();
    return {
      storage_schema_version: "browser-stream-state/v1",
      producer_id: value.producer_id, stream_id: value.stream_id,
      active_generation: value.generation, next_sequence: "1", last_cursor_hash: H0,
      ack_generation: value.generation, ack_sequence: "0", ack_cursor_hash: H0,
      normal_bytes_used: "0", terminal_reserve_bytes_used: "0", generation_state: "ACTIVE",
    };
  }

  private key(sequence?: string): string[] {
    const value = this.configuration();
    const key = [value.producer_id, value.stream_id];
    return sequence === undefined ? key : [...key, value.generation.padStart(19, "0"), sequence.padStart(19, "0")];
  }

  private open(): Promise<IDBDatabase> {
    const name = `hybrid-discovery-v6.2-working-${this.configuration().browser_run_id}`;
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = event => {
        if (event.oldVersion !== 0 || event.newVersion !== 1) {
          request.transaction?.abort();
          return;
        }
        request.result.createObjectStore(stores[0], { autoIncrement: false });
        const rows = request.result.createObjectStore(stores[1], { autoIncrement: false });
        for (const field of ["spool_record_id", "raw_observation_id"]) {
          rows.createIndex(`by_${field}`, `spool_record.${field}`, { unique: true, multiEntry: false });
        }
      };
      request.onerror = () => { reject(request.error ?? new Error("E_SPOOL_OPEN")); };
      request.onblocked = () => { reject(new Error("E_SPOOL_BLOCKED")); };
      request.onsuccess = () => {
        const database = request.result;
        if (database.name !== name || database.version !== 1 || !same(Array.from(database.objectStoreNames), stores.toSorted())) {
          database.close();
          reject(new Error("E_SPOOL_STORAGE_SCHEMA"));
          return;
        }
        database.onversionchange = () => { database.close(); };
        resolve(database);
      };
    });
  }

  private async snapshot(): Promise<{ state: State; entries: Entry[] }> {
    // ponytail: scan retained rows to verify the chain; add verified checkpoints only if run size demands it.
    const database = await this.open();
    try {
      const transaction = database.transaction(stores, "readonly");
      const done = completion(transaction);
      const stateRequest = requestValue(transaction.objectStore(stores[0]).get(this.key()) as IDBRequest<State | undefined>);
      const entries: Entry[] = [];
      const rows = transaction.objectStore(stores[1]);
      const cursor = rows.openCursor(IDBKeyRange.bound(this.key("0"), this.key(String(maximum)), false, false), "next");
      cursor.onsuccess = () => {
        if (cursor.result) {
          const entry = cursor.result.value as Entry;
          if (!same(cursor.result.key, this.key(entry.spool_record.position.sequence))) {
            transaction.abort();
            return;
          }
          entries.push(entry);
          cursor.result.continue();
        }
      };
      const state = await stateRequest ?? this.initial();
      await done;
      await this.validate(state, entries);
      return { state, entries };
    } finally { database.close(); }
  }

  private async validate(state: State, entries: Entry[]): Promise<void> {
    const initial = this.initial();
    if (!same(Object.keys(state).sort(), Object.keys(initial).sort()) ||
        state.storage_schema_version !== initial.storage_schema_version ||
        state.producer_id !== initial.producer_id || state.stream_id !== initial.stream_id ||
        state.active_generation !== initial.active_generation || state.ack_generation !== initial.ack_generation ||
        state.generation_state !== "ACTIVE" || state.terminal_reserve_bytes_used !== "0") {
      throw new Error("E_SPOOL_STATE");
    }
    let previous = H0;
    let bytes = 0n;
    for (const [index, entry] of entries.entries()) {
      const row = entry.spool_record;
      const raw = entry.sanitized_observation;
      this.validateRaw(raw);
      const config = this.configuration();
      if (raw.context.browser_run_id !== config.browser_run_id || raw.stream_id !== config.stream_id ||
          raw.generation !== config.generation || !uuid.test(raw.discovery_run_id) ||
          raw.sequence !== row.position.sequence || decimal(row.payload_size_bytes) < BigInt(canonicalBytes(raw).byteLength) ||
          decimal(row.payload_size_bytes) > 65536n) throw new Error("E_SPOOL_OBSERVATION_BINDING");
      if (!same(Object.keys(entry).sort(), ["sanitized_observation", "spool_record", "storage_schema_version"]) ||
          entry.storage_schema_version !== "browser-spool-entry/v1" ||
          row.position.sequence !== String(index + 1) || row.previous_cursor_hash !== previous ||
          row.raw_observation_id !== raw.raw_observation_id || row.raw_observation_content_hash !== raw.content_hash ||
          !same(row.position.generation_key, this.generationKey()) ||
          row.cursor_hash !== await this.cursor(raw, previous) ||
          row.content_hash !== await this.hash("SpoolRecord", row) ||
          raw.content_hash !== await this.hash("RawObservation", raw)) {
        throw new Error("E_SPOOL_CHAIN");
      }
      previous = row.cursor_hash;
      bytes += decimal(row.payload_size_bytes);
    }
    const ack = decimal(state.ack_sequence);
    if (decimal(state.next_sequence) !== BigInt(entries.length) + 1n ||
        state.last_cursor_hash !== previous || decimal(state.normal_bytes_used) !== bytes ||
        ack > BigInt(entries.length) ||
        state.ack_cursor_hash !== (ack === 0n ? H0 : entries[Number(ack - 1n)]?.spool_record.cursor_hash)) {
      throw new Error("E_SPOOL_CHAIN");
    }
  }

  private validateRaw(value: unknown): void {
    try { this.configuration().validateRaw(value); }
    catch { throw new Error("E_SPOOL_SCHEMA"); }
  }

  private generationKey(): SpoolRecord["position"]["generation_key"] {
    const { browser_run_id, producer_id, stream_id, generation } = this.configuration();
    return { stream: { browser_run_id, producer_id, stream_id }, generation };
  }

  private hash(kind: string, value: unknown): Promise<string> {
    return canonicalContentHash(kind, value, this.configuration().registry);
  }

  private cursor(raw: Observation, previous: string): Promise<string> {
    const value = this.configuration();
    return this.hash("CursorStep", {
      schema_version: "cursor-step/v1", discovery_run_id: raw.discovery_run_id,
      browser_run_id: value.browser_run_id, producer_id: value.producer_id,
      stream_id: value.stream_id, generation: value.generation, sequence: raw.sequence,
      raw_observation_hash: raw.content_hash, previous_cursor_hash: previous,
    });
  }

  private async write(previous: State, next: State, entry?: Entry): Promise<void> {
    const database = await this.open();
    try {
      const transaction = database.transaction(stores, "readwrite", { durability: "strict" });
      const done = completion(transaction);
      const states = transaction.objectStore(stores[0]);
      const request = states.get(this.key()) as IDBRequest<State | undefined>;
      request.onsuccess = () => {
        if (!same(request.result ?? this.initial(), previous)) {
          transaction.abort();
          return;
        }
        if (entry) transaction.objectStore(stores[1]).add(entry, this.key(entry.spool_record.position.sequence));
        states.put(next, this.key());
      };
      await done;
    } finally { database.close(); }
  }

  async append(value: PersistableSanitizedObservationV1): Promise<SpoolRecord> {
    const input = value as { canonicalSanitizedBytes?: unknown;
      validatedRawObservation?: { canonicalBytes?: unknown } } | undefined;
    if (!(input?.canonicalSanitizedBytes instanceof Uint8Array) ||
        !(input.validatedRawObservation?.canonicalBytes instanceof Uint8Array) ||
        !same(Array.from(input.canonicalSanitizedBytes), Array.from(input.validatedRawObservation.canonicalBytes))) {
      throw new Error("E_SPOOL_UNVALIDATED");
    }
    if (value.canonicalSanitizedBytes.byteLength > 65536) throw new Error("E_SPOOL_SCHEMA");
    const raw = parseStrictJson(value.canonicalSanitizedBytes) as Observation;
    this.validateRaw(raw);
    const config = this.configuration();
    if (raw.context.browser_run_id !== config.browser_run_id || raw.stream_id !== config.stream_id ||
        raw.generation !== config.generation || !uuid.test(raw.discovery_run_id) ||
        decimal(raw.sequence) === 0n || raw.content_hash !== await this.hash("RawObservation", raw)) {
      throw new Error("E_SPOOL_OBSERVATION_BINDING");
    }
    const { state, entries } = await this.snapshot();
    if (decimal(raw.sequence) < decimal(state.next_sequence)) {
      const existing = entries.find(entry => entry.spool_record.position.sequence === raw.sequence);
      if (existing && same(existing.sanitized_observation, raw)) return existing.spool_record;
      throw new Error("E_SPOOL_CONFLICT");
    }
    const size = BigInt(value.canonicalSanitizedBytes.byteLength);
    if (raw.sequence !== state.next_sequence || decimal(state.next_sequence) === maximum) throw new Error("E_SPOOL_SEQUENCE");
    if (decimal(state.normal_bytes_used) + size > (config.normalByteLimit ?? 133169152n)) throw new Error("E_SPOOL_CAPACITY");
    const cursor = await this.cursor(raw, state.last_cursor_hash);
    const record: SpoolRecord = {
      record_type: "SpoolRecord", schema_version: "1", content_hash: "0".repeat(64),
      guarantee: "EFFECTIVELY_ONCE_AFTER_DURABLE_LOCAL_SPOOL_COMMIT",
      spool_record_id: `SPOOL:${cursor}`, position: { generation_key: this.generationKey(), sequence: raw.sequence },
      raw_observation_id: raw.raw_observation_id, raw_observation_content_hash: raw.content_hash,
      previous_cursor_hash: state.last_cursor_hash, cursor_hash: cursor,
      cursor_hash_verification: "VERIFIED_HD_CURSOR_STEP_V1", spool_state: "DURABLY_SPOOLED",
      committed_at: new Date().toISOString(), payload_size_bytes: String(size), individual_deletion_eligible: false,
    };
    const hashed = { ...record, content_hash: await this.hash("SpoolRecord", record) };
    try {
      await this.write(state, { ...state, next_sequence: String(decimal(state.next_sequence) + 1n),
        last_cursor_hash: cursor, normal_bytes_used: String(decimal(state.normal_bytes_used) + size) },
      { storage_schema_version: "browser-spool-entry/v1", spool_record: hashed, sanitized_observation: raw });
    } catch (error) {
      // A concurrent identical append can commit between the snapshot and write.
      const current = await this.snapshot();
      const duplicate = current.entries.find(entry => entry.spool_record.position.sequence === raw.sequence);
      if (duplicate && same(duplicate.sanitized_observation, raw)) return duplicate.spool_record;
      throw error;
    }
    return hashed;
  }

  async enumeratePending(): Promise<readonly SpoolRecord[]> {
    const { state, entries } = await this.snapshot();
    return entries.filter(entry => decimal(entry.spool_record.position.sequence) > decimal(state.ack_sequence))
      .map(entry => entry.spool_record);
  }

  async readPendingObservations(limit: number): Promise<readonly Readonly<{
    record: SpoolRecord; canonicalSanitizedBytes: Uint8Array;
  }>[]> {
    if (!Number.isInteger(limit) || limit < 1 || limit > 32) throw new Error("E_SPOOL_LIMIT");
    const {state, entries} = await this.snapshot();
    return entries.filter(entry => decimal(entry.spool_record.position.sequence) > decimal(state.ack_sequence))
      .slice(0, limit).map(entry => ({record: structuredClone(entry.spool_record),
        canonicalSanitizedBytes: canonicalBytes(entry.sanitized_observation)}));
  }

  async exportRetainedObservations(): Promise<readonly Uint8Array[]> {
    const {entries} = await this.snapshot();
    return entries.map(entry => canonicalBytes(entry.sanitized_observation));
  }

  async readVerifiedStreamState(): Promise<Readonly<{
    generation: string; nextSequence: string; ackSequence: string; ackCursorHash: string; pendingCount: number;
  }>> {
    const {state, entries} = await this.snapshot();
    return Object.freeze({generation: state.active_generation, nextSequence: state.next_sequence,
      ackSequence: state.ack_sequence, ackCursorHash: state.ack_cursor_hash,
      pendingCount: entries.length - Number(decimal(state.ack_sequence))});
  }

  async persistVerifiedAck(generation: string, sequence: string, cursorHash: string): Promise<void> {
    const { state, entries } = await this.snapshot();
    const number = decimal(sequence);
    if (generation !== state.active_generation || number < decimal(state.ack_sequence) ||
        number > BigInt(entries.length) ||
        cursorHash !== (number === 0n ? H0 : entries[Number(number - 1n)]?.spool_record.cursor_hash)) {
      throw new Error("E_SPOOL_ACK");
    }
    await this.write(state, { ...state, ack_sequence: sequence, ack_cursor_hash: cursorHash });
  }
}
