/** Test-only owned Worker; never receives an expected state. */
import { Spool } from "../src/spool.js";
// The registered legacy Node executor remains unqualified for browser evidence.
export const contractNotImplemented = () => {
    throw new Error("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04");
};
if (typeof location === "undefined")
    contractNotImplemented();
const reply = (value) => { globalThis.postMessage(value); };
const workerId = new URL(location.href).searchParams.get("worker_id");
const moduleUrl = new URL("../src/spool.js", import.meta.url).href;
const envelope = (raw) => {
    // Python-schema-validated synthetic fixtures only; no production projector claim.
    const bytes = new TextEncoder().encode(raw);
    return { canonicalSanitizedBytes: bytes, validatedRawObservation: { canonicalBytes: bytes } };
};
const actualRows = async (request) => {
    const database = await new Promise((resolve, reject) => {
        const open = indexedDB.open(`hybrid-discovery-v6.2-working-${request.options.browser_run_id}`, 1);
        open.onupgradeneeded = () => { open.transaction?.abort(); };
        open.onsuccess = () => { resolve(open.result); };
        open.onerror = () => { reject(open.error ?? new Error("E_TEST_DATABASE_OPEN")); };
    });
    try {
        if (request.mutation) {
            await new Promise((resolve, reject) => {
                const transaction = database.transaction(["stream_state_v1", "spool_entries_v1"], "readwrite", { durability: "strict" });
                const key = [request.options.producer_id, request.options.stream_id];
                if (request.mutation === "delete-row") {
                    transaction.objectStore("spool_entries_v1").delete([...key, "0".repeat(19), "1".padStart(19, "0")]);
                }
                else {
                    const states = transaction.objectStore("stream_state_v1");
                    const get = states.get(key);
                    get.onsuccess = () => { states.put({ ...get.result, ack_sequence: "1", ack_cursor_hash: "f".repeat(64) }, key); };
                }
                transaction.oncomplete = () => { resolve(); };
                transaction.onabort = () => { reject(transaction.error ?? new Error("E_TEST_MUTATION_ABORT")); };
            });
        }
        return await new Promise((resolve, reject) => {
            const transaction = database.transaction(["stream_state_v1", "spool_entries_v1"], "readonly");
            const states = transaction.objectStore("stream_state_v1").getAll();
            const entries = transaction.objectStore("spool_entries_v1").getAll();
            const keys = transaction.objectStore("spool_entries_v1").getAllKeys();
            transaction.oncomplete = () => { resolve({ states: states.result, entries: entries.result, keys: keys.result }); };
            transaction.onabort = () => { reject(transaction.error ?? new Error("E_TEST_READ_ABORT")); };
        });
    }
    finally {
        database.close();
    }
};
globalThis.onmessage = (event) => {
    const request = event.data;
    void (async () => {
        const bytes = await (await fetch(moduleUrl)).arrayBuffer();
        const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
        const evidence = { ...request.identity, worker_id: workerId, module_url: moduleUrl,
            module_sha256: Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join(""),
            origin: location.origin, protocol: location.protocol };
        const spool = new Spool(request.options);
        if (request.operation === "initialize") {
            await spool.enumeratePending();
            reply({ ...evidence, ...await actualRows(request) });
            return;
        }
        if (request.operation.startsWith("destruction-")) {
            // Only the disposable test Worker exposes whole-database deletion.
            if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(request.options.browser_run_id))
                throw new Error("E_DESTRUCTION_RUN_ID");
            const name = `hybrid-discovery-v6.2-working-${request.options.browser_run_id}`;
            if (request.operation === "destruction-prepare") {
                const raw = request.observations[0];
                const ack = request.final_ack;
                if (!raw || !ack)
                    throw new Error("E_DESTRUCTION_PREPARE");
                await spool.append(envelope(raw));
                await spool.persistVerifiedAck(ack.generation, ack.sequence, ack.cursor_hash);
            }
            if (request.operation === "destruction-delete") {
                await new Promise((resolve, reject) => {
                    const deletion = indexedDB.deleteDatabase(name);
                    deletion.onsuccess = () => { resolve(); };
                    deletion.onerror = () => { reject(deletion.error ?? new Error("E_DESTRUCTION_IDB_DELETE")); };
                    deletion.onblocked = () => { reject(new Error("E_DESTRUCTION_WRITER_PRESENT")); };
                });
            }
            const names = (await indexedDB.databases()).map(database => database.name).sort();
            const present = names.includes(name);
            reply({ ...evidence, database_name: name, present, database_names: names,
                ...(present ? await actualRows(request) : { states: [], entries: [], keys: [] }) });
            return;
        }
        if (request.operation === "read") {
            reply({ ...evidence, ...await actualRows(request) });
            return;
        }
        if (request.operation === "deliver" || request.operation === "recover") {
            const transport = request.transport;
            if (!transport || !/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(transport.endpoint))
                throw new Error("E_TEST_LOOPBACK");
            const post = async (path, value) => {
                const response = await fetch(transport.endpoint + path, { method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token: transport.token, value }) });
                if (!response.ok)
                    throw new Error(`E_TEST_LOOPBACK_STATUS:${String(response.status)}`);
                return await response.json();
            };
            const boundary = request.operation === "recover" ? "" : request.identity.checkpoint_id;
            await spool.enumeratePending();
            const rawRows = await actualRows(request);
            if (request.operation === "deliver") {
                const raw = request.observations[0];
                if (raw === undefined)
                    throw new Error("E_TEST_INPUT");
                await spool.append(envelope(raw));
            }
            else if (rawRows.entries.length === 0) {
                const raw = request.observations[0];
                if (raw === undefined)
                    throw new Error("E_TEST_REOBSERVATION_REQUIRED");
                await spool.append(envelope(raw));
            }
            const rows = await actualRows(request);
            const raw = rows.entries[0]?.sanitized_observation;
            if (!raw)
                throw new Error("E_TEST_REPLAY_ROW");
            let wireAck;
            const pause = () => {
                reply({ ...evidence, boundary, wire_ack: wireAck });
                for (;;) { /* owner terminates this exact Worker before transaction completion */ }
            };
            const deliver = async () => {
                const received = await post("/ingest", raw);
                const ack = received.ack;
                if (!ack || ack.run_id !== request.options.browser_run_id ||
                    ack.browser_run_id !== request.options.browser_run_id ||
                    ack.producer_id !== request.options.producer_id || ack.stream_id !== request.options.stream_id ||
                    ack.generation !== Number(request.options.generation) || ack.cursor_hash_verified !== 1)
                    throw new Error("E_TEST_ACK_BINDING");
                wireAck = ack;
                if (boundary === "ack_01_before_extension_ack_transaction")
                    pause();
                if (boundary === "ack_02_during_extension_ack_transaction") {
                    // eslint-disable-next-line @typescript-eslint/unbound-method -- native receiver preserved.
                    const put = IDBObjectStore.prototype.put;
                    IDBObjectStore.prototype.put = function (...args) {
                        const result = put.apply(this, args);
                        result.addEventListener("success", pause);
                        return result;
                    };
                }
                await spool.persistVerifiedAck(String(ack.generation), String(ack.highest_contiguous_sequence), String(ack.cursor_hash));
                if (boundary === "ack_03_after_extension_ack_transaction")
                    pause();
                await post("/confirm", ack);
                return ack;
            };
            const ack = await deliver();
            if (boundary === "ack_06_duplicate_identical") {
                const duplicate = await deliver();
                if (JSON.stringify(ack) !== JSON.stringify(duplicate))
                    throw new Error("E_TEST_DUPLICATE_ACK");
            }
            reply({ ...evidence, boundary, wire_ack: ack, ...await actualRows(request) });
            return;
        }
        const first = request.observations[0];
        if (first === undefined)
            throw new Error("E_TEST_INPUT");
        if (request.operation === "exercise") {
            const [one, duplicate] = await Promise.all([
                spool.append(envelope(first)), spool.append(envelope(first)),
            ]);
            const second = request.observations[1];
            const third = request.observations[2];
            if (second === undefined || third === undefined)
                throw new Error("E_TEST_INPUT");
            const two = await spool.append(envelope(second));
            let invalidAck = "";
            try {
                await spool.persistVerifiedAck("0", "2", "f".repeat(64));
            }
            catch (error) {
                invalidAck = String(error);
            }
            await spool.persistVerifiedAck("0", "1", one.cursor_hash);
            // eslint-disable-next-line @typescript-eslint/unbound-method -- applied to the intercepted receiver below.
            const put = IDBObjectStore.prototype.put;
            IDBObjectStore.prototype.put = function (...args) {
                const result = put.apply(this, args);
                this.transaction.abort();
                return result;
            };
            let aborted = false;
            try {
                await spool.append(envelope(third));
            }
            catch {
                aborted = true;
            }
            IDBObjectStore.prototype.put = put;
            reply({ ...evidence, ...await actualRows(request), duplicate,
                first: one, second: two, invalid_ack: invalidAck, aborted,
                pending: await spool.enumeratePending() });
            return;
        }
        const pause = () => {
            reply({ ...evidence, boundary: request.identity.checkpoint_id });
            // The owned Worker blocks inside the IDB callback until Worker.terminate().
            for (;;) { /* transaction cannot complete before termination */ }
        };
        const boundary = request.identity.checkpoint_id;
        if (boundary === "idb_01_before_transaction") {
            // eslint-disable-next-line @typescript-eslint/unbound-method -- applied to the intercepted receiver below.
            const transaction = IDBDatabase.prototype.transaction;
            IDBDatabase.prototype.transaction = function (...args) {
                if (args[1] === "readwrite")
                    pause();
                return transaction.apply(this, args);
            };
        }
        else if (boundary === "idb_02_during_sequence_allocation" || boundary === "idb_03_during_row_put") {
            // eslint-disable-next-line @typescript-eslint/unbound-method -- applied to the intercepted receiver below.
            const add = IDBObjectStore.prototype.add;
            IDBObjectStore.prototype.add = function (...args) {
                if (boundary === "idb_02_during_sequence_allocation")
                    pause();
                const result = add.apply(this, args);
                result.addEventListener("success", pause);
                return result;
            };
        }
        else if (boundary !== "idb_04_after_commit")
            throw new Error("E_TEST_CHECKPOINT");
        await spool.append(envelope(first));
        pause();
    })().catch((error) => { reply({ error: String(error), worker_id: workerId }); });
};
