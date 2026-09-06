import { ContractNotImplementedError } from "./errors.js";
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

export class Spool {
  append(value: PersistableSanitizedObservationV1): Promise<SpoolRecord> {
    Object.is(value, value);
    throw new ContractNotImplementedError("F0A-T03");
  }
}
