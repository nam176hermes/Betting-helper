import canonicalize from "canonicalize";
import { canonicalContentHash, parseStrictJson } from "../canonical.js";
const checkPlain = (value, seen = new Set(), depth = 0) => {
    if (depth > 32 || seen.size > 65536)
        throw new Error("E_OFFLINE_JSON");
    if (value === null || typeof value === "string" || typeof value === "boolean" ||
        (typeof value === "number" && Number.isFinite(value)))
        return;
    if (typeof value !== "object" || seen.has(value))
        throw new Error("E_OFFLINE_JSON");
    if (Object.getPrototypeOf(value) !== (Array.isArray(value) ? Array.prototype : Object.prototype)) {
        throw new Error("E_OFFLINE_JSON");
    }
    seen.add(value);
    for (const key of Reflect.ownKeys(value)) {
        if (typeof key !== "string" || (Array.isArray(value) && key !== "length" && !/^(0|[1-9][0-9]*)$/.test(key))) {
            throw new Error("E_OFFLINE_JSON");
        }
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor || !("value" in descriptor) || (!descriptor.enumerable && !(Array.isArray(value) && key === "length")))
            throw new Error("E_OFFLINE_JSON");
        checkPlain(descriptor.value, seen, depth + 1);
    }
};
export const projectBeforePersistence = async (input, context) => {
    if (input instanceof Uint8Array && input.byteLength > 65536)
        throw new Error("E_OFFLINE_INPUT_SIZE");
    let value;
    try {
        value = input instanceof Uint8Array ? parseStrictJson(input) : input;
        checkPlain(value);
        // Reuse strict Unicode validation for locally parsed plain-data convenience calls.
        if (!(input instanceof Uint8Array))
            value = parseStrictJson(new TextEncoder().encode(JSON.stringify(value)));
    }
    catch {
        throw new Error("E_OFFLINE_JSON");
    }
    if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 65536)
        throw new Error("E_OFFLINE_INPUT_SIZE");
    try {
        context.validateRaw(value);
    }
    catch {
        throw new Error("E_OFFLINE_SCHEMA");
    }
    const raw = value;
    const binding = context;
    if (binding.sourceKind !== "SYNTHETIC_TEST" || binding.allowedKinds.length !== 1 ||
        binding.allowedKinds[0] !== "TERMINAL" || raw.observation_kind !== "TERMINAL" ||
        raw.context.context_kind !== "RUN_BOUND_NOT_DOCUMENT" || raw.discovery_run_id !== context.runId ||
        raw.context.browser_run_id !== context.browserRunId || raw.stream_id !== context.streamId ||
        raw.generation !== context.generation)
        throw new Error("E_OFFLINE_SOURCE_BINDING");
    let hash;
    try {
        hash = await canonicalContentHash("RawObservation", value, context.canonicalRegistry);
    }
    catch {
        throw new Error("E_OFFLINE_CONTENT_HASH");
    }
    if (hash !== raw.content_hash)
        throw new Error("E_OFFLINE_CONTENT_HASH");
    const bytes = new TextEncoder().encode(canonicalize(value));
    if (bytes.byteLength > 65536)
        throw new Error("E_OFFLINE_INPUT_SIZE");
    return { canonicalSanitizedBytes: bytes, validatedRawObservation: { canonicalBytes: bytes.slice() } };
};
