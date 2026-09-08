# Discovery runtime authoring rules

- This repository is an inert REPO0 governance/bootstrap baseline. It has no discovery or production authority.
- Never use authenticated operator access, attach Chrome debugger to a real profile, contact providers, or perform network discovery from this repository.
- Consume normative material only from `vendor/hybrid-discovery-v6.3.6/`. `tools/sync_pack_assets.py` is the sole pack-to-vendor copy/check path; never edit vendored files or `task-command-registry.json` by hand.
- Generated boundaries are `vendor/hybrid-discovery-v6.3.6/SCHEMA_SHA256.json`, `schema-lock.json`, `extension/dist/`, and `extension/.test-build/`.
- There is no archive, backup, compaction, rolling deletion, automatic cleanup, or restore subsystem. Whole-run destruction remains a later gated contract.
- Later task tests intentionally fail only with `E_CONTRACT_NOT_IMPLEMENTED:<TASK-ID>` until that exact phase is separately authorized.
- Run focused tests first, then `uv run --frozen python tools/run_command_registry.py --self-check`; only the controller runs the full baseline registry and seals a repository.
- Do not commit, add a remote, push, deploy, or alter authority without explicit controller approval.

`AUTHORIZED_PRODUCTION_PHASES: NONE`

<!-- codex-workflow:begin -->
## Codex operating defaults

Use `/home/thenam176/betting-helper/scripts/codex_task.py` for bounded launch/resume packets.
An injected `CODEX_WORKFLOW_POLICY_` supplies the operating rules once. Without a packet:
use 0-2 independent workers, scoped reads, evidence-based retries and targeted checks first.
Existing authority/HOLD, critical-risk verification and independent-review rules still govern.
Full workflow on demand: `/home/thenam176/betting-helper/docs/codex/workflow.md`.
<!-- codex-workflow:end -->
