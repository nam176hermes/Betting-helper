# Repair evidence status

BH-R08 is an offline evidence-gate repair. It grants no production, live,
provider, monetary or discovery authority. Security review is NOT_REVIEWED.

## Gate contract

`tools/verify_repair_evidence.py::aggregate_repair_evidence(required_ids, results)`
accepts the exact planned ID list and terminal case rows. Duplicate, missing,
extra, empty or contradictory identities fail. PASS, FAIL, BLOCKED_ENVIRONMENT,
NOT_IMPLEMENTED and NOT_EXECUTED remain distinct. A negative case is PASS only
when its actual rejection matches the independent expected error and fields.
An absent declared prerequisite prevents execution and holds the result;
evidence lost or modified after execution fails the result.

The complete local qualification inventory is the union of the governed 46 crash
and 65 clock IDs. A successful smaller set is labelled SUBSET and leaves
`legacy_full_qualification=HOLD`. No environment sentinel satisfies a crash ID.
Every required full crash case currently remains NOT_IMPLEMENTED. There is no
accepted full-crash evidence adapter while the real full shared/browser owners
remain absent; future implementation and review must supply one before full PASS
is possible. R08 does not implement those owners or fabricate their evidence.

Executed clock rows bind actual Git HEAD and working source bytes, all vendor
bytes, schema/uv/pnpm locks, Python/Node executable hashes and host environment.
The gate rereads those bytes and the actual artifact, verifies input/expected
hashes, checks the current governed case oracle, compares both language outputs,
and requires matching command exits, first error and comparison. A changed
source, build output, lock, environment or revision requires fresh execution.
This conservative binding covers all runtime/tool sources, so unrelated source
edits can also require a rerun. It is a local byte check, not signed authority.

The clock runner captures bindings before execution and uses this gate in its
own summary. Its existing mutation runner still requires actual controls/trials
and fails on missing nested artifacts; mutations are not extra required-case
rows. `actual.json` remains actual-only; input/oracle data stay in the parent row.

CLI: `uv run --frozen --offline python tools/verify_repair_evidence.py evidence.json`,
where the JSON object has `required_ids` and `results`. Exit 0 is scoped PASS,
exit 2 is HOLD, and exit 1 is FAIL. Consumers must inspect qualification scope.
Compile the existing TypeScript test target before clock execution. Compiled
output is evidence-bound and is never hand-edited to refresh a receipt.

## Dependency-aware findings

| Evidence group | Truthful state and required rerun |
| --- | --- |
| R03 full inherited crash obligations | All 46 NOT_IMPLEMENTED/HOLD. The 18 tested backend boundaries are supplemental and do not complete inherited browser/lifecycle contracts. Rerun affected backend source checks and retain full-case holds. |
| R04 browser environment | Last actual probe BLOCKED_ENVIRONMENT: E_EXTENSION_TARGET_UNAVAILABLE, renderer chrome-error:. No extension sentinel crash/readback completed. This task launches no browser. |
| R05 shared spool and ACK owner | Unimplemented; dependency/environment blocked. No browser or shared ACK execution can be inferred from R04 test counts. |
| R07 clock | Fresh runner provides 17 executed PASS and 48 NOT_IMPLEMENTED; six actual comparator mutations. Full clock HOLD. Old results lack the new binding and require rerun. |
| R09 portable/full routing | Portable PASS is routing and regression evidence only. Full controller configuration and changed source receipts remain held under its own prerequisite report. |
| Combined required cases | 17 PASS + 94 NOT_IMPLEMENTED = 111 terminal rows, complete inventory, aggregate HOLD. This is not 111 executions. |

Supplemental R03 `scoped_result`/`scoped_evidence` must be reported separately,
with their original artifacts and scope. R08 rejects such fields in the required
case input instead of silently accepting unverified nested artifacts. For a full
inventory report, obtain the no-launch `run_family(..., observation_input=None)`
rows; do not turn backend projection PASS into full vector PASS.

## Consumer inventory and invalidated claims

- `src/moj_discovery/durability_release.py` formerly accepted matching ID lists
  and a literal zero mutation count. Controller-authorized containment now
  rejects missing evidence and requires R08 full qualification. Its old caller
  in `tests/durability/test_destruction_and_release.py` remains an unfulfilled
  full destruction obligation, not a compatibility PASS path.
- `tools/run_clock_vector_qualification.py::summarize` now checks R08 bindings
  and registered oracles in addition to its actual artifact/counter checks.
  Repair and `tests/clock/test_clock_parity_and_mutation.py` counters are derived
  from verified records and retain HOLD for missing runtime families.
- `tools/inspect_restart_state.py` counters describe actual owned process kills;
  they alone are not qualification. `run_loopback_ack_crash_matrix.py::run_family`
  keeps full rows NOT_IMPLEMENTED even when supplemental backend cases execute.
- Legacy `tests/durability/test_{sqlite,loopback_ack,gap_generation,indexeddb}_process_crash.py`,
  destruction and Chrome-environment assertions still demand obsolete full PASS
  or counts. Their ordinary failures remain visible; they are not reinterpreted
  as repaired acceptance, skipped to turn a gate green, or silently deleted.
- Review/candidate/controller receipts and external obligations retain their
  existing gates. Old Review A/B/P10 or inventory-only durability/65-clock PASS
  claims do not certify changed code or current execution; independent closure
  and applicable controller reruns are still required.

No historical receipt, sealed pack, vendor file, registry, lockfile or signed
aggregate was rewritten. The ignored task report records fresh commands,
artifact locations and the exact tested revision without a self-hash cycle.
