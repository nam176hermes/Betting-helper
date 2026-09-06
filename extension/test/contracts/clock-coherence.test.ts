import { strict as assert } from "node:assert";
import test from "node:test";
import {
  closeClockMapping,
  reopenClockMapping,
  selectClockMapping,
} from "../../src/contracts/clock-vectors.js";
import {
  acceptCandidate,
  evaluateRelease,
  transitionCoherence,
  type ReleaseInput,
} from "../../src/contracts/clock-coherence.js";

const releaseInput = (): ReleaseInput => ({
  controller_state: "NEW_EPOCH_PENDING",
  predecessor_epoch_id: "EPOCH:predecessor",
  candidate_epoch_id: "EPOCH:candidate",
  predecessor_closed: true,
  proof_status: "OBSERVED",
  proof_verified: true,
  signed_accepted_capability_evidence: true,
  snapshot_semantics: "FULL_AUTHORITATIVE_SNAPSHOT",
  football_state: "FRESH",
  operator_state: "FRESH",
  market_book: "FRESH_COMPLETE_OPEN",
  conservative_lower_bounds_strictly_after_shock_upper: true,
  mappings_valid: true,
  identities_orientation_generations_agree: true,
  cursor_ranges_contiguous: true,
  gap_conflict_schema_lifecycle_mapping_or_later_shock_absent: true,
  score_period_suspension_and_shock_fields_agree: true,
  proof_bound_mappings_open_unclosed_valid_at_release: true,
  freshness_bindings_valid_at_release: true,
  continuity_bindings_valid_at_release: true,
  candidate_created: true,
  candidate_distinct_from_predecessor: true,
  predecessor_permanently_closed: true,
  proof_bindings_valid: true,
});

void test("closed mappings retain history and cannot reopen or be selected", () => {
  const mappingId = `MAP:${"c".repeat(64)}`;
  const history = closeClockMapping(mappingId, "SLEEP_RESUME");
  assert.deepEqual(history, [{
    mapping_id: mappingId,
    reason: "SLEEP_RESUME",
    permanent: true,
    reopen_permitted: false,
  }]);
  assert.throws(() => reopenClockMapping(mappingId, history), {
    message: "E_MAPPING_PERMANENTLY_CLOSED",
  });
  assert.throws(
    () => selectClockMapping([{ mapping_id: mappingId, width_us: 1, valid_from_us: 1 }], history),
    { message: "E_NO_VALID_MAPPING" },
  );
});

void test("coherence follows the governed state path and rolls pending back on shock", () => {
  let state = "OPEN";
  for (const [reason, expected] of [
    ["SHOCK_ATOMIC_CLOSE", "SHOCKED_CLOSED"],
    ["CLOSE_RECORDED", "WAITING_FOR_RESNAPSHOT"],
    ["RESNAPSHOT_CANDIDATE_ACCEPTED", "NEW_EPOCH_PENDING"],
    ["RELEASE_PREDICATE_SATISFIED", "NEW_EPOCH_OPEN"],
  ] as const) {
    state = transitionCoherence(state, reason);
    assert.equal(state, expected);
  }
  assert.equal(transitionCoherence("NEW_EPOCH_PENDING", "NEW_SHOCK_CLOSED_CANDIDATE"), "WAITING_FOR_RESNAPSHOT");
});

void test("candidate and release gates fail closed", () => {
  assert.deepEqual(acceptCandidate({
    controller_state: "WAITING_FOR_RESNAPSHOT", proof_status: "UNKNOWN",
    proof_verified: false, release_predicate: "NOT_SATISFIED",
    predecessor_permanently_closed: true, candidate_distinct_from_predecessor: true,
    freshness_binding_verified: false, shock_binding_verified: false,
    mapping_bindings_verified: false, continuity_bindings_verified: false,
  }), { accepted: false, error: "E_RESNAPSHOT_CANDIDATE_BINDING", state: "WAITING_FOR_RESNAPSHOT" });
  assert.deepEqual(evaluateRelease(releaseInput()), {
    accepted: true, error: "ACCEPT", state: "NEW_EPOCH_OPEN",
    predecessor_state: "CLOSED_FOREVER", successor_distinct: true,
  });
  assert.deepEqual(evaluateRelease({ ...releaseInput(), proof_bindings_valid: false }), {
    accepted: false, error: "E_RELEASE_BINDING", state: "NEW_EPOCH_PENDING",
  });
});
