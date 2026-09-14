# P07 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P07-T01 — Run complete candidate command registry

Execute every exact qualification command against the authoring runtime candidate with no authenticated operator/provider access.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: EXECUTABLE → QUALIFIED.

### Dependencies

- `V636-P06-T03`

### Preconditions

- Dependency V636-P06-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tools/run_command_registry.py`
- `runtime/tests/release/test_candidate_command_registry.py`

### Exact symbols

- `runtime/tools/run_command_registry.py::main`
- `runtime/tests/release/test_candidate_command_registry.py::test_candidate_mode_runs_every_required_command_once`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P07_T01`

### Tests

- `runtime/tests/release/test_candidate_command_registry.py`

### Positive vectors

- `V636-P07-T01-POS-01`

### Negative vectors

- `V636-P07-T01-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P07-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P07-T02 — Validate complete proof-coverage matrix

Require all and only CANDIDATE-stage proof rows; SEALED and REVIEWED rows must remain pending and confer no candidate authority.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: EXECUTABLE → QUALIFIED.

### Dependencies

- `V636-P07-T01`

### Preconditions

- Dependency V636-P07-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tests/release/test_full_proof_coverage.py`

### Exact symbols

- `runtime/tests/release/test_full_proof_coverage.py::test_every_proof_matrix_row_has_passing_evidence`

### Schema pointers

- `pack/docs/schemas/proof-coverage.schema.json#/$defs/ProofCoverageMatrix`

### Exact command IDs

- `VERIFY_V636_P07_T02`

### Tests

- `runtime/tests/release/test_full_proof_coverage.py`

### Positive vectors

- `V636-P07-T02-POS-01`

### Negative vectors

- `V636-P07-T02-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- Every CANDIDATE row has current passing evidence
- No future-stage evidence is consumed or fabricated
- Later rows remain mandatory at their own gates

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P07-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P07-T03 — Issue candidate qualification receipt

Bind command-result root, proof matrix, exactness gates, clean candidate state, absence of live evidence, and production authority NONE.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: EXECUTABLE → QUALIFIED.

### Dependencies

- `V636-P07-T02`

### Preconditions

- Dependency V636-P07-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`

### Exact symbols

- `runtime/tools/build_candidate_qualification_receipt.py::main`
- `runtime/tests/release/test_candidate_qualification_receipt.py::test_receipt_rejects_skipped_command_live_evidence_or_production_authority`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P07_T03`

### Tests

- `runtime/tests/release/test_candidate_qualification_receipt.py`

### Positive vectors

- `V636-P07-T03-POS-01`

### Negative vectors

- `V636-P07-T03-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P07-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
