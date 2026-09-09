/** Closed live records. Compose with the pinned local standalone schema validator. */
import { canonicalBytes } from "../canonical.js";

export type LiveRecordKind = "ProviderState" | "MarketBook" | "FixtureBinding" |
  "BindingChange" | "HealthChange" | "LiveEvent";
export type SchemaValidator = (value: unknown, kind: LiveRecordKind) => boolean;
export type Score = { home: number; away: number } | null;
export type Period = "PREGAME" | "H1" | "HALFTIME" | "H2" | "FINISHED" |
  "BLOCKED" | "OUT_OF_SCOPE" | "UNKNOWN";
export type Selection = { selection_id: string; decimal_odds: string };
export type MarketBook = {
  binding_id: string; binding_revision: string; operator_fixture_id: string;
  market_id: string; horizon: "H1" | "H2" | "FT";
  settlement_basis: "NORMAL_TIME_INCLUDING_STOPPAGE" | "UNSUPPORTED";
  selections: { HOME: Selection; DRAW: Selection; AWAY: Selection };
  market_status: "OPEN" | "SUSPENDED" | "CLOSED" | "UNKNOWN";
  capture_revision: string; native_revision: string | null; observed_at_utc: string;
  browser_mono_us: string; clock_domain_id: string; source_updated_at: string | null;
  operator_score: Score; operator_period: Period | null;
  capture_evidence_tier: "DISPLAY_COHERENT" | "UNVERIFIED";
  profile_hash: string; document_epoch: string; quality_flags: string[];
};
export type LiveEvent = {
  protocol: "BH_LIVE_READONLY_V1"; run_id: string;
  source_kind: "PROVIDER" | "OPERATOR" | "CONTROL"; stream_id: string;
  generation: string; sequence: string; observation_id: string; observed_at_utc: string;
  received_mono_us: string; previous_hash: string; content_hash: string;
  payload_type: "ProviderState" | "MarketBook" | "BindingChange" | "HealthChange";
  payload: Record<string, unknown>;
};
const counters = new Set(["received_mono_us", "content_revision", "binding_revision",
  "capture_revision", "browser_mono_us", "revision", "before_revision", "epoch",
  "generation", "sequence", "counter", "first_sequence", "last_sequence", "monotonic_us"]);
function scalars(value: unknown, key = ""): void {
  if (typeof value === "string") {
    if (Array.from(value).some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127) ||
        (counters.has(key) && BigInt(value) > 9223372036854775807n)) throw new Error();
  } else if (Array.isArray(value)) {
    for (const child of value) scalars(child, key);
  } else if (value !== null && typeof value === "object") {
    for (const [name, child] of Object.entries(value)) scalars(child, name);
  }
}
export function validateLiveRecord(value: unknown, kind: LiveRecordKind,
  validateSchema: SchemaValidator): Record<string, unknown> {
  try {
    if (!validateSchema(value, kind)) throw new Error();
    const record = value as Record<string, unknown>;
    if (canonicalBytes(record).byteLength > 65536) throw new Error();
    scalars(record);
    if (kind === "LiveEvent") validateLiveRecord(record["payload"],
      record["payload_type"] as LiveRecordKind, validateSchema);
    if (kind === "MarketBook") {
      const selections = Object.values((value as MarketBook).selections);
      if (new Set(selections.map(s => s.selection_id)).size !== 3 ||
          selections.some(s => Number(s.decimal_odds) <= 1)) throw new Error();
    }
    if ((kind === "ProviderState" || kind === "FixtureBinding") &&
        record["home_id"] === record["away_id"]) throw new Error();
    if (kind === "ProviderState" && record["provider_updated_at"] !== null) throw new Error();
    return structuredClone(record);
  } catch { throw new Error("E_LIVE_RECORD"); }
}
