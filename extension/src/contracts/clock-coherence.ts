import type { AnySchemaObject } from "ajv";
import { validateArtifact } from "../schema-registry.js";

type Evaluation = {
  accepted: boolean;
  error: string;
  state: string;
  predecessor_state?: "CLOSED_FOREVER";
  successor_distinct?: true;
};

export type ReleaseInput = Record<string, unknown> & {
  controller_state: string;
  predecessor_epoch_id: string;
  candidate_epoch_id: string | null;
};

const transitions: Readonly<Record<string, string>> = {
  "OPEN|SHOCK_ATOMIC_CLOSE": "SHOCKED_CLOSED",
  "NEW_EPOCH_OPEN|SHOCK_ATOMIC_CLOSE": "SHOCKED_CLOSED",
  "SHOCKED_CLOSED|CLOSE_RECORDED": "WAITING_FOR_RESNAPSHOT",
  "WAITING_FOR_RESNAPSHOT|RESNAPSHOT_CANDIDATE_ACCEPTED": "NEW_EPOCH_PENDING",
  "NEW_EPOCH_PENDING|RELEASE_PREDICATE_SATISFIED": "NEW_EPOCH_OPEN",
  "NEW_EPOCH_PENDING|NEW_SHOCK_CLOSED_CANDIDATE": "WAITING_FOR_RESNAPSHOT",
};

const rejected = (error: string, state: string): Evaluation => ({ accepted: false, error, state });

export const validateCoherenceArtifact = (
  artifact: unknown,
  schemas: readonly AnySchemaObject[],
): boolean => {
  try {
    validateArtifact(artifact, "https://hybrid-discovery.local/schemas/v6.2/clock-coherence-records.schema.json", schemas);
    return true;
  } catch {
    return false;
  }
};

export const transitionCoherence = (state: string, reason: string): string => {
  const next = transitions[`${state}|${reason}`];
  if (next === undefined) throw new Error("E_INVALID_COHERENCE_TRANSITION");
  return next;
};

export const acceptCandidate = (value: Record<string, unknown>): Evaluation => {
  const accepted = value.controller_state === "WAITING_FOR_RESNAPSHOT" &&
    value.proof_status === "OBSERVED" && value.proof_verified === true &&
    value.release_predicate === "SATISFIED" && value.predecessor_permanently_closed === true &&
    value.candidate_distinct_from_predecessor === true &&
    value.freshness_binding_verified === true && value.shock_binding_verified === true &&
    value.mapping_bindings_verified === true && value.continuity_bindings_verified === true;
  return accepted
    ? { accepted: true, error: "ACCEPT", state: "NEW_EPOCH_PENDING" }
    : rejected("E_RESNAPSHOT_CANDIDATE_BINDING", "WAITING_FOR_RESNAPSHOT");
};

export const evaluateRelease = (value: ReleaseInput): Evaluation => {
  if (value.predecessor_reopen_requested === true) return rejected("E_PREDECESSOR_EPOCH_IMMUTABLE", "CLOSED_FOREVER");
  if (value.candidate_created !== true || !value.candidate_epoch_id) return rejected("E_RELEASE_BINDING", "NEW_EPOCH_PENDING");
  if (value.candidate_epoch_id === value.predecessor_epoch_id) return rejected("E_INVALID_COHERENCE_TRANSITION", "NEW_EPOCH_PENDING");
  if (value.predecessor_permanently_closed !== true) return rejected("E_NON_GENESIS_PREDECESSOR_NOT_CLOSED", "WAITING_FOR_RESNAPSHOT");
  if (value.predecessor_closed !== true) return rejected("E_PREDECESSOR_NOT_CLOSED", "WAITING_FOR_RESNAPSHOT");
  if (value.signed_accepted_capability_evidence !== true) return rejected("E_CAPABILITY_EVIDENCE_NOT_ACCEPTED", "WAITING_FOR_RESNAPSHOT");
  if (value.proof_status === "NOT_OBSERVED") return rejected("E_RESNAPSHOT_NOT_OBSERVED", "WAITING_FOR_RESNAPSHOT");
  if (value.proof_status !== "OBSERVED" || value.proof_verified !== true) return rejected("E_RESNAPSHOT_UNKNOWN", "WAITING_FOR_RESNAPSHOT");
  if (value.snapshot_semantics !== "FULL_AUTHORITATIVE_SNAPSHOT") return rejected("E_RESNAPSHOT_NOT_OBSERVED", "WAITING_FOR_RESNAPSHOT");
  const checks: readonly [boolean, string][] = [
    [value.football_state === "FRESH", "E_FOOTBALL_STATE_NOT_FRESH"],
    [value.operator_state === "FRESH", "E_OPERATOR_STATE_NOT_FRESH"],
    [value.market_book === "FRESH_COMPLETE_OPEN", "E_MARKET_BOOK_NOT_COMPLETE_OPEN"],
    [value.conservative_lower_bounds_strictly_after_shock_upper === true, "E_NOT_STRICTLY_POST_SHOCK"],
    [value.proof_bound_mappings_open_unclosed_valid_at_release === true, "E_MAPPING_CLOSED"],
    [value.mappings_valid === true, "E_MAPPING_CLOSED"],
    [value.identities_orientation_generations_agree === true, "E_IDENTITY_OR_GENERATION_MISMATCH"],
    [value.cursor_ranges_contiguous === true, "E_CURSOR_NOT_CONTIGUOUS"],
  ];
  for (const [passed, error] of checks) if (!passed) return rejected(error, "NEW_EPOCH_PENDING");
  if (value.gap_conflict_schema_lifecycle_mapping_or_later_shock_absent !== true) {
    return value.blocker === "LATER_OR_INTERSECTING_SHOCK"
      ? rejected("E_CANDIDATE_CLOSED_BY_NEW_SHOCK", "WAITING_FOR_RESNAPSHOT")
      : rejected("E_RELEASE_BLOCKED", "NEW_EPOCH_PENDING");
  }
  if (value.score_period_suspension_and_shock_fields_agree !== true) return rejected("E_STATE_FIELDS_DISAGREE", "NEW_EPOCH_PENDING");
  if (value.freshness_bindings_valid_at_release !== true ||
      value.continuity_bindings_valid_at_release !== true || value.proof_bindings_valid !== true) {
    return rejected("E_RELEASE_BINDING", "NEW_EPOCH_PENDING");
  }
  return { accepted: true, error: "ACCEPT", state: "NEW_EPOCH_OPEN", predecessor_state: "CLOSED_FOREVER", successor_distinct: true };
};
