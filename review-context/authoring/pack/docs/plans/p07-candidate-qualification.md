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

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json`
- `runtime/tools/full_verifier_config.py`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CURRENT_INPUTS.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stderr`

### Exact files

- `runtime/tests/release/test_candidate_command_registry.py`
- `runtime/tools/full_verifier_config.py`
- `runtime/tools/run_command_registry.py`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CURRENT_INPUTS.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/CAPTURE_V636_SUPPLEMENTAL_ENVIRONMENT.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_ALL_TESTS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_CRASH_HARNESS_AFTER_IMPLEMENTATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_PRODUCTION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/COMPILE_V636_P04_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/ISSUE_CURRENT_PHASE_PROOFS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_BOOTSTRAP_TS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_INHERITED_CANONICAL_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_NORMATIVE_BINDINGS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/QUALIFY_SUCCESSOR_REGISTRY_SELF_CHECK.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_RELEASE_TOOLS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_PY.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_SECURITY_TS.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_TS_V636_P04_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P01_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P02_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P03_T07.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P04_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T04.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T05.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T06.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T07.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P05_T08.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T01.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T02.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/TEST_V636_P06_T03.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DECLARATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VALIDATE_CURRENT_DESCENDANT_MIGRATION.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_REVIEW_AUTHORITY_BOOTSTRAP.stderr`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T01.stderr`

### Exact symbols

- `runtime/tools/run_command_registry.py::main`
- `runtime/tests/release/test_candidate_command_registry.py::test_candidate_mode_runs_every_required_command_once`

### Schema pointers

None; this task consumes previously created artifacts.

### Exact command IDs

- `VERIFY_EXTERNAL_AUTHORING_SOURCES`
- `VERIFY_V636_P07_T01`
- `ISSUE_CURRENT_PHASE_PROOFS`

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

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T01.json`

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
- pack/docs/registries/proof-coverage-matrix.v1.json
- runtime/vendor/hybrid-discovery-v6.3.6/docs/registries/proof-coverage-matrix.v1.json

### Outputs

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stderr`

### Exact files

- `runtime/tests/release/test_full_proof_coverage.py`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T02.stderr`

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

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T02.json`

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

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/CANDIDATE_QUALIFICATION.json`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stderr`

### Exact files

- `runtime/tools/build_candidate_qualification_receipt.py`
- `runtime/tests/release/test_candidate_qualification_receipt.py`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stdout`
- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/command-logs/VERIFY_V636_P07_T03.stderr`

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

- `/home/thenam176/betting-helper/authoring-evidence/part-b-one-ready-r12/V636-P07-T03.json`

### Rollback boundary

- Keep the failed candidate and evidence; resume only from the last accepted source inventory in a new isolated authoring root.
- Never delete or overwrite the sealed predecessor, baseline, review output, or production data.

Stop: Stop immediately if any exact input, path, symbol, schema, command, or authority assumption is unresolved.

Commit policy: NO_COMMIT_WITHOUT_SEPARATE_USER_AUTHORIZATION. Production authority: NONE.
