import type { AnySchemaObject } from "ajv/dist/2020.js";
import type { CanonicalRegistry } from "../canonical.js";
import { validateArtifact } from "../schema-registry.js";
import type { ProjectionContext } from "../security/redaction.js";

export type OfflineRunContext = Readonly<{
  schema_version: "offline-run-context/v1"; source_kind: "SYNTHETIC_TEST";
  run_id: string; browser_run_id: string; producer_id: string; stream_id: string; generation: string;
  backend_url: "ws://127.0.0.1:8765/offline"; allowed_extension_origin: string;
  max_duration_seconds: 600; max_frame_bytes: 262144; max_raw_bytes: 65536; max_batch_records: 32;
  normal_spool_limit_bytes: string; code_sha256: string; vendor_sha256: string;
  schema_lock_sha256: string; scenario_sha256: string;
  live_authority: false; provider_authority: false; money_authority: false;
}>;

export const validateOfflineContext = (value: unknown, schemas: readonly AnySchemaObject[]): OfflineRunContext => {
  try {
    validateArtifact(value, "urn:betting-helper:offline-slice:context:v1", schemas);
    const context = value as OfflineRunContext;
    const limit = BigInt(context.normal_spool_limit_bytes);
    if (limit < 1024n || limit > 133169152n || BigInt(context.generation) > 9223372036854775807n) throw new Error();
    return Object.freeze({...context});
  } catch { throw new Error("E_OFFLINE_SOURCE_BINDING"); }
};

export const projectionContext = (context: OfflineRunContext, schemas: readonly AnySchemaObject[],
  canonicalRegistry: CanonicalRegistry): ProjectionContext => ({
  sourceKind: context.source_kind, runId: context.run_id, browserRunId: context.browser_run_id,
  streamId: context.stream_id, generation: context.generation, allowedKinds: ["TERMINAL"],
  canonicalRegistry, validateRaw: (value: unknown): void => {
    validateArtifact(value, "urn:hybrid-discovery:v6.2:raw-observation:v1", schemas);
  },
});
