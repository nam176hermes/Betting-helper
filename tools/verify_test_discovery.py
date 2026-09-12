"""Verify every declared proof group is discoverable by a concrete test command."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.prepare_review_workspace import _node_binary

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = RUNTIME_ROOT / "vendor/hybrid-discovery-v6.3.6"


def verify_verification_topology(runtime_root: Path = RUNTIME_ROOT) -> dict[str, object]:
    try:
        topology = json.loads(
            (
                runtime_root
                / "vendor/hybrid-discovery-v6.3.6/docs/registries/verification-topology.v1.json"
            ).read_text()
        )
        registry = json.loads((runtime_root / "task-command-registry.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("E_VERIFICATION_TOPOLOGY") from error
    groups = topology.get("group_sources") if isinstance(topology, dict) else None
    identifiers = topology.get("candidate_command_ids") if isinstance(topology, dict) else None
    commands = registry.get("commands") if isinstance(registry, dict) else None
    if (
        topology.get("schema_version") != "verification-topology/v1"
        or not isinstance(groups, dict)
        or not isinstance(identifiers, list)
        or not isinstance(commands, list)
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    expected_groups = {
        "bootstrap",
        "authoring",
        "materialization",
        "contracts",
        "durability",
        "clock",
        "review",
        "security",
        "release",
        "seal",
        "test-harness",
    }

    if set(groups) != expected_groups or any(
        not isinstance(sources, list)
        or not sources
        or any(not isinstance(source, str) for source in sources)
        for sources in groups.values()
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    mapped = {row["command_id"]: row for row in commands}
    if (
        len(mapped) != len(commands)
        or len(identifiers) != len(set(identifiers))
        or not set(identifiers) <= mapped.keys()
    ):
        raise ValueError("E_VERIFICATION_TOPOLOGY")
    controller = json.loads(
        (
            runtime_root
            / "vendor/hybrid-discovery-v6.3.6/docs/configs/full-verifier-controller.v2.json"
        ).read_bytes()
    )
    external = controller["external_authoring_command"]
    authoring = Path(external["cwd"])
    expected: dict[str, set[Path]] = {}
    source_groups: dict[str, list[set[Path]]] = {}
    for group, sources in groups.items():
        paths: set[Path] = set()
        source_groups[group] = []
        for source in sources:
            path = (
                (runtime_root / source.removeprefix("runtime/"))
                if source.startswith("runtime/")
                else authoring / source
            )
            files = (
                list(path.rglob("test_*.py"))
                if path.is_dir() and "extension" not in path.parts
                else (list(path.rglob("*.ts")) if path.is_dir() else [path])
            )
            if not files or any(not file.is_file() for file in files):
                raise ValueError("E_VERIFICATION_TOPOLOGY:missing-group:" + group)
            resolved = {file.resolve() for file in files}
            paths.update(resolved)
            source_groups[group].append(resolved)
        expected[group] = paths

    # The supported pytest registry grammar has explicit files/directories and no
    # selectors. A single collection covers their union; it never runs test bodies.
    python_rows = []
    for row in [mapped[name] for name in identifiers] + [
        {"command_id": "VERIFY_EXTERNAL_AUTHORING_SOURCES", **external}
    ]:
        argv = row["argv"]
        if "pytest" not in argv:
            continue
        tail = argv[argv.index("pytest") + 1 :]
        operands = []
        index = 0
        while index < len(tail):
            token = tail[index]
            if token in {"-c", "--confcutdir", "-o"}:
                index += 2
                continue
            if token in {"-q", "--strict-config", "--strict-markers"}:
                index += 1
                continue
            if token.startswith("-") or "::" in token:
                raise ValueError("E_VERIFICATION_TOPOLOGY:unsupported-selection")
            operands.append(token)
            index += 1
        if not operands:
            raise ValueError("E_VERIFICATION_TOPOLOGY:empty-command:" + row["command_id"])
        cwd = (
            authoring if row["command_id"] == "VERIFY_EXTERNAL_AUTHORING_SOURCES" else runtime_root
        )
        python_rows.append(
            {"command_id": row["command_id"], "argv": argv, "cwd": str(cwd), "operands": operands}
        )
    observed: set[Path] = set()
    evidence: list[dict[str, Any]] = []
    for cwd in (runtime_root, authoring):
        selected = [row for row in python_rows if row["cwd"] == str(cwd)]
        operands = sorted({operand for row in selected for operand in row["operands"]})
        if not operands:
            raise ValueError("E_VERIFICATION_TOPOLOGY:empty-collection")
        argv = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "--collect-only",
            "--rootdir",
            str(cwd),
            "-q",
            *operands,
        ]
        if cwd == authoring:
            argv += ["-c", "/dev/null", "--confcutdir", str(authoring)]
        collected = subprocess.run(  # noqa: S603 -- collect fixed local registry operands only.
            argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=120
        )  # noqa: S603
        nodes = sorted(
            line.strip()
            for line in collected.stdout.splitlines()
            if "::" in line and not line.startswith((" ", "<", "E "))
        )
        if collected.returncode or not nodes:
            raise ValueError("E_VERIFICATION_TOPOLOGY:collection:" + str(cwd))
        paths = {(cwd / node.split("::", 1)[0]).resolve() for node in nodes}
        for row in selected:
            if not any(
                any(
                    path == (cwd / op).resolve() or path.is_relative_to((cwd / op).resolve())
                    for op in row["operands"]
                )
                for path in paths
            ):
                raise ValueError("E_VERIFICATION_TOPOLOGY:uncollected-command:" + row["command_id"])
        observed.update(paths)
        evidence.append(
            {
                "commands": selected,
                "collection_argv": argv,
                "cwd": str(cwd),
                "nodeids": nodes,
                "exit_code": collected.returncode,
            }
        )

    for command_key, required_groups in (
        ("all_test_compile_command", ("clock", "security")),
        ("harness_compile_command", ("test-harness",)),
    ):
        row = mapped[topology[command_key]]
        argv = row["argv"]
        if (
            argv[:5] != ["pnpm", "--dir", "extension", "exec", "tsc"]
            or len(argv) != 7
            or argv[5] != "-p"
        ):
            raise ValueError("E_VERIFICATION_TOPOLOGY:compiler-command")
        compiler = runtime_root / "extension/node_modules/typescript/lib/tsc.js"
        check_argv = [str(_node_binary()), str(compiler), "-p", argv[6], "--listFilesOnly"]
        compiled = subprocess.run(  # noqa: S603 -- pinned compiler inventory, no emitted output.
            check_argv,
            cwd=runtime_root / "extension",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )  # noqa: S603
        paths = {
            Path(line).resolve() for line in compiled.stdout.splitlines() if line.endswith(".ts")
        }
        if compiled.returncode:
            raise ValueError("E_VERIFICATION_TOPOLOGY:compiler")
        shown_argv = [str(_node_binary()), str(compiler), "-p", argv[6], "--showConfig"]
        shown = subprocess.run(  # noqa: S603 -- fixed compiler configuration query.
            shown_argv,
            cwd=runtime_root / "extension",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if shown.returncode:
            raise ValueError("E_VERIFICATION_TOPOLOGY:compiler-config")
        parsed_config = json.loads(shown.stdout)
        options = parsed_config["compilerOptions"]
        root_dir = (runtime_root / "extension" / options["rootDir"]).resolve()
        out_dir = (runtime_root / "extension" / options["outDir"]).resolve()
        outputs = {}
        for filename in parsed_config["files"]:
            source_file = runtime_root / "extension" / filename
            try:
                outputs[source_file.resolve()] = out_dir / source_file.relative_to(
                    root_dir
                ).with_suffix(".js")
            except ValueError as error:
                raise ValueError("E_VERIFICATION_TOPOLOGY:compiler-root") from error
        scheduled = {
            (runtime_root / token).resolve()
            for name in identifiers
            for token in mapped[name]["argv"][1:]
            if mapped[name]["argv"][0] == "node" and token.endswith(".js")
        }
        for group in required_groups:
            required = {path for path in expected[group] if path.suffix == ".ts"}
            if not required <= paths:
                raise ValueError("E_VERIFICATION_TOPOLOGY:compiler-excluded:" + group)
            if group != "test-harness":
                entries = {
                    outputs[path]
                    for path in required
                    if path.name.endswith(".test.ts") and path in outputs
                }
                if not entries & scheduled:
                    raise ValueError("E_VERIFICATION_TOPOLOGY:unscheduled-typescript:" + group)
            observed.update(required)
        evidence.append(
            {
                "command_id": row["command_id"],
                "argv": argv,
                "inventory_argv": check_argv,
                "compiler_configuration": json.loads(shown.stdout),
                "node_commands": [
                    mapped[name] for name in identifiers if mapped[name]["argv"][0] == "node"
                ],
                "files": sorted(map(str, paths)),
                "exit_code": compiled.returncode,
            }
        )
    coverage = {}
    for group, group_files in expected.items():
        # Directory declarations require actual selected tests in each source,
        # not activation of inherited future-phase intentional failure tests.
        if any(not source & observed for source in source_groups[group]):
            raise ValueError("E_VERIFICATION_TOPOLOGY:uncovered:" + group)
        coverage[group] = sorted(map(str, group_files & observed))
    discovery = {"coverage": coverage, "observations": evidence}
    return {
        "result": "PASS",
        "group_count": len(groups),
        "command_count": len(identifiers),
        "discovery_evidence": discovery,
        "discovery_sha256": hashlib.sha256(
            json.dumps(discovery, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(verify_verification_topology(), sort_keys=True))
