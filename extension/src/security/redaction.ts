import canonicalize from "canonicalize";
import { canonicalContentHash, parseStrictJson, type CanonicalRegistry } from "../canonical.js";

declare const persistableSanitizedObservationBrand: unique symbol;
declare const validatedRawObservationBrand: unique symbol;

type ValidatedRawObservationV1 = Readonly<{
  readonly [validatedRawObservationBrand]: "RawObservation";
  readonly canonicalBytes: Uint8Array;
}>;

export type PersistableSanitizedObservationV1 = Readonly<{
  readonly [persistableSanitizedObservationBrand]: never;
  readonly canonicalSanitizedBytes: Uint8Array;
  readonly validatedRawObservation: ValidatedRawObservationV1;
}>;


export type ProjectionContext = Readonly<{
  sourceKind: "SYNTHETIC_TEST"; runId: string; browserRunId: string; streamId: string;
  generation: string; allowedKinds: readonly ["TERMINAL"];
  validateRaw: (value: unknown) => void; canonicalRegistry: CanonicalRegistry;
}>;

const checkPlain = (value: unknown, seen = new Set<object>(), depth = 0): void => {
  if (depth > 32 || seen.size > 65536) throw new Error("E_OFFLINE_JSON");
  if (value === null || typeof value === "string" || typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))) return;
  if (typeof value !== "object" || seen.has(value)) throw new Error("E_OFFLINE_JSON");
  if (Object.getPrototypeOf(value) !== (Array.isArray(value) ? Array.prototype : Object.prototype)) {
    throw new Error("E_OFFLINE_JSON");
  }
  seen.add(value);
  for (const key of Reflect.ownKeys(value)) {
    if (typeof key !== "string" || (Array.isArray(value) && key !== "length" && !/^(0|[1-9][0-9]*)$/.test(key))) {
      throw new Error("E_OFFLINE_JSON");
    }
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !("value" in descriptor) || (!descriptor.enumerable && !(Array.isArray(value) && key === "length"))) throw new Error("E_OFFLINE_JSON");
    checkPlain(descriptor.value as unknown, seen, depth + 1);
  }
};

export const projectBeforePersistence = async (
  input: unknown, context: ProjectionContext,
): Promise<PersistableSanitizedObservationV1> => {
  if (input instanceof Uint8Array && input.byteLength > 65536) throw new Error("E_OFFLINE_INPUT_SIZE");
  let value: unknown;
  try {
    value = input instanceof Uint8Array ? parseStrictJson(input) : input;
    checkPlain(value);
    // Reuse strict Unicode validation for locally parsed plain-data convenience calls.
    if (!(input instanceof Uint8Array)) value = parseStrictJson(new TextEncoder().encode(JSON.stringify(value)));
  } catch { throw new Error("E_OFFLINE_JSON"); }
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 65536) throw new Error("E_OFFLINE_INPUT_SIZE");
  try { context.validateRaw(value); } catch { throw new Error("E_OFFLINE_SCHEMA"); }
  const raw = value as { discovery_run_id: string; stream_id: string; generation: string;
    context: {browser_run_id: string; context_kind: string}; observation_kind: string; content_hash: string; };
  const binding = context as {sourceKind: string; allowedKinds: readonly string[]};
  if (binding.sourceKind !== "SYNTHETIC_TEST" || binding.allowedKinds.length !== 1 ||
      binding.allowedKinds[0] !== "TERMINAL" || raw.observation_kind !== "TERMINAL" ||
      raw.context.context_kind !== "RUN_BOUND_NOT_DOCUMENT" || raw.discovery_run_id !== context.runId ||
      raw.context.browser_run_id !== context.browserRunId || raw.stream_id !== context.streamId ||
      raw.generation !== context.generation) throw new Error("E_OFFLINE_SOURCE_BINDING");
  let hash: string;
  try { hash = await canonicalContentHash("RawObservation", value, context.canonicalRegistry); }
  catch { throw new Error("E_OFFLINE_CONTENT_HASH"); }
  if (hash !== raw.content_hash) throw new Error("E_OFFLINE_CONTENT_HASH");
  const bytes = new TextEncoder().encode(canonicalize(value));
  if (bytes.byteLength > 65536) throw new Error("E_OFFLINE_INPUT_SIZE");
  return { canonicalSanitizedBytes: bytes, validatedRawObservation: {canonicalBytes: bytes.slice()} } as PersistableSanitizedObservationV1;
};
