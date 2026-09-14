# P04 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P04-T01 — Freeze clock failure precedence registry

Create one shared ordered registry for mapping rejection and acceptance so Python and TypeScript cannot diverge.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P02-T03`

### Preconditions

- Dependency V636-P02-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/clock_precedence.py`
- `runtime/tests/clock/test_failure_precedence_registry.py`

### Exact files

- `runtime/src/moj_discovery/clock_precedence.py`
- `runtime/tests/clock/test_failure_precedence_registry.py`
- `pack/docs/registries/clock-failure-precedence.v1.json`
- `pack/docs/vectors/inherited/clock-coherence-v6.2.json`
- `pack/docs/registries/clock-vector-coverage.v1.json`

### Exact symbols

- `runtime/src/moj_discovery/clock_precedence.py::load_clock_failure_precedence`
- `runtime/tests/clock/test_failure_precedence_registry.py::test_precedence_registry_is_total_unique_and_shared`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P04_T01`

### Tests

- `runtime/tests/clock/test_failure_precedence_registry.py`

### Positive vectors

- `V636-P04-T01-POS-01`

### Negative vectors

- `V636-P04-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced
- All 16 inherited mapping-negative vectors are mapped with exact expected error and eligibility
- All 65 named inherited clock/coherence vectors are accounted for by the coverage registry

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P04-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P04-T02 — Implement Python clock-vector evaluator

Recompute interval, RTT, padding, uncertainty, drift, eligibility, and first failure from inputs without trusting expected fields.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P04-T01`

### Preconditions

- Dependency V636-P04-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/tests/clock/test_python_clock_vectors.py`

### Exact files

- `runtime/src/moj_discovery/clock_vectors.py`
- `runtime/tests/clock/test_python_clock_vectors.py`

### Exact symbols

- `runtime/src/moj_discovery/clock_vectors.py::evaluate_clock_mapping_vector`
- `runtime/tests/clock/test_python_clock_vectors.py::test_python_evaluator_recomputes_all_positive_and_negative_vectors`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P04_T02`

### Tests

- `runtime/tests/clock/test_python_clock_vectors.py`

### Positive vectors

- `V636-P04-T02-POS-01`

### Negative vectors

- `V636-P04-T02-NEG-01`

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

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P04-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P04-T03 — Implement TypeScript clock-vector evaluator

Implement the same evaluator from the same registry bytes and compile it under the test configuration.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P04-T02`

### Preconditions

- Dependency V636-P04-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/extension/src/contracts/clock-vectors.ts`
- `runtime/extension/test/clock/clock-vectors.test.ts`

### Exact files

- `runtime/extension/src/contracts/clock-vectors.ts`
- `runtime/extension/test/clock/clock-vectors.test.ts`

### Exact symbols

- `runtime/extension/src/contracts/clock-vectors.ts#evaluateClockMappingVector`
- `runtime/extension/test/clock/clock-vectors.test.ts#clockVectorQualificationSuite`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `COMPILE_V636_P04_T03`
- `TEST_TS_V636_P04_T03`

### Tests

- `runtime/extension/test/clock/clock-vectors.test.ts`

### Positive vectors

- `V636-P04-T03-POS-01`

### Negative vectors

- `V636-P04-T03-NEG-01`

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

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P04-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P04-T04 — Qualify cross-language clock parity and mutation sensitivity

Run all vectors through both evaluators and prove expected eligibility/error/input mutations are detected.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → QUALIFIED.

### Dependencies

- `V636-P04-T03`

### Preconditions

- Dependency V636-P04-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/run_clock_vector_qualification.py`
- `runtime/tests/clock/test_clock_parity_and_mutation.py`

### Exact files

- `runtime/tools/run_clock_vector_qualification.py`
- `runtime/tests/clock/test_clock_parity_and_mutation.py`

### Exact symbols

- `runtime/tools/run_clock_vector_qualification.py::run_clock_vector_qualification`
- `runtime/tests/clock/test_clock_parity_and_mutation.py::test_cross_language_drift_and_mutation_survivors_are_zero`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P04_T04`

### Tests

- `runtime/tests/clock/test_clock_parity_and_mutation.py`

### Positive vectors

- `V636-P04-T04-POS-01`

### Negative vectors

- `V636-P04-T04-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Cross-language drift zero
- Mutation survivors zero
- Skipped vectors zero

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P04-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
