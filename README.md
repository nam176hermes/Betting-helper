# Hybrid Discovery v6.2 REPO0 runtime

This directory contains a runnable, authoring-only governance baseline plus typed stubs for later discovery phases. It does not authorize implementation, authenticated access, browser attachment, provider calls, an archive subsystem, or production use.

Normative assets are copied byte-for-byte from the approved pack into `vendor/hybrid-discovery-v6.3.6/` by the sole sync tool. Runtime code reads only that vendor tree. `task-command-registry.json`, `schema-lock.json`, and the vendor manifest are generated outputs and must not be edited independently.

## Verification

```text
uv sync --frozen --python 3.12.3
pnpm install --frozen-lockfile --ignore-scripts
uv run --frozen python tools/sync_pack_assets.py --pack /home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack
uv run --frozen python tools/sync_pack_assets.py --check --pack /home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack
uv run --frozen python tools/verify_normative_bundle.py --pack /home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/pack
uv run --frozen python tools/run_command_registry.py --self-check
uv run --frozen python tools/run_command_registry.py --mode baseline
```

`--mode baseline` runs only registered `PRE_BASELINE` commands. `POST_SEAL` commands require the separately sealed pack, archive, and external baseline receipt and are not bootstrap authority.

The extension bootstrap is inert and reports `READY_TO_IMPLEMENT_DISCOVERY_PACK:NO`. Production authority is always `NONE`.
