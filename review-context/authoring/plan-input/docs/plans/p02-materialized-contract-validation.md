# P02 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P02-T01 — Validate materialized task-manifest semantics

Reject task-count mismatch, unknown/forward dependencies, production authority, placeholders, empty rollback, unresolved command IDs, and invalid lifecycle transitions.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → MATERIALIZED.

### Dependencies

- `V636-MIG0-T07`

### Preconditions

- Dependency V636-MIG0-T07 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/governance.py`
- `runtime/src/moj_discovery/task_contracts.py`
- `runtime/tests/bootstrap/test_graph_partition.py`
- `runtime/tests/contracts/test_task_manifest_semantics.py`

### Exact files

- `pack/docs/registries/inherited-baseline-qualification.v1.json`
- `runtime/src/moj_discovery/governance.py`
- `runtime/src/moj_discovery/task_contracts.py`
- `runtime/tests/bootstrap/test_graph_partition.py`
- `runtime/tests/contracts/test_task_manifest_semantics.py`

### Exact symbols

- `runtime/src/moj_discovery/task_contracts.py::validate_task_manifest_semantics`
- `runtime/tests/contracts/test_task_manifest_semantics.py::test_review_counterexamples_are_rejected`

### Schema pointers

- `pack/docs/schemas/task-card-v6.3.6.schema.json#/$defs/TaskManifestV636`
- `pack/docs/schemas/task-card-v6.3.6.schema.json#/$defs/TaskCardV636`

### Exact command IDs

- `TEST_V636_P02_T01`

### Tests

- `runtime/tests/contracts/test_task_manifest_semantics.py`

### Positive vectors

- `V636-P02-T01-POS-01`

### Negative vectors

- `TASK-PRODUCTION-AUTHORITY`
- `TASK-PLACEHOLDER-COMMAND`
- `TASK-UNKNOWN-DEPENDENCY`
- `TASK-FUTURE-DEPENDENCY`
- `TASK-EMPTY-ROLLBACK`
- `TASK-COUNT-MISMATCH`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced
- Preserve all named tests and negative cases; adapt inputs according to docs/contracts/09-inherited-baseline-qualification.md.
- validate_task_dependencies accepts the successor task manifest explicitly and validates its declared count/DAG; validate_canonical_registry accepts pinned historical registry data and explicit successor coverage bindings, never assumes active commands have v6.2 verification_commands shape.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P02-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P02-T02 — Validate materialized artifact ownership and lifecycle

Validate owner uniqueness, owner-before-consumer ordering, declared materialization stage, modifier permissions, and no unowned required artifact.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → MATERIALIZED.

### Dependencies

- `V636-P02-T01`

### Preconditions

- Dependency V636-P02-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/artifact_ownership.py`
- `runtime/tests/contracts/test_artifact_dependency_semantics.py`

### Exact files

- `runtime/src/moj_discovery/artifact_ownership.py`
- `runtime/tests/contracts/test_artifact_dependency_semantics.py`

### Exact symbols

- `runtime/src/moj_discovery/artifact_ownership.py::validate_artifact_lifecycle`
- `runtime/tests/contracts/test_artifact_dependency_semantics.py::test_consumer_cannot_precede_creation_owner`

### Schema pointers

- `pack/docs/schemas/artifact-ownership.schema.json#/$defs/ArtifactOwnershipRegistry`

### Exact command IDs

- `TEST_V636_P02_T02`

### Tests

- `runtime/tests/contracts/test_artifact_dependency_semantics.py`

### Positive vectors

- `V636-P02-T02-POS-01`

### Negative vectors

- `V636-P02-T02-NEG-01`

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

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P02-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P02-T03 — Issue MATERIALIZED_CONTRACTS_VALID gate

Prove the plan has complete ownership, exact command identities, valid schema references, and no unresolved declaration-level architecture.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: MATERIALIZED → MATERIALIZED.

### Dependencies

- `V636-P02-T02`

### Preconditions

- Dependency V636-P02-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `runtime/src/moj_discovery/declaration_gate.py`
- `runtime/tests/contracts/test_declaration_complete_gate.py`

### Exact files

- `runtime/src/moj_discovery/declaration_gate.py`
- `runtime/tests/contracts/test_declaration_complete_gate.py`

### Exact symbols

- `runtime/src/moj_discovery/declaration_gate.py::issue_declaration_complete_receipt`
- `runtime/tests/contracts/test_declaration_complete_gate.py::test_declaration_gate_fails_on_unowned_schema_or_command`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `TEST_V636_P02_T03`

### Tests

- `runtime/tests/contracts/test_declaration_complete_gate.py`

### Positive vectors

- `V636-P02-T03-POS-01`

### Negative vectors

- `V636-P02-T03-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every planned artifact has an owner
- Every command ID exists
- Schema refs may be declared only when their materialization owner is complete

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P02-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
