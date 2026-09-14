# P10 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P10-T01 — Issue Review A launch authorization and isolated workspace

Use external review authority to bind implementation-readiness role, exact sealed inputs, prompt/commands, one-use serial, expiry, isolated workspace, and allowed outputs.

Authority: EXTERNAL_REVIEW. Lifecycle applies to this task’s artifacts: SEALED → EXTERNAL_REVIEWED.

### Dependencies

- `V636-P09-T04`

### Preconditions

- Dependency V636-P09-T04 is ACCEPTED
- Human HOST_REVIEW_AUTHORITY_BOOTSTRAP is completed and verified; it is an external prerequisite, not authority granted to this task.

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/review-authorizations/hybrid-discovery-v6.3.6/review-a.authorization.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/workspace-attestation.json`

### Exact files

- `/home/thenam176/betting-helper/review-authorizations/hybrid-discovery-v6.3.6/review-a.authorization.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/workspace-attestation.json`

### Exact symbols

- `runtime/tools/issue_review_launch_authorization.py::main`
- `runtime/tools/prepare_review_workspace.py::main`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P10_T01`
- `REVIEW_A_PREPARE`
- `REVIEW_A_MECHANICAL`

### Tests

- `runtime/tests/review/test_review_launch_authorization.py`
- `runtime/tests/review/test_review_workspace_isolation.py`

### Positive vectors

- `V636-P10-T01-POS-01`

### Negative vectors

- `V636-P10-T01-NEG-01`

### Steps

- Consume only the sealed inputs and previously qualified review tools.
- Run the exact launch/prepare/execute/finalize/aggregate commands listed for this task.
- Await the explicit host authorization, independent reviewer result and human fresh-session attestation where required; do not fabricate them.
- Write only the declared external outputs; never edit source or sealed files.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P10-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P10-T02 — Issue Review B launch authorization and isolated workspace

Use a distinct role, serial, workspace, output root, prompt and command registry; exclude Review A output and authoring workspace.

Authority: EXTERNAL_REVIEW. Lifecycle applies to this task’s artifacts: SEALED → EXTERNAL_REVIEWED.

### Dependencies

- `V636-P09-T04`

### Preconditions

- Dependency V636-P09-T04 is ACCEPTED
- Human HOST_REVIEW_AUTHORITY_BOOTSTRAP is completed and verified; it is an external prerequisite, not authority granted to this task.

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/review-authorizations/hybrid-discovery-v6.3.6/review-b.authorization.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/workspace-attestation.json`

### Exact files

- `/home/thenam176/betting-helper/review-authorizations/hybrid-discovery-v6.3.6/review-b.authorization.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/workspace-attestation.json`

### Exact symbols

- `runtime/tools/issue_review_launch_authorization.py::main`
- `runtime/tools/prepare_review_workspace.py::main`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P10_T02`
- `REVIEW_B_PREPARE`
- `REVIEW_B_MECHANICAL`

### Tests

- `runtime/tests/review/test_review_launch_authorization.py`
- `runtime/tests/review/test_review_workspace_isolation.py`

### Positive vectors

- `V636-P10-T02-POS-01`

### Negative vectors

- `V636-P10-T02-NEG-01`

### Steps

- Consume only the sealed inputs and previously qualified review tools.
- Run the exact launch/prepare/execute/finalize/aggregate commands listed for this task.
- Await the explicit host authorization, independent reviewer result and human fresh-session attestation where required; do not fabricate them.
- Write only the declared external outputs; never edit source or sealed files.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P10-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P10-T03 — Finalize independent review execution receipts

Verify each review used its authorized workspace, exact inputs and commands, changed only allowed outputs, completed before expiry, and includes human fresh-session attestation.

Authority: EXTERNAL_REVIEW. Lifecycle applies to this task’s artifacts: SEALED → EXTERNAL_REVIEWED.

### Dependencies

- `V636-P10-T01`
- `V636-P10-T02`

### Preconditions

- Dependency V636-P10-T01 is ACCEPTED
- Dependency V636-P10-T02 is ACCEPTED
- Human HOST_REVIEW_AUTHORITY_BOOTSTRAP is completed and verified; it is an external prerequisite, not authority granted to this task.

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/result.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/execution-receipt.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/result.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/execution-receipt.json`

### Exact files

- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/result.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-a/execution-receipt.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/result.json`
- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/review-b/execution-receipt.json`

### Exact symbols

- `runtime/tools/finalize_review.py::main`
- `runtime/src/moj_discovery/review_authorization.py::verify_review_execution_receipt`

### Schema pointers

- `pack/docs/schemas/review-execution-receipt.schema.json#/$defs/ReviewExecutionReceipt`
- `pack/docs/schemas/review-result.schema.json#/$defs/ReviewResult`

### Exact command IDs

- `FINALIZE_A_V636_P10_T03`
- `FINALIZE_B_V636_P10_T03`

### Tests

- `runtime/tests/review/test_review_workspace_isolation.py`

### Positive vectors

- `V636-P10-T03-POS-01`

### Negative vectors

- `V636-P10-T03-NEG-01`

### Steps

- Consume only the sealed inputs and previously qualified review tools.
- Run the exact launch/prepare/execute/finalize/aggregate commands listed for this task.
- Await the explicit host authorization, independent reviewer result and human fresh-session attestation where required; do not fabricate them.
- Write only the declared external outputs; never edit source or sealed files.

### Acceptance criteria

- Review roles, serials, workspaces, outputs, and runs are distinct
- Both inputs bind identical sealed pack and baseline
- Human fresh-session attestation is present and explicitly procedural

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P10-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P10-T04 — Aggregate independent reviews and issue handoff verdict

Deterministically require Review A PASS, Review B PASS, valid independent receipts, no blocking finding, and production authority NONE before implementation readiness may be YES.

Authority: EXTERNAL_REVIEW. Lifecycle applies to this task’s artifacts: EXTERNAL_REVIEWED → EXTERNAL_REVIEWED.

### Dependencies

- `V636-P10-T03`

### Preconditions

- Dependency V636-P10-T03 is ACCEPTED
- Human HOST_REVIEW_AUTHORITY_BOOTSTRAP is completed and verified; it is an external prerequisite, not authority granted to this task.

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/aggregate/result.json`

### Exact files

- `/home/thenam176/betting-helper/reviews/hybrid-discovery-v6.3.6/aggregate/result.json`

### Exact symbols

- `runtime/tools/aggregate_reviews.py::main`
- `runtime/src/moj_discovery/review_aggregation.py::aggregate_independent_reviews`

### Schema pointers

- `pack/docs/schemas/review-result.schema.json#/$defs/ReviewResult`

### Exact command IDs

- `VERIFY_V636_P10_T04`

### Tests

- `runtime/tests/review/test_review_aggregation_and_self_review.py`

### Positive vectors

- `V636-P10-T04-POS-01`

### Negative vectors

- `V636-P10-T04-NEG-01`

### Steps

- Consume only the sealed inputs and previously qualified review tools.
- Run the exact launch/prepare/execute/finalize/aggregate commands listed for this task.
- Await the explicit host authorization, independent reviewer result and human fresh-session attestation where required; do not fabricate them.
- Write only the declared external outputs; never edit source or sealed files.

### Acceptance criteria

- Incomplete cybersecurity review yields HOLD
- READY YES with SAFE_TO_FREEZE_SCOPE0 NO is representable
- AUTHORIZED_PRODUCTION_PHASES remains NONE

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P10-T04.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
