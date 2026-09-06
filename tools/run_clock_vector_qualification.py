"""Cross-language qualification for the closed clock-vector coverage inventory."""
# ruff: noqa: E402
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from subprocess import PIPE, run

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RUNTIME_ROOT), str(RUNTIME_ROOT / "src")]

from moj_discovery.clock_vectors import evaluate_clock_mapping_vector


_NODE = r'''
const { pathToFileURL } = require("node:url");
(async () => {
  const module = await import(pathToFileURL(process.argv[3]).href);
  const value = module.evaluateClockMappingVector(JSON.parse(process.argv[1]), JSON.parse(process.argv[2]));
  process.stdout.write(JSON.stringify(value));
})().catch(error => { console.error(String(error)); process.exit(1); });
'''


def _typescript(vector: dict[str, object], guardrails: dict[str, object], runtime: Path) -> dict[str, object]:
    completed = run(
        [
            "node", "-e", _NODE, json.dumps(vector), json.dumps(guardrails),
            str(runtime / "extension/.test-build/src/contracts/clock-vectors.js"),
        ],
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"E_CLOCK_TYPESCRIPT:{completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _ids(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(item for key, item in value.items() if key == "id" and isinstance(item, str)),
            *set().union(*(_ids(item) for item in value.values())),
        }
    if isinstance(value, list):
        return set().union(*(_ids(item) for item in value)) if value else set()
    return set()


def run_clock_vector_qualification(pack: Path, runtime: Path) -> dict[str, object]:
    vectors = json.loads((pack / "docs/vectors/inherited/clock-coherence-v6.2.json").read_text())
    coverage = json.loads((pack / "docs/registries/clock-vector-coverage.v1.json").read_text())
    entries = coverage["entries"]
    coverage_ids = [entry["vector_id"] for entry in entries]
    if len(entries) != 65 or len(coverage_ids) != len(set(coverage_ids)) or not set(coverage_ids) <= _ids(vectors):
        raise ValueError("E_CLOCK_COVERAGE")
    cases = [vectors["golden_mapping"]]
    for negative in vectors["mapping_negative_vectors"]:
        candidate = copy.deepcopy(vectors["golden_mapping"])
        candidate.update(negative["mutation"])
        cases.append(candidate)
    for case in cases:
        python = evaluate_clock_mapping_vector(case, vectors["guardrails"])
        typescript = _typescript(case, vectors["guardrails"], runtime)
        if python != typescript:
            raise ValueError("E_CLOCK_PARITY")
    for negative in vectors["mapping_negative_vectors"]:
        candidate = copy.deepcopy(vectors["golden_mapping"])
        candidate.update(negative["mutation"])
        if evaluate_clock_mapping_vector(candidate, vectors["guardrails"])["accepted"]:
            raise ValueError("E_CLOCK_MUTATION_SURVIVOR")
    return {
        "result": "PASS",
        "covered_vector_count": len(coverage_ids),
        "cross_language_drift": 0,
        "mutation_survivors": 0,
        "skipped_vectors": 0,
    }
