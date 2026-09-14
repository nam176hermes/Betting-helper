# Hybrid Discovery v6.3.6 Bootstrap and Rebind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a fresh, local-only v6.3.6 authoring candidate whose evidence and contracts cannot be confused with held v6.3.5 execution evidence.

**Architecture:** The sealed v6.3.5 ZIP is an immutable source input. A new v6.3.6 workspace owns a separately generated execution manifest, command registry, pack, runtime paths, and evidence directory; rebind checks reject any active v6.3.5 identifier or path. The bootstrap tasks then create evidence only from commands observed in this workspace.

**Tech Stack:** Python 3.12 standard library, pinned `uv`/`pnpm` toolchains already declared by the source plan, JSON, SHA-256, Git local-only.

**Spec:** `hybrid-discovery-v6.3.6-repair-plan.md`; `plan-input/hybrid-discovery-v6.3.5-authoritative-design-plan/IMPLEMENTATION_PLAN_V6_3_5.md`

## Global Constraints

- Preserve `hybrid-discovery-v6.3.5-authoring/` and `authoring-evidence/hybrid-discovery-v6.3.5/` byte-for-byte; neither is an input candidate.
- Create only `hybrid-discovery-v6.3.6-authoring/`, `authoring-evidence/hybrid-discovery-v6.3.6/`, and `discovery-runtime-v6.3.6/` inside this checkout.
- Every v6.3.6 task and receipt uses `V636-*`, `PLAN_AUTHORING`, and `authorized_production_phases=NONE`.
- Do not use providers, authenticated browser access, real Chrome profiles, production, remote Git, commits, or installs that are not in a registered command.
- A receipt is accepted only when it is a regular non-symlink JSON file with `result=PASS`, the exact predecessor digest, recorded argv, and stdout/stderr/output hashes.
- `TEST_SECURITY_PY` runs only v6.3.6-owned security qualification files; the three inherited intentional-red tests remain present, unmodified, and excluded by exact path.
- `repo0-baseline-receipt/v2` binds the delivered commit/tree/working tree, candidate evidence, baseline registry, locks, toolchains, vendor root, and normative source-map/set roots; `--check-only` reads no authoring root.
- Do not commit without a separate explicit authorization.

---

### Task 1: Create the v6.3.6 successor-contract generator

**Files:**
- Create: `hybrid-discovery-v6.3.6-authoring/authoring-tools/rebind_successor.py`
- Create: `hybrid-discovery-v6.3.6-authoring/authoring-tests/test_rebind_successor.py`
- Create: `hybrid-discovery-v6.3.6-authoring/plan-input/docs/tasks/task-manifest.v6.3.6.json`
- Create: `hybrid-discovery-v6.3.6-authoring/plan-input/docs/registries/task-command-registry.v6.3.6.json`
- Modify: `hybrid-discovery-v6.3.6-authoring/plan-input/plan-manifest.json`
- Test: `hybrid-discovery-v6.3.6-authoring/authoring-tests/test_rebind_successor.py`

**Interfaces:**
- Consumes: an extracted, manifest-verified v6.3.5 plan directory and its task manifest.
- Produces: `rebind_successor(source: Path, destination: Path) -> None`, which writes a v6.3.6 task manifest and registry with exactly matching task/command cardinalities and no active `V635-` or `v6.3.5` token.

- [ ] **Step 1: Write the failing successor-rebind test**

```python
def test_rebind_successor_rejects_active_v635_references(tmp_path: Path) -> None:
    source = tmp_path / "source"; destination = tmp_path / "destination"
    (source / "docs/tasks").mkdir(parents=True)
    (source / "docs/tasks/task-manifest.v6.3.5.json").write_text(
        json.dumps({"declared_task_count": 1, "tasks": [{"task_id": "V635-P01-T02"}]})
    )
    rebind_successor(source, destination)
    rendered = (destination / "docs/tasks/task-manifest.v6.3.6.json").read_text()
    assert "V636-P01-T02" in rendered
    assert "V635-" not in rendered and "v6.3.5" not in rendered
```

- [ ] **Step 2: Run the test and verify the expected RED failure**

Run: `cd hybrid-discovery-v6.3.6-authoring && python3.12 -B -m pytest -q authoring-tests/test_rebind_successor.py`

Expected: FAIL because `rebind_successor` does not exist.

- [ ] **Step 3: Implement the narrow rebind helper**

```python
def rebind_successor(source: Path, destination: Path) -> None:
    data = json.loads((source / "docs/tasks/task-manifest.v6.3.5.json").read_text())
    text = json.dumps(data, sort_keys=True)
    text = text.replace("V635-", "V636-").replace("v6.3.5", "v6.3.6")
    if "V635-" in text or "v6.3.5" in text:
        raise ValueError("E_V636_REBIND")
    target = destination / "docs/tasks/task-manifest.v6.3.6.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n")
```

Expand the helper only to rebind the named manifest, registries, exact absolute roots, and generated task cards; reject unresolved references rather than guessing replacements.

- [ ] **Step 4: Run the focused test and source-plan checker**

Run: `cd hybrid-discovery-v6.3.6-authoring && python3.12 -B -m pytest -q authoring-tests/test_rebind_successor.py && python3.12 -B plan-input/plan_tools/check_plan.py --root plan-input`

Expected: PASS; v6.3.5 source input still validates unchanged.

### Task 2: Bootstrap a new isolated v6.3.6 workspace and evidence root

**Files:**
- Create: `hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T01.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T02.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-BOOT0-T03.json`
- Test: `hybrid-discovery-v6.3.6-authoring/plan-input/bootstrap/test_bootstrap_tools.py`

**Interfaces:**
- Consumes: `inputs/hybrid-discovery-v6.3.5-authoritative-design-plan.zip` and its `.sha256` sidecar.
- Produces: immutable `plan-input/` provenance copy plus receipt records whose `predecessor_sha256` is empty only for T01 and equals the previous receipt digest thereafter.

- [ ] **Step 1: Write a failing receipt-shape test**

```python
def test_v636_receipt_requires_exact_predecessor_hash(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="E_V636_EVIDENCE"):
        validate_receipt({"result": "PASS", "predecessor_sha256": "not-a-digest"}, None)
```

- [ ] **Step 2: Run it and verify RED**

Run: `cd hybrid-discovery-v6.3.6-authoring && python3.12 -B -m pytest -q authoring-tests/test_evidence_chain.py`

Expected: FAIL because the validator has not been created.

- [ ] **Step 3: Implement `validate_receipt` and execute BOOT0-T01 through T03**

```python
def validate_receipt(record: dict[str, object], previous: bytes | None) -> None:
    if record.get("result") != "PASS" or record.get("authority") != "PLAN_AUTHORING":
        raise ValueError("E_V636_EVIDENCE")
    expected = "" if previous is None else hashlib.sha256(previous).hexdigest()
    if record.get("predecessor_sha256") != expected:
        raise ValueError("E_V636_EVIDENCE")
```

Use the source plan's `extract_plan.py`, `verify_extracted_plan.py`, and `create_authoring_workspace.py` only against new paths. Record the exact argv and observed stream/output hashes after each command; do not reconstruct a receipt.

- [ ] **Step 4: Verify the bootstrap chain**

Run: `cd hybrid-discovery-v6.3.6-authoring && python3.12 -B -m pytest -q authoring-tests/test_evidence_chain.py plan-input/bootstrap/test_bootstrap_tools.py`

Expected: PASS; the three v6.3.6 receipt files are regular JSON files and chain in order.

### Task 3: Rebind migration contracts and make P01-T02 fail closed

**Files:**
- Create: `hybrid-discovery-v6.3.6-authoring/runtime/tools/validate_evidence_chain.py`
- Create: `hybrid-discovery-v6.3.6-authoring/runtime/tests/materialization/test_declared_stubs.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/runtime/tools/materialize_declared_stubs.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/pack/docs/registries/task-command-registry.v6.3.6.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-MIG0-T01.json` through `V636-MIG0-T06.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T01.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T02.json`
- Test: `hybrid-discovery-v6.3.6-authoring/runtime/tests/materialization/test_declared_stubs.py`

**Interfaces:**
- Consumes: the Task 2 evidence chain and the v6.3.6 task manifest.
- Produces: `validate_chain(evidence_root: Path, manifest: dict[str, object]) -> None` and `materialize_declared_stubs(root: Path, check: bool = False) -> list[str]` with the exact `E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T02` behavior.

- [ ] **Step 1: Write the failing P01-T02 regression test**

```python
def test_declared_stubs_reject_missing_link_and_wrong_task_error(tmp_path: Path) -> None:
    runtime = prepare_v636_runtime(tmp_path)
    materialize_declared_stubs(runtime)
    stub = runtime / "src/future.py"
    assert "E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T02" in stub.read_text()
    stub.unlink(); assert materialize_declared_stubs(runtime, check=True) == [
        "E_CONTRACT_STUBS:MISSING:runtime/src/future.py"
    ]
    stub.symlink_to("../extension/src/future.ts")
    assert materialize_declared_stubs(runtime, check=True) == [
        "E_CONTRACT_STUBS:FILE:runtime/src/future.py"
    ]
```

- [ ] **Step 2: Run it and verify RED**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen pytest -q tests/materialization/test_declared_stubs.py`

Expected: FAIL because the copied v6.3.5 task identifier is still active.

- [ ] **Step 3: Implement the v6.3.6-only stub and chain rules**

```python
TASK_ID = "V636-P01-T02"
STUB_ERROR = "E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T02"
```

Require every predecessor receipt to be a non-symlink regular file, JSON object, `PASS`, `PLAN_AUTHORING`, `NONE`, and hash-linked to its immediate predecessor. Build `TEST_SECURITY_PY` from an explicit v6.3.6-owned list; assert the three inherited intentional-red paths are materialized but absent from that argv.

- [ ] **Step 4: Run the targeted command and strict verifier**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen pytest -q tests/materialization/test_declared_stubs.py && uv run --frozen python tools/validate_evidence_chain.py --evidence-root ../../authoring-evidence/hybrid-discovery-v6.3.6 --manifest ../pack/docs/tasks/task-manifest.v6.3.6.json`

Expected: PASS only after MIG0-T01 through P01-T02 receipts have been observed and hash-linked.

### Task 4: Close the v2 REPO0 and review boundary before P06

**Files:**
- Create: `hybrid-discovery-v6.3.6-authoring/runtime/tests/release/test_post_commit_baseline.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/runtime/tools/qualify_zero_parent_baseline.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/runtime/tools/assemble_review_pack.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/runtime/tools/seal_review_pack.py`
- Modify: `hybrid-discovery-v6.3.6-authoring/runtime/tools/issue_review_launch_authorization.py`
- Create: `hybrid-discovery-v6.3.6-authoring/pack/docs/receipts/repo0-baseline-receipt.schema.json`
- Test: `hybrid-discovery-v6.3.6-authoring/runtime/tests/release/test_post_commit_baseline.py`

**Interfaces:**
- Consumes: accepted v6.3.6 candidate evidence and a local, zero-parent runtime Git repository created only at V636-P08-T02.
- Produces: `verify_zero_parent_baseline(root: Path, receipt_path: Path, *, pack: Path | None = None) -> dict[str, object]` where `--check-only` recomputes only final runtime identity and normative equality.

- [ ] **Step 1: Write the failing isolated-review test**

```python
def test_check_only_does_not_read_authoring_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V636_AUTHORING_ROOT", str(tmp_path / "forbidden"))
    verify_zero_parent_baseline(delivered_root, receipt, pack=pack)
```

- [ ] **Step 2: Run it and verify RED**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen pytest -q tests/release/test_post_commit_baseline.py`

Expected: FAIL because current v6.3.5-derived helpers retain authoring-root dependencies.

- [ ] **Step 3: Implement the closed v2 receipt**

```python
required = {
    "baseline_commit", "baseline_tree", "baseline_file_root_sha256",
    "candidate_qualification_sha256", "candidate_command_evidence_sha256",
    "baseline_registry_sha256", "toolchain_versions", "lockfile_hashes",
    "vendor_root_sha256", "normative_source_map_sha256", "normative_source_set_root",
}
```

Bind all listed values to the delivered root. Do not read authoring paths in `--check-only`; reject a receipt with extra/missing fields, non-digests, a non-clean tree, or production authority.

- [ ] **Step 4: Run release-boundary checks**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen pytest -q tests/release/test_post_commit_baseline.py tests/review/test_review_a_runner.py`

Expected: PASS while the review runner remains check-only and local.

### Task 5: Execute the remaining v6.3.6 task graph only from accepted evidence

**Files:**
- Modify: `hybrid-discovery-v6.3.6-authoring/pack/docs/tasks/task-manifest.v6.3.6.json`
- Modify: `hybrid-discovery-v6.3.6-authoring/pack/docs/registries/task-command-registry.v6.3.6.json`
- Create: `authoring-evidence/hybrid-discovery-v6.3.6/V636-P01-T03.json` through `V636-P10-T04.json`
- Test: exact tests registered by each current `V636-*` task card.

**Interfaces:**
- Consumes: the strict evidence verifier and the v6.3.6 registry.
- Produces: one observed receipt per dependency-ordered task, with no task starting before its immediate predecessor is accepted.

- [ ] **Step 1: Run the verifier before every task**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen python tools/validate_evidence_chain.py --evidence-root ../../authoring-evidence/hybrid-discovery-v6.3.6 --manifest ../pack/docs/tasks/task-manifest.v6.3.6.json`

Expected: PASS only for the predecessor chain of the next task.

- [ ] **Step 2: Run the next task's exact registered test before implementation**

Run:

```bash
tasks=(
  V636-P01-T03 V636-P01-T04 V636-P01-T05 V636-P01-T06 V636-MIG0-T07
  V636-P02-T01 V636-P02-T02 V636-P02-T03
  V636-P03-T01 V636-P03-T02 V636-P03-T03 V636-P03-T04 V636-P03-T05 V636-P03-T06 V636-P03-T07
  V636-P04-T01 V636-P04-T02 V636-P04-T03 V636-P04-T04
  V636-P05-T01 V636-P05-T02 V636-P05-T03 V636-P05-T04 V636-P05-T05 V636-P05-T06 V636-P05-T07 V636-P05-T08 V636-P05-T09
  V636-MIG0-T08 V636-P06-T01 V636-P06-T02 V636-P06-T03
  V636-P07-T01 V636-P07-T02 V636-P07-T03
  V636-P08-T01 V636-P08-T02 V636-P08-T03
  V636-P09-T01 V636-P09-T02 V636-P09-T03 V636-P09-T04
  V636-P10-T01 V636-P10-T02 V636-P10-T03 V636-P10-T04
)
for task in "${tasks[@]}"; do
  uv run --frozen python tools/run_command_registry.py --task "$task" --tests-first || exit $?
done
```

Expected: the declared failing contract state, never a missing-path/import/configuration error.

- [ ] **Step 3: Make the minimal task-owned change and rerun its registered argv**

Run:

```bash
tasks=(
  V636-P01-T03 V636-P01-T04 V636-P01-T05 V636-P01-T06 V636-MIG0-T07
  V636-P02-T01 V636-P02-T02 V636-P02-T03
  V636-P03-T01 V636-P03-T02 V636-P03-T03 V636-P03-T04 V636-P03-T05 V636-P03-T06 V636-P03-T07
  V636-P04-T01 V636-P04-T02 V636-P04-T03 V636-P04-T04
  V636-P05-T01 V636-P05-T02 V636-P05-T03 V636-P05-T04 V636-P05-T05 V636-P05-T06 V636-P05-T07 V636-P05-T08 V636-P05-T09
  V636-MIG0-T08 V636-P06-T01 V636-P06-T02 V636-P06-T03
  V636-P07-T01 V636-P07-T02 V636-P07-T03
  V636-P08-T01 V636-P08-T02 V636-P08-T03
  V636-P09-T01 V636-P09-T02 V636-P09-T03 V636-P09-T04
  V636-P10-T01 V636-P10-T02 V636-P10-T03 V636-P10-T04
)
for task in "${tasks[@]}"; do
  uv run --frozen python tools/run_command_registry.py --task "$task" || exit $?
done
```

Expected: exit code exactly matching the registry entry; record hashes from this run only.

- [ ] **Step 4: Write and verify the receipt before advancing**

Run: `cd hybrid-discovery-v6.3.6-authoring/runtime && uv run --frozen python tools/validate_evidence_chain.py --evidence-root ../../authoring-evidence/hybrid-discovery-v6.3.6 --manifest ../pack/docs/tasks/task-manifest.v6.3.6.json`

Expected: PASS with exactly one new accepted receipt; otherwise stop.

## Self-Review

- Coverage: Tasks 1-3 implement the required fresh v6.3.6 root, independent evidence chain, P01-T02 stub proof, and security allowlist. Task 4 implements the P08 v2 receipt and Review A isolation. Task 5 makes all remaining P01-P10 execution dependent on observed predecessor evidence.
- Placeholder scan: no deferred code markers or unspecified task identifiers are used.
- Consistency: all new execution IDs use `V636-*`; source v6.3.5 artifacts remain immutable provenance input.
