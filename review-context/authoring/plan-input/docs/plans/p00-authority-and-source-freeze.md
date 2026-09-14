# P00 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P00-T01 — Freeze source reviews and provenance

Import the v6.3.1 plan review as immutable source evidence and bind the v6.3.1 plan ZIP plus v6.2 review hashes.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → DECLARED.

### Dependencies

- `V636-BOOT0-T03`

### Preconditions

- Dependency V636-BOOT0-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/import_review_sources.py`
- `authoring-tests/test_review_source_import.py`
- `pack/docs/receipts/source-provenance.v1.json`

### Exact files

- `authoring-tools/import_review_sources.py`
- `authoring-tests/test_review_source_import.py`
- `pack/docs/reviews/v6.3.1-plan-review-input.md`
- `pack/docs/receipts/source-provenance.v1.json`
- `pack/docs/registries/source-inputs.v1.json`

### Exact symbols

- `authoring-tools/import_review_sources.py::import_review_sources`
- `authoring-tests/test_review_source_import.py::test_review_sources_match_frozen_hashes`

### Schema pointers

- `pack/docs/schemas/migration-receipt.schema.json#/$defs/MigrationReceipt`

### Exact command IDs

- `VERIFY_V636_P00_T01`

### Tests

- `authoring-tests/test_review_source_import.py`

### Positive vectors

- `V636-P00-T01-POS-01`

### Negative vectors

- `V636-P00-T01-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Source hashes exactly match the frozen registry
- Imported review bytes are immutable
- No source review is rewritten

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P00-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P00-T02 — Freeze authority graphs

Create separate machine-readable executable and future graphs with no cross-class edge or reachability.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → DECLARED.

### Dependencies

- `V636-P00-T01`

### Preconditions

- Dependency V636-P00-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/validate_authority_graph.py`
- `authoring-tests/test_authority_graph.py`
- `pack/docs/contracts/02-authority-graph.md`

### Exact files

- `authoring-tools/validate_authority_graph.py`
- `authoring-tests/test_authority_graph.py`
- `pack/docs/graphs/executable-discovery-graph.v1.json`
- `pack/docs/graphs/non-authoritative-future-roadmap.v1.json`
- `pack/docs/contracts/02-authority-graph.md`

### Exact symbols

- `authoring-tools/validate_authority_graph.py::validate_graph_partition`
- `authoring-tests/test_authority_graph.py::test_executable_and_future_graphs_are_disconnected`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P00_T02`

### Tests

- `authoring-tests/test_authority_graph.py`

### Positive vectors

- `V636-P00-T02-POS-01`

### Negative vectors

- `V636-P00-T02-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- No cross-set endpoints
- No executable-to-future transitive path
- AUTHORIZED_PRODUCTION_PHASES remains NONE

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P00-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P00-T03 — Freeze task schema and manifest semantics

Define the exact task-card format, task lifecycle, dependency semantics, authority enum, and semantic validator responsibilities.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → DECLARED.

### Dependencies

- `V636-P00-T02`

### Preconditions

- Dependency V636-P00-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/validate_task_manifest.py`
- `authoring-tests/test_task_manifest_semantics.py`

### Exact files

- `authoring-tools/validate_task_manifest.py`
- `authoring-tests/test_task_manifest_semantics.py`
- `pack/docs/tasks/task-manifest.v6.3.6.json`
- `pack/docs/schemas/task-card-v6.3.6.schema.json`
- `pack/docs/contracts/01-artifact-lifecycle.md`

### Exact symbols

- `authoring-tools/validate_task_manifest.py::validate_task_manifest_semantics`
- `authoring-tests/test_task_manifest_semantics.py::test_task_manifest_rejects_placeholders_unknown_dependencies_and_production_authority`

### Schema pointers

- `pack/docs/schemas/task-card-v6.3.6.schema.json#/$defs/TaskManifestV636`
- `pack/docs/schemas/task-card-v6.3.6.schema.json#/$defs/TaskCardV636`

### Exact command IDs

- `VERIFY_V636_P00_T03`

### Tests

- `authoring-tests/test_task_manifest_semantics.py`

### Positive vectors

- `V636-P00-T03-POS-01`

### Negative vectors

- `TASK-AUTHORITY-PRODUCTION`
- `TASK-COMMAND-PLACEHOLDER`
- `TASK-UNKNOWN-DEPENDENCY`
- `TASK-EMPTY-ROLLBACK`
- `TASK-COUNT-MISMATCH`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Task count equals array length
- Only approved task authorities are accepted
- Every dependency names an earlier declared task

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P00-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P00-T04 — Freeze artifact ownership and path registries

Assign every planned artifact one creation owner, lifecycle stage, and allowed modifier set.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → DECLARED.

### Dependencies

- `V636-P00-T03`

### Preconditions

- Dependency V636-P00-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/validate_artifact_ownership.py`
- `authoring-tests/test_artifact_ownership.py`

### Exact files

- `authoring-tools/validate_artifact_ownership.py`
- `authoring-tests/test_artifact_ownership.py`
- `pack/docs/registries/artifact-ownership.v1.json`
- `pack/docs/registries/path-registry.v1.json`
- `pack/docs/registries/schema-reference-registry.v1.json`
- `pack/docs/schemas/artifact-ownership.schema.json`

### Exact symbols

- `authoring-tools/validate_artifact_ownership.py::validate_artifact_ownership`
- `authoring-tests/test_artifact_ownership.py::test_every_referenced_artifact_has_one_creation_owner`

### Schema pointers

- `pack/docs/schemas/artifact-ownership.schema.json#/$defs/ArtifactOwnershipRegistry`

### Exact command IDs

- `VERIFY_V636_P00_T04`

### Tests

- `authoring-tests/test_artifact_ownership.py`

### Positive vectors

- `V636-P00-T04-POS-01`

### Negative vectors

- `V636-P00-T04-NEG-01`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every exact file has a baseline source or one creation owner
- No artifact has conflicting creation owners
- Consumers never precede creation owner

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P00-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P00-T05 — Issue DECLARATION_COMPLETE gate

Prove that every planned artifact, command, schema, vector, task dependency, lifecycle stage, and authority class is declared and owned without requiring future implementation symbols to exist.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → DECLARED.

### Dependencies

- `V636-P00-T04`

### Preconditions

- Dependency V636-P00-T04 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `authoring-tools/issue_declaration_gate.py`
- `authoring-tests/test_declaration_gate.py`
- `pack/docs/receipts/declaration-complete.v1.json`

### Exact files

- `authoring-tools/issue_declaration_gate.py`
- `authoring-tests/test_declaration_gate.py`
- `pack/docs/receipts/declaration-complete.v1.json`

### Exact symbols

- `authoring-tools/issue_declaration_gate.py::issue_declaration_complete_receipt`
- `authoring-tests/test_declaration_gate.py::test_declaration_gate_checks_ownership_without_requiring_materialized_symbols`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `ISSUE_V636_P00_T05`

### Tests

- `authoring-tests/test_declaration_gate.py`

### Positive vectors

- `DECLARATION-ALL-OWNED-AND-ORDERED`

### Negative vectors

- `DECLARATION-UNOWNED-ARTIFACT`
- `DECLARATION-CONSUMER-BEFORE-OWNER`
- `DECLARATION-REQUIRES-FUTURE-SYMBOL`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- Every planned artifact has exactly one baseline source or creation owner
- No consumer precedes its owner
- No materialization or symbol-existence proof is required at declaration stage

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P00-T05.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop if any exact input, file, symbol, schema, vector, command, or authority condition is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
