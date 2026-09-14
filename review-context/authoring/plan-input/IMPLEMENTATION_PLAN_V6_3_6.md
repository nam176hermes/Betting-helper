# Implementation plan v6.3.6

Scope: repair/implement the declared successor contract tooling only after independent review and explicit human task authorization. This authoring run implements no discovery runtime.

## Exact dependency order

| Task | Dependencies | Outcome |
|---|---|---|
| V636-BOOT0-T01 |  | Verify and extract sealed plan input |
| V636-BOOT0-T02 | V636-BOOT0-T01 | Create isolated authoring workspace |
| V636-BOOT0-T03 | V636-BOOT0-T02 | Initialize authoring Git repository |
| V636-P00-T01 | V636-BOOT0-T03 | Freeze source reviews and provenance |
| V636-P00-T02 | V636-P00-T01 | Freeze authority graphs |
| V636-P00-T03 | V636-P00-T02 | Freeze task schema and manifest semantics |
| V636-P00-T04 | V636-P00-T03 | Freeze artifact ownership and path registries |
| V636-P00-T05 | V636-P00-T04 | Issue DECLARATION_COMPLETE gate |
| V636-MIG0-T01 | V636-P00-T05 | Verify v6.2 source baseline |
| V636-MIG0-T02 | V636-MIG0-T01 | Populate the existing BOOT0 workspace from the pinned baseline |
| V636-MIG0-T03 | V636-MIG0-T02 | Rebind versioned paths, IDs, and working roots |
| V636-MIG0-T04 | V636-MIG0-T03 | Synchronize one normative bundle |
| V636-MIG0-T05 | V636-MIG0-T04 | Regenerate task command registry and config bindings |
| V636-MIG0-T06 | V636-MIG0-T05 | Scan legacy references and issue migration receipt |
| V636-P01-T01 | V636-MIG0-T06 | Materialize runtime toolchains and test configuration |
| V636-P01-T02 | V636-P01-T01 | Materialize every declared source and test stub |
| V636-P01-T03 | V636-P01-T02 | Materialize schemas, registries, vectors, and exact schema definitions |
| V636-P01-T04 | V636-P01-T03 | Materialize all crash and clock harness entrypoints |
| V636-P01-T05 | V636-P01-T04 | Materialize review, cybersecurity, aggregation, export, and sealing tools |
| V636-P01-T06 | V636-P01-T05 | Issue MATERIALIZATION_COMPLETE gate |
| V636-MIG0-T07 | V636-P01-T06 | Synchronize fully materialized normative assets and refresh native locks |
| V636-P02-T01 | V636-MIG0-T07 | Validate materialized task-manifest semantics |
| V636-P02-T02 | V636-P02-T01 | Validate materialized artifact ownership and lifecycle |
| V636-P02-T03 | V636-P02-T02 | Issue MATERIALIZED_CONTRACTS_VALID gate |
| V636-P03-T01 | V636-P02-T03 | Freeze and validate complete crash-vector mapping |
| V636-P03-T02 | V636-P03-T01 | Qualify real Chrome and IndexedDB test environment |
| V636-P03-T03 | V636-P03-T02 | Execute IndexedDB spool crash matrix |
| V636-P03-T04 | V636-P03-T03 | Execute loopback delivery and ACK crash matrix |
| V636-P03-T05 | V636-P03-T04 | Execute SQLite transaction crash matrix |
| V636-P03-T06 | V636-P03-T05 | Execute GAP, generation, and coherence crash matrix |
| V636-P03-T07 | V636-P03-T06 | Execute destruction matrix and durability release gate |
| V636-P04-T01 | V636-P02-T03 | Freeze clock failure precedence registry |
| V636-P04-T02 | V636-P04-T01 | Implement Python clock-vector evaluator |
| V636-P04-T03 | V636-P04-T02 | Implement TypeScript clock-vector evaluator |
| V636-P04-T04 | V636-P04-T03 | Qualify cross-language clock parity and mutation sensitivity |
| V636-P05-T01 | V636-P02-T03 | Implement exact file and symbol resolver |
| V636-P05-T02 | V636-P05-T01 | Implement proof-coverage matrix verifier |
| V636-P05-T03 | V636-P05-T02 | Freeze cybersecurity command registry and attack matrix |
| V636-P05-T04 | V636-P05-T03 | Implement host-issued review launch authorization |
| V636-P05-T05 | V636-P05-T04 | Implement isolated review workspace preparation and finalization |
| V636-P05-T06 | V636-P05-T05 | Implement Review A mechanical runner |
| V636-P05-T07 | V636-P05-T06 | Implement Review B cybersecurity runner |
| V636-P05-T08 | V636-P05-T07 | Implement deterministic review aggregation and internal self-review tooling |
| V636-P05-T09 | V636-P05-T08, V636-P03-T07, V636-P04-T04 | Implement and qualify all candidate, export, baseline and sealing tools |
| V636-MIG0-T08 | V636-P03-T07, V636-P04-T04, V636-P05-T09 | Finalize normative synchronization and lock source/config bindings |
| V636-P06-T01 | V636-MIG0-T08 | Resolve every executable file, symbol, schema, vector, command, and config |
| V636-P06-T02 | V636-P06-T01 | Verify test discovery, build configs, and command coverage |
| V636-P06-T03 | V636-P06-T02 | Issue EXECUTABLE_REFERENCE_COMPLETE gate |
| V636-P07-T01 | V636-P06-T03 | Run complete candidate command registry |
| V636-P07-T02 | V636-P07-T01 | Validate complete proof-coverage matrix |
| V636-P07-T03 | V636-P07-T02 | Issue candidate qualification receipt |
| V636-P08-T01 | V636-P07-T03 | Export deterministic final runtime candidate |
| V636-P08-T02 | V636-P08-T01 | Create delivered zero-parent Git baseline |
| V636-P08-T03 | V636-P08-T02 | Replay committed baseline in place and issue REPO0 receipt |
| V636-P09-T01 | V636-P08-T03 | Assemble immutable review-pack candidate |
| V636-P09-T02 | V636-P09-T01 | Compute acyclic governed-content root |
| V636-P09-T03 | V636-P09-T02 | Generate internal self-review without ZIP or manifest self-reference |
| V636-P09-T04 | V636-P09-T03 | Generate manifest, deterministic ZIP, sidecar, and external seal attestation |
| V636-P10-T01 | V636-P09-T04 | Issue Review A launch authorization and isolated workspace |
| V636-P10-T02 | V636-P09-T04 | Issue Review B launch authorization and isolated workspace |
| V636-P10-T03 | V636-P10-T01, V636-P10-T02 | Finalize independent review execution receipts |
| V636-P10-T04 | V636-P10-T03 | Aggregate independent reviews and issue handoff verdict |

## Gate rules

DECLARATION_COMPLETE -> MATERIALIZATION_COMPLETE -> MATERIALIZED_CONTRACTS_VALID -> EXECUTABLE_REFERENCE_COMPLETE -> CANDIDATE qualification -> zero-parent export -> SEALED -> EXTERNAL_REVIEWED. MIG0-T07 and MIG0-T08 are explicit synchronization tasks, not implicit repeated phases.

CANDIDATE evidence never consumes seal or review output. Runtime source stops changing at P06-T03; normative/config bindings freeze at MIG0-T08. Later source drift requires a new candidate cycle.

## Inventory

Tasks: 62. Task/bootstrap commands: 142. Crash cases: 46. Clock named vectors: 65; mapping negatives: 16. Separate review/security registries contain the remaining leaf/launch commands.

## Current authority

PLAN_AUTHORED: YES

INDEPENDENT_PLAN_REVIEW: PENDING

READY_TO_IMPLEMENT_DISCOVERY_PACK: NO

AUTHORIZED_PRODUCTION_PHASES: NONE
