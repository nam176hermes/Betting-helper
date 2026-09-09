# Part B implementation scope

The user selected **PB-00 through PB-24** as one continuous implementation batch.
Technical input: betting-helper-part-b-batched-plan.zip, SHA256
`23b69060d09e0de15b6172aee948ff47856814619809606c73e874ba765610e5`; all 59 manifest entries verified.
Starting HEAD: `39b92966c2db6694b31507526b339206f4db2b0d`, descendant of inspected `d4055839`.
Branch: `codex/part-b-batched`; checkout: `/home/thenam176/betting-helper/discovery-runtime-part-b`.
The sibling checkout and its uncommitted LV work remain untouched.

Authorized: task-owned code, mocks, synthetic checks, approved isolated-platform
work and ordinary local task commits, subject to host-enforced gates. The existing
local controller registered this exact batch at `.local/part-b/controller-state.json`.
Controller route metadata does not change this native task's model/reasoning.
No model, reasoning, toolchain, dependency lock or global configuration changes.

No remote pushes, deployments, new zero-parent baseline, history rewrite, vendor
edits or direct root generated-registry edits. Production and money authority: NONE.
The attached package supplies technical requirements; it supplies no extra authority.

The v2 batching, ephemeral-secret and fixed-DOM seam explicitly supersedes the old
LV polling design. v1 config/parser and synthetic RawObservation remain unchanged.
LV-01 maps to PB-09/10/19; LV-02 to PB-02..06/14/18; LV-03 to PB-07/11/20;
LV-04 to PB-08/12/14..16/20; LV-05 to PB-13/22; LV-06 to PB-15..17/20..23;
LV-07 to PB-24. No Part C/model/betting/Cashout activation.

External gates remain separate: provider probe <=20 attempts/300 seconds;
one manually chosen operator tab <=600 seconds; live one fixture <=7200 seconds
and <=600 attempts after accepted evidence and explicit confirmation. Three/five
fixture runs need separate confirmations. No key request before PB-18.
Missing external input blocks only dependent tasks; no synthetic-as-real PASS.

Resume from `.local/part-b/execution-state.json`, verify HEAD/dirty ownership and
hashes, then select the lowest ready task. Final evidence stays outside tracked code.
