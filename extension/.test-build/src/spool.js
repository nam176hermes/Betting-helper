import { canonicalBytes, canonicalContentHash, parseStrictJson } from "./canonical.js";
const H0 = "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c";
const stores = ["stream_state_v1", "spool_entries_v1"];
const maximum = 9223372036854775807n;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const decimal = (value) => {
    if (!/^(0|[1-9][0-9]*)$/.test(value) || BigInt(value) > maximum) {
        throw new Error("E_SPOOL_INTEGER");
    }
    return BigInt(value);
};
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const identicalEntry = (left, right) => {
    if (left === right)
        return true;
    if (left === null || right === null || typeof left !== "object" || typeof right !== "object")
        return false;
    const prototype = Object.getPrototypeOf(left);
    if ((prototype !== Object.prototype && prototype !== Array.prototype) || Object.getPrototypeOf(right) !== prototype)
        return false;
    if (Array.isArray(left) && Array.isArray(right) && left.length !== right.length)
        return false;
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) &&
        identicalEntry(left[key], right[key]));
};
const requestValue = (request) => new Promise((resolve, reject) => {
    request.onsuccess = () => { resolve(request.result); };
    request.onerror = () => { reject(request.error ?? new Error("E_SPOOL_REQUEST")); };
});
const completion = (transaction) => new Promise((resolve, reject) => {
    transaction.oncomplete = () => { resolve(); };
    transaction.onabort = () => { reject(transaction.error ?? new Error("E_SPOOL_ABORT")); };
    transaction.onerror = () => { reject(transaction.error ?? new Error("E_SPOOL_TRANSACTION")); };
});
/** Offline durable sink. Only the still-gated projector may construct its input. */
export class Spool {
    options;
    // Reuse hash proofs only for byte-identical full entries read again from IndexedDB.
    // State, schema, ordering and predecessor bindings are still checked on every snapshot.
    verifiedEntries = new Map();
    verifiedRegistry;
    writes = Promise.resolve();
    constructor(options) {
        this.options = options;
    }
    serializeWrite(work) {
        const result = this.writes.then(work);
        this.writes = result.then(() => undefined, () => undefined);
        return result;
    }
    configuration() {
        const value = this.options;
        if (!value || ![value.browser_run_id, value.producer_id, value.stream_id].every(id => uuid.test(id))) {
            throw new Error("E_SPOOL_BINDING");
        }
        decimal(value.generation);
        if (typeof value.validateRaw !== "function")
            throw new Error("E_SPOOL_BINDING");
        const limit = value.normalByteLimit ?? 133169152n;
        if (typeof limit !== "bigint" || limit < 1024n || limit > 133169152n)
            throw new Error("E_SPOOL_CAPACITY");
        return value;
    }
    initial() {
        const value = this.configuration();
        return {
            storage_schema_version: "browser-stream-state/v1",
            producer_id: value.producer_id, stream_id: value.stream_id,
            active_generation: value.generation, next_sequence: "1", last_cursor_hash: H0,
            ack_generation: value.generation, ack_sequence: "0", ack_cursor_hash: H0,
            normal_bytes_used: "0", terminal_reserve_bytes_used: "0", generation_state: "ACTIVE",
        };
    }
    key(sequence) {
        const value = this.configuration();
        const key = [value.producer_id, value.stream_id];
        return sequence === undefined ? key : [...key, value.generation.padStart(19, "0"), sequence.padStart(19, "0")];
    }
    open() {
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
    async snapshot() {
        // Read every retained row and key in one native batch; preserve full chain verification.
        const database = await this.open();
        try {
            const transaction = database.transaction(stores, "readonly");
            const done = completion(transaction);
            const stateRequest = requestValue(transaction.objectStore(stores[0]).get(this.key()));
            const rows = transaction.objectStore(stores[1]);
            const range = IDBKeyRange.bound(this.key("0"), this.key(String(maximum)), false, false);
            const entriesRequest = requestValue(rows.getAll(range));
            const keysRequest = requestValue(rows.getAllKeys(range));
            const state = await stateRequest ?? this.initial();
            const entries = await entriesRequest, keys = await keysRequest;
            await done;
            if (entries.length !== keys.length || entries.some((entry, index) => !same(keys[index], this.key(entry.spool_record.position.sequence))))
                throw new Error("E_SPOOL_CHAIN");
            await this.validate(state, entries);
            return { state, entries };
        }
        finally {
            database.close();
        }
    }
    async validate(state, entries) {
        const registry = this.configuration().registry;
        if (!identicalEntry(this.verifiedRegistry, registry)) {
            this.verifiedEntries.clear();
            this.verifiedRegistry = structuredClone(registry);
        }
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
                raw.sequence !== row.position.sequence ||
                decimal(row.payload_size_bytes) > 65536n)
                throw new Error("E_SPOOL_OBSERVATION_BINDING");
            if (!same(Object.keys(entry).sort(), ["sanitized_observation", "spool_record", "storage_schema_version"]) ||
                entry.storage_schema_version !== "browser-spool-entry/v1" ||
                row.position.sequence !== String(index + 1) || row.previous_cursor_hash !== previous ||
                row.raw_observation_id !== raw.raw_observation_id || row.raw_observation_content_hash !== raw.content_hash ||
                !same(row.position.generation_key, this.generationKey())) {
                throw new Error("E_SPOOL_CHAIN");
            }
            if (!identicalEntry(this.verifiedEntries.get(row.position.sequence), entry)) {
                if (decimal(row.payload_size_bytes) < BigInt(canonicalBytes(raw).byteLength))
                    throw new Error("E_SPOOL_OBSERVATION_BINDING");
                if (row.cursor_hash !== await this.cursor(raw, previous) ||
                    row.content_hash !== await this.hash("SpoolRecord", row) ||
                    raw.content_hash !== await this.hash("RawObservation", raw))
                    throw new Error("E_SPOOL_CHAIN");
                this.verifiedEntries.set(row.position.sequence, structuredClone(entry));
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
    validateRaw(value) {
        try {
            this.configuration().validateRaw(value);
        }
        catch {
            throw new Error("E_SPOOL_SCHEMA");
        }
    }
    generationKey() {
        const { browser_run_id, producer_id, stream_id, generation } = this.configuration();
        return { stream: { browser_run_id, producer_id, stream_id }, generation };
    }
    hash(kind, value) {
        return canonicalContentHash(kind, value, this.configuration().registry);
    }
    cursor(raw, previous) {
        const value = this.configuration();
        return this.hash("CursorStep", {
            schema_version: "cursor-step/v1", discovery_run_id: raw.discovery_run_id,
            browser_run_id: value.browser_run_id, producer_id: value.producer_id,
            stream_id: value.stream_id, generation: value.generation, sequence: raw.sequence,
            raw_observation_hash: raw.content_hash, previous_cursor_hash: previous,
        });
    }
    async write(previous, next, entry) {
        const database = await this.open();
        try {
            const transaction = database.transaction(stores, "readwrite", { durability: "strict" });
            const done = completion(transaction);
            const states = transaction.objectStore(stores[0]);
            const request = states.get(this.key());
            request.onsuccess = () => {
                if (!same(request.result ?? this.initial(), previous)) {
                    transaction.abort();
                    return;
                }
                if (entry)
                    transaction.objectStore(stores[1]).add(entry, this.key(entry.spool_record.position.sequence));
                states.put(next, this.key());
            };
            await done;
        }
        finally {
            database.close();
        }
    }
    append(value) {
        return this.serializeWrite(() => this.appendRecord(value));
    }
    async appendRecord(value) {
        const input = value;
        if (!(input?.canonicalSanitizedBytes instanceof Uint8Array) ||
            !(input.validatedRawObservation?.canonicalBytes instanceof Uint8Array) ||
            !same(Array.from(input.canonicalSanitizedBytes), Array.from(input.validatedRawObservation.canonicalBytes))) {
            throw new Error("E_SPOOL_UNVALIDATED");
        }
        if (value.canonicalSanitizedBytes.byteLength > 65536)
            throw new Error("E_SPOOL_SCHEMA");
        const raw = parseStrictJson(value.canonicalSanitizedBytes);
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
            if (existing && same(existing.sanitized_observation, raw))
                return existing.spool_record;
            throw new Error("E_SPOOL_CONFLICT");
        }
        const size = BigInt(value.canonicalSanitizedBytes.byteLength);
        if (raw.sequence !== state.next_sequence || decimal(state.next_sequence) === maximum)
            throw new Error("E_SPOOL_SEQUENCE");
        if (decimal(state.normal_bytes_used) + size > (config.normalByteLimit ?? 133169152n))
            throw new Error("E_SPOOL_CAPACITY");
        const cursor = await this.cursor(raw, state.last_cursor_hash);
        const record = {
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
                last_cursor_hash: cursor, normal_bytes_used: String(decimal(state.normal_bytes_used) + size) }, { storage_schema_version: "browser-spool-entry/v1", spool_record: hashed, sanitized_observation: raw });
        }
        catch (error) {
            // A concurrent identical append can commit between the snapshot and write.
            const current = await this.snapshot();
            const duplicate = current.entries.find(entry => entry.spool_record.position.sequence === raw.sequence);
            if (duplicate && same(duplicate.sanitized_observation, raw))
                return duplicate.spool_record;
            throw error;
        }
        return hashed;
    }
    async enumeratePending() {
        const { state, entries } = await this.snapshot();
        return entries.filter(entry => decimal(entry.spool_record.position.sequence) > decimal(state.ack_sequence))
            .map(entry => entry.spool_record);
    }
    async readPendingObservations(limit) {
        if (!Number.isInteger(limit) || limit < 1 || limit > 32)
            throw new Error("E_SPOOL_LIMIT");
        const { state, entries } = await this.snapshot();
        return entries.filter(entry => decimal(entry.spool_record.position.sequence) > decimal(state.ack_sequence))
            .slice(0, limit).map(entry => ({ record: structuredClone(entry.spool_record),
            canonicalSanitizedBytes: canonicalBytes(entry.sanitized_observation) }));
    }
    async exportRetainedObservations() {
        const { entries } = await this.snapshot();
        return entries.map(entry => canonicalBytes(entry.sanitized_observation));
    }
    async readVerifiedStreamState() {
        const { state, entries } = await this.snapshot();
        return Object.freeze({ generation: state.active_generation, nextSequence: state.next_sequence,
            ackSequence: state.ack_sequence, ackCursorHash: state.ack_cursor_hash,
            pendingCount: entries.length - Number(decimal(state.ack_sequence)) });
    }
    persistVerifiedAck(generation, sequence, cursorHash) {
        return this.serializeWrite(() => this.persistAck(generation, sequence, cursorHash));
    }
    async persistAck(generation, sequence, cursorHash) {
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
