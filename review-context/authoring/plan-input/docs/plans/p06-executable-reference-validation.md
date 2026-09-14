# P06 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P06-T01 — Resolve every executable file, symbol, schema, vector, command, and config

Run exact resolution only after materialization and implementation phases have produced all artifacts.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → EXECUTABLE.

### Dependencies

- `V636-MIG0-T08`

### Preconditions

- Dependency V636-MIG0-T08 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/verify_executable_references.py`
- `runtime/tests/release/test_executable_references.py`

### Exact files

- `runtime/tools/verify_executable_references.py`
- `runtime/tests/release/test_executable_references.py`

### Exact symbols

- `runtime/tools/verify_executable_references.py::verify_executable_references`
- `runtime/tests/release/test_executable_references.py::test_every_executable_reference_resolves_without_placeholder`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P06_T01`

### Tests

- `runtime/tests/release/test_executable_references.py`

### Positive vectors

- `V636-P06-T01-POS-01`

### Negative vectors

- `V636-P06-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Files unresolved zero
- Symbols unresolved zero
- Schema pointers unresolved zero
- Commands/configs unresolved zero

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P06-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P06-T02 — Verify test discovery, build configs, and command coverage

Prove Python and TypeScript discovery includes bootstrap, migration, contracts, durability, clock, review, security, and release suites plus crash harness compilation.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → EXECUTABLE.

### Dependencies

- `V636-P06-T01`

### Preconditions

- Dependency V636-P06-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/tools/verify_test_discovery.py`
- `runtime/tests/release/test_verification_topology.py`

### Exact files

- `runtime/tools/verify_test_discovery.py`
- `runtime/tests/release/test_verification_topology.py`

### Exact symbols

- `runtime/tools/verify_test_discovery.py::verify_verification_topology`
- `runtime/tests/release/test_verification_topology.py::test_all_proof_groups_are_discovered_and_registry_bound`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P06_T02`

### Tests

- `runtime/tests/release/test_verification_topology.py`

### Positive vectors

- `V636-P06-T02-POS-01`

### Negative vectors

- `V636-P06-T02-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every proof group has exact commands
- Crash harness sources are compiled
- Bare pytest is not the only release proof

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P06-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P06-T03 — Issue EXECUTABLE_REFERENCE_COMPLETE gate

Issue a content-addressed receipt only after all exact references and proof topology are executable.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → EXECUTABLE.

### Dependencies

- `V636-P06-T02`

### Preconditions

- Dependency V636-P06-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/executable_gate.py`
- `runtime/tests/release/test_executable_complete_gate.py`

### Exact files

- `runtime/src/moj_discovery/executable_gate.py`
- `runtime/tests/release/test_executable_complete_gate.py`

### Exact symbols

- `runtime/src/moj_discovery/executable_gate.py::issue_executable_reference_complete_receipt`
- `runtime/tests/release/test_executable_complete_gate.py::test_gate_rejects_intentional_stub_or_unexecuted_command`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P06_T03`

### Tests

- `runtime/tests/release/test_executable_complete_gate.py`

### Positive vectors

- `V636-P06-T03-POS-01`

### Negative vectors

- `V636-P06-T03-NEG-01`

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

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P06-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
