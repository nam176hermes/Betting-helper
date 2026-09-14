# Codex workflow: load on demand

This is operating guidance, not a source pack, readiness receipt, model switch,
or authorization. Existing task contracts and nested instructions still govern.

## Start and resume

1. Identify the requested repository/candidate and read applicable instructions.
   Record cwd, HEAD, dirty paths, task ID, scope, and authority. The outer workspace
   is not a substitute for the nested repository's Git state.
2. Read the relevant source, callers, nearest tests, and exact command definition.
   Use architecture/contract docs only where needed; avoid recursive workspace scans.
3. Keep this verified context in the current session. Resume from the last handoff,
   checking revision, relevant dirty bytes, prerequisites, and prior evidence bindings.
   Invalidate changed facts; do not replay the entire task history.
4. Treat local memory and old reports as pointers. Neither an older PASS nor a
   newer directory establishes current readiness or authorization.

Useful entry points, relative to the selected runtime:

| Work | Entry points |
| --- | --- |
| Portable/full validation | `README.md`, `tools/verify_local.py`, `tests/repairs/test_portable_verification.py` |
| Governed commands | `task-command-registry.json`, `tools/run_command_registry.py`; registry cwd may name another runtime |
| Python behavior | `src/`, `moj_discovery/`, nearest family in `tests/` |
| Extension behavior | `extension/src/`, `extension/test/`; compile before Node execution |
| Crash/recovery/clock qualification | Relevant `tools/run_*` runner, `tests/durability/`, `tests/clock/`, `tests/repairs/` |
| Formal evidence | `docs/repairs/external-evidence-index.md`, selected source-pack contracts and review configs |
| Authoring changes | Selected authoring checkout's `authoring-tools/`, `authoring-tests/`, and exact governed task |

## Task classes and routing

These are recommendations for supported task settings, not automatic overrides.
Respect explicit user model choices and tool restrictions. Do not create another
agent or task just to change models. Recheck the host catalog if a setting is rejected.

| Class / task | Suggested model | Reasoning | Process |
| --- | --- | --- | --- |
| A: deterministic docs, formatting, small rename | GPT-5.6 Luna | low | Inspect, edit, focused check; no delegation or plan artifact |
| B: isolated implementation or ordinary defect | GPT-5.6 Terra | medium | Focused inspection; concise plan only if helpful |
| B: bounded repository reconnaissance | GPT-5.6 Terra | low | Exact paths and graph query when useful; stop when interfaces are known |
| B: implementation spanning several files within one subsystem | GPT-5.6 Sol | medium | Stable interfaces, relevant callers and tests |
| C: ambiguous plan or cross-subsystem change | GPT-6 Astra | medium | Resolve contracts, dependency plan, review where valuable, freeze decisions |
| C: architecture or difficult root cause | GPT-6 Astra | high | Evidence-led hypotheses; reduce effort once decisions become mechanical |
| D: credentials, authority, persistence, recovery, clocks, concurrency, financial execution | GPT-6 Astra | high | Strong invariants, negative tests, independent risk review where required/useful |
| C/D: final adversarial review | GPT-6 Astra | high | Review changed behavior and failure modes; retain formal A/B requirements |

The desktop catalog inspected on 2026-09-08 supports Astra `low`, `medium`,
`high`, `xhigh`, `max`, and `ultra`. Start from task risk, not the largest value.
Use xhigh only for a concrete unresolved difficult decision; max/ultra require
specific justification. No quota multiplier or savings percentage is assumed.
The desktop and WSL CLI may have different defaults; confirm the task's actual setting.

## Delegation and handoff

Ordinary target: one coordinator plus zero to two concurrent workers, only when
delegation is authorized and each worker can make independent useful progress.
More workers require a concrete dependency/ownership reason. This is not a cap
on mandated formal review roles and is not an automatic dispatch instruction.

Do not delegate mechanical work, the coordinator's already-resolved question,
overlapping writes, or work waiting on another worker's contract. Reuse a suitable
existing worker for a bounded follow-up. The coordinator owns integration and checks
the combined state. A worker must not add workers without an explicit assignment.

Use a compact brief, preferably referenced by path for long-lived complex work:

```text
TASK / EXPECTED OUTPUT
SCOPE / TARGET CWD / HEAD / RELEVANT DIRTY STATE
FILES / OWNERSHIP
CONSTRAINTS / AUTHORITY / REQUIRED REVIEW ROLE
KNOWN FACTS / EVIDENCE PATHS / INPUT BINDINGS
DECISIONS / OPEN QUESTIONS
CHECKS ALREADY RUN / EXIT STATUS / REQUIRED REMAINING CHECKS
DO NOT RE-READ: verified unchanged context (refresh if inputs changed)
```

Return findings as severity, file:line, evidence, impact, and action; include
changed files, exact checks/exits, and blockers. Full-history inheritance is rarely
needed. Share implementation reconnaissance, but give formal independent reviewers
only their authorized immutable inputs; do not share peer verdicts or replace fresh
human role attestations with worker output. See source-pack
`docs/contracts/05-reviewer-independence.md` for the binding A/B requirements.

Use blocking completion tools within host limits; avoid repeated status requests
or messages when there is no decision or changed state. A long-running test needs
its completion result, not another invocation.

## Verification selection

The inspected v6.3.6 runtime pins Node 22.23.0, pnpm 10.33.2, Python 3.12.3,
uv 0.11.7, and TypeScript 6.0.2. Read the selected checkout's manifests if they change.
With locked dependencies already installed, run commands from that runtime:

```bash
uv run --frozen --offline python -m pytest -q tests/repairs/test_ci_profile_contract.py
pnpm typecheck
pnpm lint
uv run --frozen --offline python tools/verify_local.py --profile portable
```

The first command is an example of focused selection, not a universal test gate.
For Python changes use the existing Ruff/mypy configuration and affected tests;
for extension changes use package scripts, compile the test target, and execute
the named Node tests. No dependency installation is implicit in this guidance.

Escalation: changed behavior/counterexample → related callers/tests → affected
subsystem → required lint/type/build checks → integration/full qualification when
required. Portable already compiles tests and runs registry self-check; do not
repeat those immediately on identical inputs without a contract or diagnostic reason.
Portable executes an explicit subset and collects other repairs; collection is not
execution. Tests of the portable verifier may invoke it again intentionally.

Broader affected-suite execution is mandatory for shared infrastructure, schema or
dependency changes, concurrency, security/authority, persistence/recovery, and final
integration/release qualification. Run every check mandated by the relevant contract,
including independent negative/crash vectors. Do not convert intentional-red tests
to green, mark missing executions as PASS, or shrink a required matrix to save quota.

Full qualification remains the controller's job with explicit pack, evidence,
authoring tests, caches, browser binding, and authority. The inspected executable
requires `--profile full --config <source-owned-config-path>`; its old individual
`--pack`/cache/browser flags return HOLD. The runtime README still shows that older
interface, so use the current source-owned config contract, never guessed paths.
Missing configuration remains HOLD.
Documentation outside a governed tree needs link/command/scope checks, not automatic
crash/browser qualification. Code, environment, or evidence-binding changes invalidate
prior results according to that evidence contract, even across apparently unrelated files.

## Debugging and completion

First failure: retain the error and isolate a reproducer. A repeated failure needs
an explicit hypothesis and changed evidence before another edit/test. Escalate
ambiguous multi-step failures to Astra medium, cross-system/state failures to high;
stop retrying an unchanged missing prerequisite. Record HOLD with the missing input.
Strong reasoning cannot grant missing authority.

At completion, report the changed surface, checks/exits, remaining failures, and
authority. Keep full logs at their appropriate local evidence path and load only
the relevant failure range. Reuse the existing task's final handoff; create a separate
handoff file only when resumable complex work needs one, not after every small edit.
