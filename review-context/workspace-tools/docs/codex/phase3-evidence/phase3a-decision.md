# Phase 3A — offline analysis and experiment decision

Status: COMPLETE BEFORE ANY NEW MODEL EVALUATION. Source: retained Phase 2 manifest and eight named rollouts, hashes checked. No Phase 1 rescan or model dispatch.

NORMAL first request shrank 29,980 -> 28,034 tokens, but requests increased 5 -> 9. Total uncached input rose 23,640 -> 32,262; cached input 140,544 -> 292,608. Cache ratios were 85.60% -> 90.07%. The growth is predominantly more requests replaying context, not a larger first prompt.

Both NORMAL variants invoked Serena initial_instructions and activate_project. The after run selected 24 entire tool descriptions by matching names AND descriptions (rather than before's two named tools), emitted a roughly 25 KB discovery dump, serialized initialization/activation separately, loaded the 7,302-byte required code-work skill, and used overview + references + symbol body. It removed two broad shell inspections: +1 skill +3 symbols -2 shell = +2 item-level calls. Overview is avoidable for this known function; references/body are useful and required by machine guidance. Skill compliance is retained.

COMPLEX reduced requests 6 -> 4 and recorded total tokens, but uncached input rose 26,207 -> 41,938 due to lower observed cache hit ratio (87.15% -> 66.31%). Even the control's total input reduction does not prove account quota savings.

Every fixture has a 242-entry skill catalog (20,253 bytes), machine AGENTS (7,005 bytes), recommended plugins (3,038 bytes), Ponytail body (5,252 bytes), model-dependent base instructions and other fixed guidance. No outer or nested AGENTS bridge was present in these disposable Git roots: bridge duplication cannot explain the NORMAL regression. Exact wire tool schema sizes are unavailable.

The Phase 2 item output metric omits pure functions.exec discovery output: actual flattened model-visible tool result bytes NORMAL 19,849 -> 40,455; COMPLEX 25,608 -> 16,319. Preserve both metrics, never rewrite Phase 2 totals. Every component token attribution remains unavailable; bytes/characters/hashes are used.

## Smallest corrective experiment

1. M/N prompt: compact merged target/check packet, full required code-work preloaded once for NORMAL implementation, named Serena capabilities with bounded name-only fallback, batch independent symbol/body/reference/check requests, one-copy MCP text, concise final fields. Do not disable skills/MCPs or change global config.
2. C/D policy remains byte-equivalent for the same prepared state; preserve its full critical constraints, risk/verification logic and native tool availability. Reuse existing COMPLEX as control, add a fresh model control only if code/data checks establish exposure changed.
3. NORMAL B: frozen Phase 1 workflow + Terra/medium (new #1). NORMAL C: Phase 3 context + Astra/high (new #2). Existing A is reused. D-old remains historical Phase 2, but cannot complete a true factorial with a changed C workflow. Run D-new with the SAME Phase 3 profile + Terra/medium (new #3) if C quality passes. This rerun is necessary because the workflow/context treatment changed, not to improve statistics.
4. Reserve evaluation #4 for a useful longer local task only after NORMAL synthetic acceptance. A real bounded defect already identified: benchmark_codex.main returns zero even when a completed evaluation's quality is FAIL. Its repair needs a CLI behavior test with mocked model execution, no production access. Compare credible existing evidence conservatively; do not claim system-level savings without a comparable longer-task baseline.

Maximum four new evaluations; no automatic whole matrix or extra seed. Each launch must be recorded before execution. If synthetic acceptance fails, preserve failed results and stop expansion to longer tasks.

## Decision after evaluations 1–2 (before 3–4)

B passed but Terra/frozen guidance used 10 requests, 398,804 input tokens and 37,844 uncached input. C-pilot passed but Astra/new context used 8 requests, 263,065 input and 24,601 uncached, versus A's 5 requests/164,184/23,640. Model-visible tool output improved (19,849 -> 15,078 bytes), but net efficiency is not accepted.

C-pilot still rescanned Git/AGENTS, requested check --help, and returned full snapshot fingerprints from check. These are specific correctable costs. Revision 2 retains a concise verified instruction-presence map, supplies exact check syntax, keeps fingerprints in state rather than stdout, and carries actual fresh preflight results. A failing precheck is executed once by the harness before dispatch and counted separately; the model performs the post-change check. Python -B prevents bytecode files from invalidating that fresh snapshot; oracle bytes/behavior are identical. Skills and required verification remain intact.

Use the remaining TWO calls for D-new (Terra/medium) and C2 (Astra/high), both with identical revision-2 context. Keep C-pilot as a failed efficiency treatment, not the final matrix corner. A and B remain reused. The longer task is deferred until synthetic acceptance; do not exceed four calls merely to finish a planned matrix or improve statistics. If the revision still fails acceptance, no longer-task call is authorized by this decision.
