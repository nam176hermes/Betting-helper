# Hybrid Discovery v6.3.6 — repaired plan contract

This successor repairs the six v6.3.3 review blockers and the related migration/qualification defects. It is a specification package with offline plan/bootstrap validators, not a discovery implementation or production authorization. The v6.3.2/v6.3.3 inputs and v6.2 runtime remain immutable.

Start with BOOTSTRAP.md, IMPLEMENTATION_PLAN_V6_3_6.md, the machine-readable task manifest, and REPAIR_MATRIX_V6_3_6.md. The manifest is authoritative for task dependencies; MIG0 recurs at explicit synchronization tasks after P01 and P05. Phase labels are responsibility lanes, not a strict one-time phase sort.

Current status: plan authored and locally validated; independent plan approval pending. Runtime implementation readiness is NO. AUTHORIZED_PRODUCTION_PHASES: NONE.

Offline verification: python3.12 -B plan_tools/check_plan.py --root . ; python3.12 -B -m unittest discover -s plan_tests -v. Commands are separately represented as argv arrays in the registry. The checker and schema tests require the declared jsonschema 4.26.0 verifier prerequisite; the exact-argv regression also requires pinned Node22.23.0. No implicit install/network action is permitted.
