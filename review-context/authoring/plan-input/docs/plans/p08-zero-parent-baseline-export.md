# P08 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P08-T01 — Export deterministic final runtime candidate

Export only the exact P07-qualified source/build inventory bytes and modes from the authoring runtime working tree into a fresh destination; verify each hash before and after copy. Authoring HEAD is provenance only and is never substituted for current qualified content.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P07-T03`

### Preconditions

- Dependency V636-P07-T03 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tools/export_zero_parent_candidate.py`
- `runtime/tests/release/test_zero_parent_export.py`

### Exact symbols

- `runtime/tools/export_zero_parent_candidate.py::export_zero_parent_candidate`
- `runtime/tests/release/test_zero_parent_export.py::test_export_contains_only_candidate_inventory_and_exact_modes`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P08_T01`

### Tests

- `runtime/tests/release/test_zero_parent_export.py`

### Positive vectors

- `V636-P08-T01-POS-01`

### Negative vectors

- `V636-P08-T01-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P08-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P08-T02 — Create delivered zero-parent Git baseline

Initialize the final runtime as a no-remote repository and create one zero-parent commit from exported bytes.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P08-T01`

### Preconditions

- Dependency V636-P08-T01 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

None; this task consumes previously created artifacts.

### Exact files

- `runtime/tools/create_zero_parent_repository.py`
- `runtime/tests/release/test_zero_parent_repository.py`

### Exact symbols

- `runtime/tools/create_zero_parent_repository.py::create_zero_parent_repository`
- `runtime/tests/release/test_zero_parent_repository.py::test_delivered_repository_has_one_zero_parent_commit_and_no_remote`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_V636_P08_T02`

### Tests

- `runtime/tests/release/test_zero_parent_repository.py`

### Positive vectors

- `V636-P08-T02-POS-01`

### Negative vectors

- `V636-P08-T02-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- All exact commands pass
- All declared outputs are content-addressed
- No production authority is introduced
- Stage precisely the qualified export inventory, explicitly including its ignored .test-build and dist files; never force-add dependency environments or arbitrary untracked files. Final tracked paths and hashes must equal that inventory before creating the single zero-parent commit.

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P08-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P08-T03 — Replay committed baseline in place and issue REPO0 receipt

Run POST_COMMIT_BASELINE directly in the delivered Git repository and record actual commit/tree/file-root/toolchain/lock/vendor/command roots.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P08-T02`

### Preconditions

- Dependency V636-P08-T02 is ACCEPTED

### Inputs

- Verified immutable plan-input and the task-specific registered command inputs

### Outputs

- `pack/docs/receipts/repo0-baseline-receipt.json`

### Exact files

- `runtime/tools/qualify_zero_parent_baseline.py`
- `runtime/tests/release/test_post_commit_baseline.py`
- `pack/docs/receipts/repo0-baseline-receipt.json`

### Exact symbols

- `runtime/tools/qualify_zero_parent_baseline.py::qualify_zero_parent_baseline`
- `runtime/tests/release/test_post_commit_baseline.py::test_full_registry_replays_in_actual_committed_repository`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `BASELINE_INSTALL_PYTHON`
- `BASELINE_INSTALL_NODE`
- `VERIFY_V636_P08_T03`

### Tests

- `runtime/tests/release/test_post_commit_baseline.py`

### Positive vectors

- `V636-P08-T03-POS-01`

### Negative vectors

- `V636-P08-T03-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- No temporary Git-less overlay
- Working tree clean
- HEAD/tree/file root and command root match receipt

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/V636-P08-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
