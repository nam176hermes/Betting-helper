# BOOT0 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-BOOT0-T01 — Verify and extract sealed plan input

Verify the supplied plan ZIP against its sidecar, safely extract it, and verify its self-excluding manifest before any authoring workspace is created.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

None; this task consumes previously created artifacts.

### Preconditions

- Supplied ZIP, sidecar and pinned bootstrap prerequisites are present

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json`

### Exact files

- `/home/thenam176/betting-helper/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json`

### Exact symbols

- `bootstrap/verify_extracted_plan.py::verify_extracted_plan`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `BOOT0_PREPARE_INPUT_DIRS`
- `BOOT0_VERIFY_SIDECAR`
- `BOOT0_EXTRACT_PLAN`
- `BOOT0_VERIFY_EXTRACTED`
- `PLAN_PREFLIGHT`
- `PLAN_SCHEMA_TESTS`

### Tests

- `bootstrap/test_bootstrap_tools.py::test_bootstrap_scripts_parse`

### Positive vectors

- `BOOT0-VALID-ZIP-MANIFEST`

### Negative vectors

- `BOOT0-BAD-SIDECAR`
- `BOOT0-PATH-TRAVERSAL`
- `BOOT0-MANIFEST-MISMATCH`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All outputs are owned and content-addressed
- No authenticated discovery, provider call, or production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop if any exact input, file, symbol, schema, vector, command, or authority condition is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-BOOT0-T02 — Create isolated authoring workspace

Create the exact authoring root and copy the verified plan as immutable plan-input without source Git metadata, caches, or live evidence.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-BOOT0-T01`

### Preconditions

- Dependency V636-BOOT0-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json`

### Exact files

- `/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json`

### Exact symbols

- `bootstrap/create_authoring_workspace.py::create_authoring_workspace`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `BOOT0_CREATE_WORKSPACE`

### Tests

- `bootstrap/test_bootstrap_tools.py::test_bootstrap_scripts_parse`

### Positive vectors

- `BOOT0-NEW-EMPTY-AUTHORING-ROOT`

### Negative vectors

- `BOOT0-ROOT-ALREADY-EXISTS`
- `BOOT0-GIT-COPIED`
- `BOOT0-LIVE-EVIDENCE-COPIED`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All outputs are owned and content-addressed
- No authenticated discovery, provider call, or production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop if any exact input, file, symbol, schema, vector, command, or authority condition is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-BOOT0-T03 — Initialize authoring Git repository

Initialize a normal-history, no-remote Git repository for task-by-task authoring and record its actual initial commit/tree identity.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: DECLARED → MATERIALIZED.

### Dependencies

- `V636-BOOT0-T02`

### Preconditions

- Dependency V636-BOOT0-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json`

### Exact files

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json`

### Exact symbols

- `bootstrap/initialize_authoring_repository.py::initialize`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `BOOT0_INIT_AUTHORING_REPO`

### Tests

- `bootstrap/test_bootstrap_tools.py::test_bootstrap_scripts_parse`

### Positive vectors

- `BOOT0-ZERO-REMOTE-CLEAN-INITIAL-COMMIT`

### Negative vectors

- `BOOT0-REMOTE-PRESENT`
- `BOOT0-DIRTY-INITIAL-STATE`
- `BOOT0-GIT-ALREADY-EXISTS`

### Steps

- Read this card and docs/contracts/08-execution-and-ownership.md.
- Use the declared creation/modification ownership; never create an unowned consumer.
- Implement only this task obligation; run the exact registered commands.
- Record external evidence and stop; no commit or external mutation follows implicitly.

### Acceptance criteria

- All exact commands pass
- All outputs are owned and content-addressed
- No authenticated discovery, provider call, or production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop if any exact input, file, symbol, schema, vector, command, or authority condition is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
