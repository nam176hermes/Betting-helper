# P08 task contracts

Generated from docs/tasks/task-manifest.v6.3.6.json. Follow dependency order, including the recurring MIG0 tasks. Read docs/contracts/00–09 before executing.

## V636-P08-T01 — Preflight descendant repository qualification

Read-only preflight of the current descendant checkout, candidate, config, inventories and audited ancestry.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P07-T03`

### Preconditions

- Dependency V636-P07-T03 is ACCEPTED

### Inputs

- pack/docs/configs/full-verifier-controller.v2.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/environment-aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P03-T07.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P04-T04.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T01.json`
- `runtime/tests/release/test_descendant_repository_qualification.py`

### Exact files

- `runtime/tests/release/test_descendant_repository_qualification.py`
- `runtime/tools/qualify_descendant_repository.py`

### Exact symbols

- `runtime/tools/qualify_descendant_repository.py::main`

### Schema pointers

- `pack/docs/schemas/descendant-repository-qualification-receipt.schema.json#/$defs/DescendantRepositoryQualificationReceipt`

### Exact command IDs

- `VERIFY_V636_P08_T01`

### Tests

- `runtime/tests/release/test_descendant_repository_qualification.py`

### Positive vectors

- `V636-P08-T01-POS-01`

### Negative vectors

- `V636-P08-T01-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- Audited ancestor, current HEAD/tree, candidate and configured evidence validate read-only
- No repository, receipt or tracked file is written
- Production authority remains NONE

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T01.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P08-T02 — Issue descendant repository qualification receipt

Exclusively issue the current descendant receipt without creating a repository, baseline or commit.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P08-T01`

### Preconditions

- Dependency V636-P08-T01 is ACCEPTED

### Inputs

- pack/docs/configs/full-verifier-controller.v2.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/environment-aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P03-T07.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P04-T04.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T02.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/DESCENDANT_REPOSITORY_QUALIFICATION.json`

### Exact files

- `runtime/tools/qualify_descendant_repository.py`
- `runtime/tests/release/test_descendant_repository_qualification.py`

### Exact symbols

- `runtime/tools/qualify_descendant_repository.py::main`

### Schema pointers

- `pack/docs/schemas/descendant-repository-qualification-receipt.schema.json#/$defs/DescendantRepositoryQualificationReceipt`

### Exact command IDs

- `VERIFY_V636_P08_T02`

### Tests

- `runtime/tests/release/test_descendant_repository_qualification.py`

### Positive vectors

- `V636-P08-T02-POS-01`

### Negative vectors

- `V636-P08-T02-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- Exactly one exclusive descendant receipt is issued from the passing preflight
- Repository HEAD, tree and status are unchanged across issuance
- Production authority remains NONE

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T02.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.

## V636-P08-T03 — Check descendant repository qualification receipt

Check-only revalidation of the immutable descendant receipt against the current source contract.

Authority: PLAN_AUTHORING. Lifecycle applies to this task’s artifacts: QUALIFIED → QUALIFIED.

### Dependencies

- `V636-P08-T02`

### Preconditions

- Dependency V636-P08-T02 is ACCEPTED

### Inputs

- pack/docs/configs/full-verifier-controller.v2.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/full-repair/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/environment-aggregate.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/environment/inventory.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P03-T07.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P04-T04.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json
- /home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T03.json`

### Exact files

- `runtime/tools/qualify_descendant_repository.py`
- `runtime/tests/release/test_descendant_repository_qualification.py`

### Exact symbols

- `runtime/tools/qualify_descendant_repository.py::main`

### Schema pointers

- `pack/docs/schemas/descendant-repository-qualification-receipt.schema.json#/$defs/DescendantRepositoryQualificationReceipt`

### Exact command IDs

- `BASELINE_INSTALL_PYTHON`
- `BASELINE_INSTALL_NODE`
- `VERIFY_V636_P08_T03`

### Tests

- `runtime/tests/release/test_descendant_repository_qualification.py`

### Positive vectors

- `V636-P08-T03-POS-01`

### Negative vectors

- `V636-P08-T03-NEG-01`

### Steps

- Consume the already qualified tools; do not edit source, tests, configs, locks or normative bytes.
- Execute the registered operation against its exact roots.
- Write the external evidence record and stop.

### Acceptance criteria

- Check-only recomputation matches every bound receipt field
- Missing, stale, mixed-kind or aliased inputs fail closed
- Production authority remains NONE

### External evidence

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P08-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
