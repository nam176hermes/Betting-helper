# Corrected v6.3.6 design

The authority and topology remain discovery-plan-only. Sources: immutable v6.3.2 review artifacts, the byte-pinned v6.2 runtime/protocol bundle, and this reviewed successor specification. Delivery paths migrate; inherited wire-protocol URNs/hashes do not silently change.

Flow: BOOT0 -> P00 declaration -> MIG0 initial copy/tooling -> P01 materialization -> MIG0-T07 sync/build -> P02 materialized contracts -> P03/P04/P05 qualification -> MIG0-T08 final normative sync -> P06 executable references/source freeze -> P07 candidate evidence -> P08 zero-parent delivery -> P09 acyclic seal -> P10 isolated independent reviews/aggregation.

All source creation is early and owned. All release/review tooling is implemented and tested before P06; P06 validation tooling finishes before P07. Proof stages CANDIDATE, SEALED, REVIEWED make future evidence ineligible at earlier gates. Export/seal/review cannot alter qualified source. Every implicit path/command consumer is part of the ownership closure.

The exact design decisions live once in docs/contracts/00 through 09 and machine-readable registries. Task cards reference those contracts; prompts are human inputs. Self-review reports local validation only. An independent reviewer, then explicit human task authority, are still required before implementation. AUTHORIZED_PRODUCTION_PHASES: NONE.
