"""Generate a hash-guarded current review-input amendment; never grant authority.

Run after the pinned descendant amendment. Do not rerun the legacy amendment on
these outputs. Historical v1 config and baseline replay bytes remain unchanged.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
from pathlib import Path

BASE = "648ba68ba191cd3b406a94ccea0559044bca292e"
PREFIX = "/home/thenam176/betting-helper"
CURRENT = (
    "configs/full-verifier-controller.v2.json",
    "configs/review-a.v2.json",
    "configs/review-b.v2.json",
    "configs/review-aggregation.v2.json",
    "registries/task-command-registry.v1.json",
    "registries/review-command-registry.v1.json",
    "registries/cybersecurity-command-registry.v1.json",
    "registries/path-registry.v1.json",
    "registries/delivery-map.v1.json",
    "registries/reviewer-role-registry.v1.json",
    "registries/artifact-ownership.v1.json",
    "registries/command-io.v1.json",
    "registries/proof-coverage-matrix.v1.json",
    "tasks/task-manifest.v6.3.6.json",
    "security/review-trust-root.v1.json",
)


def predecessor(root):
    path = root / "authoring-fixtures/part-b-review-predecessor.json"
    raw = path.read_bytes()
    if (
        path.is_symlink()
        or hashlib.sha256(raw).hexdigest()
        != "99f45eaf4f28f77ce7ed4c74e12e64b43743663a7779a9b507f35a164fe455ca"
    ):
        raise ValueError("E_PART_B_PREDECESSOR")
    value = json.loads(raw)
    if value["commit"] != BASE:
        raise ValueError("E_PART_B_PREDECESSOR")
    return {
        name: base64.b64decode(data, validate=True)
        for name, data in value["files"].items()
    }


def targets(authoring, runtime, evidence, host):
    paths = [Path(p) for p in (authoring, runtime, evidence, host)]
    if any(not p.is_absolute() or p.resolve() != p for p in paths) or any(
        a == b or a.is_relative_to(b) or b.is_relative_to(a)
        for i, a in enumerate(paths)
        for b in paths[i + 1 :]
    ):
        raise ValueError("E_PART_B_INPUT_ROOT")
    return dict(zip(("authoring", "runtime", "evidence", "host"), map(str, paths)))


def extend_compiler_ownership(root, docs, runtime):
    # Source declarations frozen at the user-approved Part B commit, never a scan
    # of observed compiler output. Actual output equality stays a runtime check.
    path = root / "authoring-fixtures/part-b-compiler-inputs.json"
    raw = path.read_bytes()
    if path.resolve() != path or path.stat().st_nlink != 1 or hashlib.sha256(raw).hexdigest() != (
        "b941d8c2b7a62d22964a6c79fff21f782709c205114289827580bdbd7b6d4000"
    ):
        raise ValueError("E_PART_B_COMPILER_INPUTS")
    frozen = json.loads(raw)
    entries = docs["registries/artifact-ownership.v1.json"]["entries"]
    known = {row["path"] for row in entries}
    inputs, tests, production = [], [], []
    for relative, digest in frozen["sources"].items():
        source = "runtime/" + relative
        if source in known:
            raise ValueError("E_PART_B_COMPILER_INPUT_DRIFT")
        inputs.append(source)
        entries.append({
            "path": source, "classification": "EXTERNAL_INPUT", "creation_owner": None,
            "modifying_tasks": [], "materialization_required": True,
            "source": {"path": runtime + "/" + relative,
                       "binding": "PART_B_SOURCE_COMMIT:" + frozen["commit"] + ":sha256:" + digest},
            "qualification_owner": "V636-P05-T09",
            "consumers": ["V636-P04-T03", "V636-P05-T09"],
        })
        test = "runtime/extension/.test-build/" + relative.removeprefix("extension/")[:-3] + ".js"
        tests.append(test)
        entries.append({
            "path": test, "classification": "GENERATED_OUTPUT",
            "creation_owner": "V636-P04-T03", "modifying_tasks": ["V636-P05-T09"],
            "materialization_required": False, "source": {"path": source},
            "qualification_owner": "V636-P05-T09", "consumers": ["V636-P05-T09"],
        })
        if relative.startswith("extension/src/"):
            output = "runtime/extension/dist/" + relative.removeprefix("extension/src/")[:-3] + ".js"
            production.append(output)
            entries.append({
                "path": output, "classification": "GENERATED_OUTPUT",
                "creation_owner": "V636-P05-T09", "modifying_tasks": [],
                "materialization_required": False, "source": {"path": source},
                "qualification_owner": "V636-P05-T09",
                "consumers": ["V636-P05-T09", "V636-P07-T01", "V636-P08-T01",
                              "V636-P08-T03", "V636-P10-T02"],
            })
    for row in docs["tasks/task-manifest.v6.3.6.json"]["tasks"]:
        if row["task_id"] in {"V636-P04-T03", "V636-P05-T09"}:
            row["inputs"] = sorted(set(row["inputs"]) | set(inputs))
            outputs = tests + (production if row["task_id"] == "V636-P05-T09" else [])
            row["outputs"] = sorted(set(row["outputs"]) | set(outputs))
    for row in docs["registries/command-io.v1.json"]["commands"]:
        if row["command_id"] in {"COMPILE_V636_P04_T03", "COMPILE_ALL_TESTS", "COMPILE_PRODUCTION"}:
            prod = row["command_id"] == "COMPILE_PRODUCTION"
            row["inputs"] = sorted(set(row["inputs"]) | {
                p for p in inputs if not prod or p.startswith("runtime/extension/src/")
            })
            row["outputs"] = sorted(set(row["outputs"]) | set(production if prod else tests))


def build(root, original, target, init_sha256):
    if not re.fullmatch("[0-9a-f]{64}", init_sha256):
        raise ValueError("E_PART_B_HOST_IDENTITY")
    mappings = {
        PREFIX + "/discovery-runtime-v6.3.6": target["runtime"],
        PREFIX + "/authoring-controller-config-worktree": target["authoring"],
        PREFIX + "/authoring-evidence/hybrid-discovery-v6.3.6-controller": target[
            "evidence"
        ],
        PREFIX + "/review-packs/hybrid-discovery-v6.3.6": target["host"] + "/pack",
        PREFIX + "/review-workspaces/hybrid-discovery-v6.3.6": target["host"]
        + "/workspaces",
        PREFIX + "/reviews/hybrid-discovery-v6.3.6": target["host"] + "/results",
        PREFIX + "/review-authorizations/hybrid-discovery-v6.3.6": target["host"]
        + "/authorizations",
    }

    def transport(value):
        if isinstance(value, str):
            for old, new in mappings.items():
                value = re.sub(re.escape(old) + r"(?=$|[/.'\"])", lambda _: new, value)
            return value
        if isinstance(value, list):
            return [transport(v) for v in value]
        if isinstance(value, dict):
            return {transport(k): transport(v) for k, v in value.items()}
        return value

    docs = {
        name: transport(json.loads(original["pack/docs/" + name])) for name in CURRENT
    }
    cfg = docs["configs/full-verifier-controller.v2.json"]
    cfg["external_authoring_command"]["cwd"] = target["authoring"]
    a = docs["configs/review-a.v2.json"]
    producer = a["producer_environment"]
    producer["native_dependency_root"] = (
        "/mnt/c/Users/thenam/Documents/BettingHelper-Repair-Chrome/"
        "native-dependency-closure-ef63da26-f87f-45ab-af76-dd2b9ef02c08"
    )
    producer["path_translation_sha256"] = init_sha256
    producer["runtime_unc"] = (
        "\\\\wsl.localhost\\"
        + producer["wsl_distro"]
        + target["runtime"].replace("/", "\\")
    )
    for name in ("configs/review-a.v2.json", "configs/review-b.v2.json"):
        docs[name]["excluded_roots"] = [
            target["authoring"]
            if x == PREFIX + "/hybrid-discovery-v6.3.6-authoring"
            else x
            for x in docs[name]["excluded_roots"]
        ]
    roles = docs["registries/reviewer-role-registry.v1.json"]
    roles["authoring_root_excluded"] = target["authoring"]
    trust = docs["security/review-trust-root.v1.json"]
    trust["private_key_must_not_exist_under"] = [
        target["authoring"] if x == PREFIX + "/hybrid-discovery-v6.3.6-authoring" else x
        for x in trust["private_key_must_not_exist_under"]
    ]
    for row in docs["registries/task-command-registry.v1.json"]["commands"]:
        if row["command_id"] == "V636_MIG0_T08_BINDINGS":
            row["argv"][row["argv"].index("--output") + 1] = (
                target["runtime"] + "/task-command-registry.json"
            )
        if row["command_id"] == "VERIFY_EXTERNAL_AUTHORING_SOURCES":
            row["cwd"] = cfg["external_authoring_command"]["cwd"]
            row["argv"] = cfg["external_authoring_command"]["argv"]
    paths = docs["registries/path-registry.v1.json"]
    paths.update(
        authoring_root=target["authoring"],
        runtime_candidate=target["runtime"],
        pack_candidate=target["authoring"] + "/pack",
    )
    delivery = docs["registries/delivery-map.v1.json"]
    delivery["runtime_source_root"] = target["runtime"]
    new_sources = (
        "authoring-tools/prepare_part_b_review_inputs.py",
        "authoring-tests/test_part_b_review_inputs.py",
        "authoring-fixtures/part-b-review-predecessor.json",
        "authoring-fixtures/part-b-compiler-inputs.json",
    )
    for source in new_sources:
        delivery["authoring_source_exports"].append(
            {
                "source": source,
                "destination": "pack/authoring-source/" + source,
                "owner": "V636-P09-T01",
            }
        )
        docs["registries/artifact-ownership.v1.json"]["entries"].append(
            {
                "path": source,
                "classification": "TASK_OUTPUT",
                "creation_owner": "V636-MIG0-T08",
                "modifying_tasks": [],
                "materialization_required": True,
                "source": None,
                "qualification_owner": "V636-MIG0-T08",
                "consumers": ["V636-MIG0-T08", "V636-P09-T01"],
            }
        )
    for row in docs["tasks/task-manifest.v6.3.6.json"]["tasks"]:
        if row["task_id"] == "V636-P09-T01":
            row["inputs"] = sorted(set(row["inputs"]) | set(new_sources))
        if row["task_id"] == "V636-MIG0-T08":
            row["outputs"] = sorted(set(row["outputs"]) | set(new_sources))
    for row in docs["registries/command-io.v1.json"]["commands"]:
        if row["command_id"] == "VERIFY_V636_P09_T01":
            row["inputs"] = sorted(set(row["inputs"]) | set(new_sources))
    rows = []
    for entry in sorted(
        delivery["authoring_source_exports"], key=lambda r: r["source"].encode()
    ):
        source = entry["source"]
        path = root / source
        if (
            path.is_symlink()
            or not path.is_file()
            or path.resolve() != path
            or path.stat().st_nlink != 1
        ):
            raise ValueError("E_PART_B_EXPORT")
        payload = path.read_bytes()
        rows.append(
            f"{source}\0{len(payload)}\0{hashlib.sha256(payload).hexdigest()}\n".encode()
        )
    cfg["external_authoring_source_sha256"] = hashlib.sha256(b"".join(rows)).hexdigest()
    extend_compiler_ownership(root, docs, target["runtime"])
    # Bootstrap, legacy receipt inputs and v1 configs retain their original meaning.
    before = json.loads(original["pack/docs/registries/task-command-registry.v1.json"])
    frozen = {
        r["command_id"]: r
        for r in before["commands"]
        if r["command_id"].startswith("BOOT0_")
    }
    docs["registries/task-command-registry.v1.json"]["commands"] = [
        copy.deepcopy(frozen.get(r["command_id"], r))
        for r in docs["registries/task-command-registry.v1.json"]["commands"]
    ]
    return {
        "pack/docs/" + name: (
            json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        for name, value in docs.items()
    }


def materialize(root, original, expected):
    # Validate every destination before writing any: no unknown predecessor repair.
    for name, data in expected.items():
        path = root / name
        if (
            path.is_symlink()
            or path.resolve() != path
            or not path.is_file()
            or path.stat().st_nlink != 1
            or path.read_bytes() not in (original[name], data)
        ):
            raise ValueError(f"E_PART_B_INPUT_DRIFT:{name}")
    for name, data in expected.items():
        path = root / name
        if path.read_bytes() != data:
            temporary = path.with_suffix(path.suffix + ".part-b-tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
            temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    for name in ("runtime", "evidence", "host", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = targets(root, args.runtime, args.evidence, args.host)
    original = predecessor(root)
    expected = build(
        root, original, target, hashlib.sha256(Path("/init").read_bytes()).hexdigest()
    )
    materialize(root, original, expected)
    report = {
        "kind": "GENERATED_REVIEW_INPUTS_NOT_QUALIFICATION",
        "predecessor": BASE,
        "targets": target,
        "files": {
            name: {
                "before": hashlib.sha256(original[name]).hexdigest(),
                "after": hashlib.sha256(data).hexdigest(),
            }
            for name, data in expected.items()
        },
        "authority": "NONE",
        "receipt_issued": False,
    }
    with args.report.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {"result": "INPUTS_GENERATED", "files": len(expected), "authority": "NONE"}
        )
    )


if __name__ == "__main__":
    main()
