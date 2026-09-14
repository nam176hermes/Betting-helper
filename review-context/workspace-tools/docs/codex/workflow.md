# Codex workflow: operational defaults

Use this guide on demand. This workflow grants no production, provider, credential,
remote-write, signing, or formal-review authority. Existing contracts take priority.
Audit reports and evidence are not startup context.

## Bootstrap and task packet

Resolve exact CWD/Git root/HEAD and dirty ownership; resolve applicable instructions;
classify risk; inspect named source and nearest tests; load contracts/callers only
when needed. Expand discovery only to resolve a concrete missing fact. Do not scan
all repositories, history, docs, dependencies, or tests at startup.

Use the stdlib helper from this workspace. Keep packet/state/logs under `/tmp` or
an existing ignored task evidence directory, outside source and sealed inputs:

```bash
python3 scripts/codex_task.py prepare --packet /tmp/task.json --state /tmp/task-state.json
python3 scripts/codex_task.py read --state /tmp/task-state.json src/example.py --start 20 --end 70
python3 scripts/codex_task.py check --state /tmp/task-state.json focused
python3 scripts/codex_task.py resume --state /tmp/task-state.json
python3 scripts/codex_task.py close --state /tmp/task-state.json
python3 scripts/codex_task.py bridge --check
```

The filename/check ID above are examples; select actual source and repository commands.
Start from [task-packet.example.json](task-packet.example.json), replacing its placeholders.
A packet is one JSON object, at most 16,000 characters, with these fields:

| Field | Required content |
| --- | --- |
| `task`, `expected_output` | Bounded task and expected deliverable |
| `cwd`, `target_head` | Absolute exact CWD and full HEAD (`UNBORN` if applicable) |
| `dirty_ownership` | Every porcelain dirty path mapped to its owner; preserve other work |
| `files` | 1–40 explicit relevant files, including tests/config on which facts depend |
| `constraints`, `known_verified_facts`, `do_not_reread` | Arrays of concise strings; reference large evidence by path |
| `authority`, `exit_condition` | Explicit authority boundary and completion condition |
| `required_checks` | Array of `{ "id": "focused", "argv": ["python3", "..."], "tier": "V1", "timeout": 120 }` |
| `role` | `coordinator`, `implementation`, `review`, `analysis`, or `formal` |
| `risk` | Six integer axes 0–2 plus explicit `critical_flags` array, below |
| `areas` | One or more change classes from the verification table |
| Optional handoff fields | `task_status`, `decisions`, `unresolved_questions`; arrays for the latter two |
| Batch field | `independent: true`; coordinator must establish actual independence |

`prepare` validates ownership and records scoped byte hashes plus instruction hashes.
Commands use argv arrays, never shell interpolation. The packet is operator-owned local
input, not a security boundary or permission grant. The helper is not a sandbox or
signed evidence service. Canonical packet changes or route corruption require re-preparation.

For a CLI worker, select the installed executable explicitly:

```bash
python3 scripts/codex_task.py launch --state /tmp/task-state.json --codex /absolute/path/to/codex
python3 scripts/codex_task.py batch /tmp/a-state.json /tmp/b-state.json --codex /absolute/path/to/codex
```

The installed desktop WSL binary tested in Phase 2 is Codex 0.153.4 at
`/mnt/c/Users/thenam/.codex/bin/wsl/b53f5e5f7452dd19/codex`.
The shell's Codex 0.147.0 rejected Astra. Paths/catalogs can change; use `--version`
and the existing executable, never silently substitute a weaker model or edit global config.
`launch` injects the bounded policy/packet, selects model/effort, disables worker child agents,
and uses workspace-write only for implementation, read-only otherwise. Existing host
approval/config rules remain active. Explicit caller constraints still govern commands.

## Risk routing and transitions

Daily main/coordinator default: **Astra low** (`gpt-6-astra`, reasoning `low`),
configured at the user's request on 2026-09-08 after Phase 3. The helper uses Astra
low for MECHANICAL/NORMAL coordinators, Astra medium for COMPLEX coordinators,
and Astra high for CRITICAL coordinators. Return to low when the difficult decision
is resolved and the remaining coordinator task is reclassified M/N; unresolved critical
work retains its floor. Existing desktop tasks may retain their explicit model/effort
selection; the helper cannot change a running desktop task.

The table below selects worker routes. Worker defaults and all verification/review
floors remain unchanged. Historical Phase 2/3 measurements describe their recorded
routes, not a measured Astra-low baseline; this preference change runs no model benchmark.

Score each axis: `ambiguity`, `blast_radius`, `failure_cost`, `coupling`, `novelty`,
`safety`: 0 absent/low; 1 meaningful but localized; 2 high. File count is not a risk axis.

| Deterministic class rule, evaluated in order | Route |
| --- | --- |
| Any critical flag, safety >0, failure_cost=2, or security/authority/persistence/recovery/clock area | CRITICAL: Astra high |
| Otherwise any axis=2 or sum >=5 | COMPLEX: Sol medium; Astra medium when ambiguity=2 or novelty=2 |
| Otherwise any nonzero score or area minimum >=V2 | NORMAL: Terra medium |
| Otherwise | MECHANICAL: Luna low |

Critical flags: `live`, `financial`, `credentials`, `authentication`, `persistence`,
`recovery`, `checkpoint`, `concurrency`, `idempotency`, `kill_switch`, `order_state`,
`state_ownership`, `irreversible_migration`. Class and minimum verification are recorded
in task state. Classification depends on truthful input; the helper cannot discover hidden risk.

Escalate when a new counterexample, unresolved ambiguity, cross-system dependency,
authority boundary or costly failure appears: stop the mechanical step, prepare a new
packet with updated axes/flags, and record the old/new route and new evidence in `decisions`.
Never repeatedly retry a missing prerequisite. Astra high is for difficult decisions and
adversarial review; grep, formatting, boilerplate and status checking are not reasons for it.

De-escalate resolved C/D implementation to Sol medium using `frozen_decision`:
`{ "evidence": {"path": "decision.md", "sha256": "<actual digest>"},
"open_questions": [], "deterministic_implementation": true }`.
Include that evidence in scoped files. Only implementation can de-escalate; evidence bytes
must match, and the risk class, V3/V4 floor and required review remain unchanged.
A critical review stays Astra high. The helper does not change an already running desktop
model; native tasks require the operator to apply the route explicitly.

## Delegation and completion

Normally 0–2 workers. Before dispatch establish: independent work, needed context already
known by the coordinator, risk of rediscovering the same files, meaningful parallel benefit,
and any mandatory independent-review role. Do not dispatch merely because a slot exists.
Give each worker the bounded packet above, not the entire session history. Share verified
reconnaissance for implementation; formal A/B reviewers receive only authorized immutable
inputs, no peer findings or substitute human attestations.

`batch` defaults to two workers, rejects shared state and overlapping implementation
scopes/Git roots, and requires `independent: true`. More than two requires
`--workers N --justification "<independent workstreams and expected benefit>"`, up to the
host's eight-worker ceiling. Keep that reason with the task handoff. This cap is per helper
batch, not a global concurrency lock; separate batches and native tools still need coordination.

Dispatch bounded independent work, continue useful coordinator work, then collect when
its result becomes a dependency. `batch` consumes completed futures without model polling.
Run a long batch through the host's yielding execution tool and collect when needed.
For native collaboration, use a completion/event wait up to 60 seconds, preserve cursors,
and do not issue status messages on unchanged state. If no independent work remains, waiting
is appropriate. Merge once, then verify the combined changed state. Never suppress required
review just to meet the worker target.

Formal launches remain in the existing separately authorized controller path. The generic
helper rejects `role: formal`; it cannot replace signed prompts, namespaces, seals or A/B
independence. Host prompt rendering proves host instruction loading only, not isolated
review namespace execution. Such execution remains HOLD until authorized and verified.

## Verification escalation

Select exact commands from the chosen repository/task contract. Tiers are minimum plans,
not substitutes for individual mandated tests or execution receipts.

| Area / change class (`areas` value) | Minimum | Required scope |
| --- | --- | --- |
| `docs`, `mechanical` | V0 LOCAL | Syntax/links/changed-file check; no application behavior change |
| `extension_ui` | V1 TARGETED | Affected UI tests; relevant package checks |
| `subsystem`, `workflow_tooling` | V2 SUBSYSTEM | Affected tests, relevant lint/type checks and integration boundaries |
| `shared_infrastructure`, `schema` | V3 PORTABLE | Targeted checks then portable and affected contract tests |
| `clock`, `persistence`, `recovery` | V3 + review | Portable plus mandated negative/crash/time/recovery vectors |
| `security`, `authority`, `release` | V4 GOVERNED | V3 plus full governed configuration and required independent review |
| Any critical flag | At least V3 + review | Live/financial flags force V4; tag `authority` for other formal authority work |

V0→V1→V2→V3→V4 means escalating scope, not rerunning identical included checks for each label.
A changed-file check cannot establish subsystem coverage simply by labeling it V2.
The helper verifies the declared check plan and freshness; it does not infer contract completeness.
All V3/V4 or review-requiring tasks remain `HOLD` in helper completion until the external
controller provides its own genuine qualification. Lower results are `LOCAL_PLAN_PASS`,
never production readiness. Critical work: correctness > quota.

Runtime examples, from the selected runtime CWD:

```bash
uv run --frozen --offline python -m pytest -q tests/repairs/test_ci_profile_contract.py
pnpm typecheck
pnpm lint
uv run --frozen --offline python tools/run_command_registry.py --self-check
uv run --frozen --offline python tools/verify_local.py --profile portable
```

The first test is an example, not a universal gate. Read relevant manifests if their bytes
changed. Extension tests need compilation before Node execution. Portable already compiles
and self-checks; reuse those included results when contracts permit. Its 350-test collection
is not 350 executed tests. The Phase 1 portable run executed 84 tests in about 765 seconds.
That cost is not permission to weaken it. Full uses
`tools/verify_local.py --profile full --config <source-owned-config-path>`; old individual
README flags are stale. Missing configuration, evidence, browser binding, reviewer authority
or genuine negative vectors remain HOLD. Only the controller runs full baseline/sealing.

Runtime instruction edits can invalidate source-bound receipts even when application code
is unchanged. This workflow never promotes prior receipts to current qualification.
Python baseline debt from Phase 1 remains Ruff 28 and mypy 163 errors across 29 files;
report it separately, and check new code without hiding that debt.

## Tool reuse, output, retries and resumption

Use precise `rg`, known paths, narrow diffs, bounded log ranges and batched independent reads.
`read` accepts up to 200 lines and returns at most 8,000 characters. A repeated identical
file/hash/range returns a reuse marker. Ordinary tool output should stay around 2,000 tokens;
worker summaries around 2,000 characters; M/N uses FINDING / EVIDENCE / ACTION / RESULT / OPEN ISSUE.
C/D retains its full Phase 2 handoff, including impact where material.
Large artifacts stay at paths. These limits do not override a user-requested report.

`check` retains complete stdout/stderr in a per-attempt file and returns a 2,000-byte tail.
Repeated identical command/input/environment fingerprints are rejected unless accompanied by
`--reason` and `--new-information`. Allowed reasons: `changed_inputs`, `changed_state`,
`insufficient_output`, `different_environment`, `fresh_evidence`, `contract_rerun`,
`new_hypothesis`. Attempt records link the previous attempt, reason and new information.
Raw shell/MCP calls bypass these wrappers; instructions and trace review remain necessary.
Declare environment changes explicitly; the helper does not hash every external dependency.

`resume` returns a compact handoff: exact target, HEAD, dirty ownership, task status,
verified facts, decisions, files read, completed/remaining checks and unresolved questions.
Facts are valid only while bound HEAD, relevant bytes, dirty status and instruction hashes
match. Changed state returns HOLD; prepare a fresh packet with only revalidated facts.
Checks are invalidated by changed relevant bytes and a later failing attempt overrides an
older pass. All relevant inputs must be in `files`; this is not a whole-repository receipt cache.
Keep a single writer per state file. For native session resumption use the fresh packet:
`launch --state /tmp/new-state.json --codex /absolute/path/to/codex --resume-id <exact-id>`.
A new state prevents overwriting prior transcripts; do not retry a completed launch silently.

## Measure changes

`python3 scripts/benchmark_codex.py --codex /absolute/path/to/codex --output /tmp/new-empty-benchmark --case normal --variant after --run`
explicitly runs ONE selected subscription-consuming fixture evaluation. Both selectors are required;
the command will not start a matrix by default. Reuse existing corners before selecting a new run.
It compares the frozen Phase 1 guide + Astra/high with routed bounded packets; this is a
bundled workflow comparison, not a causal test of each component. Keep failed runs and
quality findings. Use fresh empty output directories; never production behavior as a fixture.
The Phase 2 report/evidence contain measured results, unavailable metrics and limitations.
No token-to-quota conversion or unmeasured savings percentage is authorized by these proxies.

## Phase 3 M/N context profiles

`prompt` now renders M/N as one merged, compact target/check context. The validated packet
still contains all required fields; full fingerprints, scores and empty optional fields
remain in state instead of being repeated in the model prompt. A concise instruction-presence
map identifies already verified bootstrap facts. Nonempty constraints, ownership, required
checks, authority, decisions and unresolved questions remain available.

NORMAL implementation receives the complete code-work skill once, with source path and hash,
plus exact Serena capability names. All other skills/MCPs remain available on demand. No
global configuration, catalog or plugin was disabled. Prefer direct named tools; if discovery
is necessary, return at most eight matching names rather than descriptions. Initialize and
activate sequentially, then read the manual before semantic work. Batch independent symbol,
caller and verification queries after prerequisites are met. Return one MCP text representation.

MECHANICAL keeps only its basic bounded task/authority/check context; relevant skills remain
on demand. COMPLEX and CRITICAL retain the Phase 2 full prompt and policy. Their risk floors,
critical reasoning and V3/V4/review obligations are unchanged.

If a focused precheck has already run through `check` on the identical prepared snapshot,
M/N prompts carry its actual exit, log and bounded tail. A failed precheck establishes the
reproducer; repeat only after changed inputs or another allowed freshness reason. Prechecks
are optional and selected, never an automatic full-suite startup step. `check` stdout now
contains result/log/tail/retry information; full fingerprints remain in task state.

M/N workers use low model verbosity and normally return five short fields:
FINDING / EVIDENCE / ACTION / RESULT / OPEN ISSUE. Required skill announcements, meaningful
progress, failures and explicitly requested detail take precedence over brevity. These are
model-level defaults, not a guarantee that every native tool output is minimal.

[Phase 3 evidence](phase3-2026-09-08.md) establishes improvement in the sampled Terra comparisons,
but the same-Astra result remains mixed. Do not infer actual quota savings or system-level
acceptance. The longer-task evaluation remains gated on synthetic acceptance; formal
namespace propagation remains separately HOLD.
