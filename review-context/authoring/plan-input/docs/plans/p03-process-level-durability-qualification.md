# P03 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P03-T01 — Freeze and validate complete crash-vector mapping

Map every inherited and successor crash vector to exactly one harness, child command, checkpoint, state inspector, expected state, mutations, owner, and verification command.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P02-T03`

### Preconditions

- Dependency V636-P02-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/durability_registry.py`
- `runtime/tests/durability/test_crash_registry.py`

### Exact files

- `runtime/src/moj_discovery/durability_registry.py`
- `runtime/tests/durability/test_crash_registry.py`
- `pack/docs/registries/crash-harness-registry.v1.json`
- `pack/docs/vectors/inherited/durability-crash-v6.2.json`
- `pack/docs/registries/crash-child-command-registry.v1.json`

### Exact symbols

- `runtime/src/moj_discovery/durability_registry.py::validate_crash_harness_registry`
- `runtime/tests/durability/test_crash_registry.py::test_every_normative_vector_has_one_process_execution_mapping`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T01`

### Tests

- `runtime/tests/durability/test_crash_registry.py`

### Positive vectors

- `V636-P03-T01-POS-01`

### Negative vectors

- `V636-P03-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Original vectors accounted 100%
- Process execution mapping 100%
- No declaration-only or unowned vector
- All 46 inherited case IDs are mapped exactly once
- Source case order, boundary, kill action, and expected state are preserved

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T02 — Qualify real Chrome and IndexedDB test environment

Prove a real Chrome/Chromium process can load the synthetic extension, persist IndexedDB, be abruptly killed, restart with the same profile, and expose the durable sentinel.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T01`

### Preconditions

- Dependency V636-P03-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/qualify_chrome_indexeddb.py`
- `runtime/tests/durability/test_chrome_indexeddb_environment.py`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/tools/inspect_restart_state.py`

### Exact files

- `runtime/tools/qualify_chrome_indexeddb.py`
- `runtime/tests/durability/test_chrome_indexeddb_environment.py`
- `runtime/extension/test-harness/indexeddb-crash-child.ts`
- `runtime/tools/inspect_restart_state.py`

### Exact symbols

- `runtime/tools/qualify_chrome_indexeddb.py::qualify_chrome_indexeddb_environment`
- `runtime/tests/durability/test_chrome_indexeddb_environment.py::test_real_chrome_indexeddb_survives_abrupt_process_kill`
- `runtime/tools/inspect_restart_state.py::inspect_restart_state`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION`
- `TEST_V636_P03_T02`

### Tests

- `runtime/tests/durability/test_chrome_indexeddb_environment.py`

### Positive vectors

- `V636-P03-T02-POS-01`

### Negative vectors

- `V636-P03-T02-NEG-01`
- `R633-03-REGRESSION`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Real browser process used
- No in-memory or fake IndexedDB substitution
- Environment limitation yields BLOCKED
- Compile modified TypeScript child with COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION before tests; bind emitted bytes to current source and config hashes.
- Reproduce R633-03 from REPAIR_MATRIX_V6_3_6.md and prove its correction; fail if the old counterexample is accepted.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T03 — Execute IndexedDB spool crash matrix

Process-execute every CHROME_INDEXEDDB vector around sequence allocation, payload commit, send boundary, and restart.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T02`

### Preconditions

- Dependency V636-P03-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_indexeddb_crash_matrix.py`
- `runtime/tests/durability/test_indexeddb_process_crash.py`

### Exact files

- `runtime/tools/run_indexeddb_crash_matrix.py`
- `runtime/tests/durability/test_indexeddb_process_crash.py`

### Exact symbols

- `runtime/tools/run_indexeddb_crash_matrix.py::run_indexeddb_crash_matrix`
- `runtime/tests/durability/test_indexeddb_process_crash.py::test_all_indexeddb_vectors_match_expected_restart_state`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T03`
- `CRASH_VECTOR_IDB_01_BEFORE_TRANSACTION`
- `CRASH_VECTOR_IDB_02_DURING_SEQUENCE_ALLOCATION`
- `CRASH_VECTOR_IDB_03_DURING_ROW_PUT`
- `CRASH_VECTOR_IDB_04_AFTER_COMMIT`

### Tests

- `runtime/tests/durability/test_indexeddb_process_crash.py`

### Positive vectors

- `V636-P03-T03-POS-01`

### Negative vectors

- `V636-P03-T03-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T04 — Execute loopback delivery and ACK crash matrix

Process-execute spool/send/backend-commit/ACK persistence and restart-handshake vectors.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T03`

### Preconditions

- Dependency V636-P03-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_loopback_ack_crash_matrix.py`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tests/durability/test_loopback_ack_process_crash.py`

### Exact files

- `runtime/tools/run_loopback_ack_crash_matrix.py`
- `runtime/tools/loopback_ack_crash_child.py`
- `runtime/tests/durability/test_loopback_ack_process_crash.py`

### Exact symbols

- `runtime/tools/run_loopback_ack_crash_matrix.py::run_loopback_ack_crash_matrix`
- `runtime/tests/durability/test_loopback_ack_process_crash.py::test_ack_never_crosses_uncommitted_or_gapped_position`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T04`
- `CRASH_VECTOR_SEND_01_AFTER_SEND_BEFORE_BACKEND_BEGIN`
- `CRASH_VECTOR_ACK_01_BEFORE_EXTENSION_ACK_TRANSACTION`
- `CRASH_VECTOR_ACK_02_DURING_EXTENSION_ACK_TRANSACTION`
- `CRASH_VECTOR_ACK_03_AFTER_EXTENSION_ACK_TRANSACTION`
- `CRASH_VECTOR_ACK_04_BEFORE_BACKEND_CONFIRMATION_COMMIT`
- `CRASH_VECTOR_ACK_05_AFTER_BACKEND_CONFIRMATION_COMMIT`
- `CRASH_VECTOR_ACK_06_DUPLICATE_IDENTICAL`

### Tests

- `runtime/tests/durability/test_loopback_ack_process_crash.py`

### Positive vectors

- `V636-P03-T04-POS-01`

### Negative vectors

- `V636-P03-T04-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T05 — Execute SQLite transaction crash matrix

SIGKILL child processes before, during, and after every RawCommit/Application/DerivedRevision/ReducerCursor/AckOutbox/COMMIT boundary.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T04`

### Preconditions

- Dependency V636-P03-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_sqlite_crash_matrix.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tests/durability/test_sqlite_process_crash.py`

### Exact files

- `runtime/tools/run_sqlite_crash_matrix.py`
- `runtime/tools/sqlite_crash_child.py`
- `runtime/tests/durability/test_sqlite_process_crash.py`

### Exact symbols

- `runtime/tools/run_sqlite_crash_matrix.py::run_sqlite_crash_matrix`
- `runtime/tests/durability/test_sqlite_process_crash.py::test_sql_transaction_is_all_or_none_after_sigkill`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T05`
- `CRASH_VECTOR_SQL_01_AFTER_RAW_COMMIT_STATEMENT`
- `CRASH_VECTOR_SQL_02_AFTER_APPLICATION_STATEMENT`
- `CRASH_VECTOR_SQL_03_AFTER_DERIVED_REVISION_STATEMENT`
- `CRASH_VECTOR_SQL_04_AFTER_REDUCER_CURSOR_STATEMENT`
- `CRASH_VECTOR_SQL_05_AFTER_ACK_OUTBOX_STATEMENT`
- `CRASH_VECTOR_SQL_06_DURING_COMMIT`
- `CRASH_VECTOR_SQL_07_AFTER_COMMIT_BEFORE_ACK_SEND`

### Tests

- `runtime/tests/durability/test_sqlite_process_crash.py`

### Positive vectors

- `V636-P03-T05-POS-01`

### Negative vectors

- `V636-P03-T05-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T05.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T06 — Execute GAP, generation, and coherence crash matrix

Process-execute conflict, predecessor close, GAP insert, generation transition, successor open, epoch close, and late-repair boundaries.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T05`

### Preconditions

- Dependency V636-P03-T05 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_gap_coherence_crash_matrix.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tests/durability/test_gap_generation_process_crash.py`

### Exact files

- `runtime/tools/run_gap_coherence_crash_matrix.py`
- `runtime/tools/gap_coherence_crash_child.py`
- `runtime/tests/durability/test_gap_generation_process_crash.py`

### Exact symbols

- `runtime/tools/run_gap_coherence_crash_matrix.py::run_gap_coherence_crash_matrix`
- `runtime/tests/durability/test_gap_generation_process_crash.py::test_closed_generation_and_epoch_never_reopen`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T06`
- `CRASH_VECTOR_GAP_01_AFTER_GAP_INSERT`
- `CRASH_VECTOR_GAP_02_AFTER_SHOCK_INSERT`
- `CRASH_VECTOR_GAP_03_AFTER_COHERENCE_TRANSITION`
- `CRASH_VECTOR_GAP_04_AFTER_CONTROLLER_CLOSE`
- `CRASH_VECTOR_GAP_05_AFTER_EPOCH_BINDING`
- `CRASH_VECTOR_GAP_06_AFTER_PREDECESSOR_CLOSE`
- `CRASH_VECTOR_GAP_07_AFTER_GENERATION_TRANSITION`
- `CRASH_VECTOR_GAP_08_AFTER_SUCCESSOR_INSERT`
- `CRASH_VECTOR_GAP_09_DURING_COMMIT`
- `CRASH_VECTOR_GAP_10_AFTER_COMMIT`
- `CRASH_VECTOR_CONFLICT_01_SAME_POSITION_DIFFERENT_HASH`
- `CRASH_VECTOR_LATE_01_MISSING_POSITION_AFTER_GAP`
- `CRASH_VECTOR_GAP_11_REPEATED_GAP_IN_SUCCESSOR`
- `CRASH_VECTOR_CAPACITY_01_NORMAL_LIMIT_REACHED`
- `CRASH_VECTOR_CLOCK_01_AFTER_MAPPING_CLOSURE_INSERT`
- `CRASH_VECTOR_CLOCK_02_AFTER_CLOSURE_COMMIT_BEFORE_SHOCK`
- `CRASH_VECTOR_EPOCH_01_AFTER_SHOCK_BEFORE_CLOSE_COMMIT`
- `CRASH_VECTOR_EPOCH_02_AFTER_SHOCK_CLOSE_COMMIT`
- `CRASH_VECTOR_EPOCH_03_AFTER_PENDING_WRITES_BEFORE_COMMIT`
- `CRASH_VECTOR_EPOCH_04_DURING_NEW_EPOCH_OPEN_COMMIT`
- `CRASH_VECTOR_EPOCH_05_NEW_SHOCK_WHILE_PENDING`

### Tests

- `runtime/tests/durability/test_gap_generation_process_crash.py`

### Positive vectors

- `V636-P03-T06-POS-01`

### Negative vectors

- `V636-P03-T06-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T06.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P03-T07 — Execute destruction matrix and durability release gate

Process-execute every whole-run destruction boundary, mutate every expected restart state, and issue the durability release receipt only when coverage is exact.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P03-T06`

### Preconditions

- Dependency V636-P03-T06 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_destruction_crash_matrix.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/src/moj_discovery/durability_release.py`
- `runtime/tests/durability/test_destruction_and_release.py`

### Exact files

- `runtime/tools/run_destruction_crash_matrix.py`
- `runtime/tools/destruction_crash_child.py`
- `runtime/src/moj_discovery/durability_release.py`
- `runtime/tests/durability/test_destruction_and_release.py`

### Exact symbols

- `runtime/tools/run_destruction_crash_matrix.py::run_destruction_crash_matrix`
- `runtime/src/moj_discovery/durability_release.py::validate_full_durability_release`
- `runtime/tests/durability/test_destruction_and_release.py::test_declared_equals_executed_and_mutation_survivors_zero`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P03_T07`
- `CRASH_VECTOR_DESTROY_01_BEFORE_AUTHORITY`
- `CRASH_VECTOR_DESTROY_01A_AFTER_CONSUMPTION_BEFORE_INTENT`
- `CRASH_VECTOR_DESTROY_02_AFTER_INTENT_BEFORE_DELETION`
- `CRASH_VECTOR_DESTROY_03_AFTER_EXTENSION_DELETION`
- `CRASH_VECTOR_DESTROY_04_AFTER_BACKEND_DELETION`
- `CRASH_VECTOR_DESTROY_05_AFTER_BOTH_DELETIONS_BEFORE_PROOF`
- `CRASH_VECTOR_DESTROY_06_AFTER_PROOF`

### Tests

- `runtime/tests/durability/test_destruction_and_release.py`

### Positive vectors

- `V636-P03-T07-POS-01`

### Negative vectors

- `V636-P03-T07-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Declared process vectors equal executed vectors
- Declaration-only vectors zero
- Unexpected graceful exits zero
- Mutation survivors zero

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P03-T07.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
