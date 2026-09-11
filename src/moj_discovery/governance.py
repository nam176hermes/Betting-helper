import ast
import base64
import copy
import hashlib
import importlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from .canonical import parse_strict_json
from .evidence_semantics import EvidenceSemanticEvaluator
from .schema_formats import STRICT_FORMAT_CHECKER
from .semantic_vectors import (
    semantic_vector_error,
    validate_consumer_registry,
    validate_required_decision_registry,
    validate_scope_policy,
)
from .vendor import plan_root

VENDOR = Path("vendor/hybrid-discovery-v6.3.6")

DDL_TABLES = {
    "ack_cursors",
    "ack_outbox",
    "application_records",
    "authoritative_resnapshot_proofs",
    "authorization_consumptions",
    "clock_mapping_closures",
    "clock_mappings",
    "clock_observations",
    "coherence_controllers",
    "coherence_epochs",
    "coherence_transitions",
    "derived_revisions",
    "gap_epoch_bindings",
    "gap_records",
    "generation_transitions",
    "input_freshness_vectors",
    "raw_commits",
    "raw_conflicts",
    "reducer_cursors",
    "revocations",
    "run_meta",
    "shock_observations",
    "stream_generations",
}

IMMUTABLE_TABLES = DDL_TABLES - {"coherence_controllers", "run_meta", "stream_generations"}
EXECUTABLE_GRAPH_EDGES = [
    ["R0", "F0A"],
    ["F0A", "SEC0"],
    ["SEC0", "E0"],
    ["SEC0", "D0"],
    ["E0", "G0"],
    ["D0", "G0"],
    ["G0", "SCOPE0"],
    ["SCOPE0", "DISCOVERY_COMPLETE"],
]
FUTURE_GRAPH_EDGES = [
    ["F0B", "PLAN-B0"],
    ["PLAN-B0", "E1"],
    ["PLAN-B0", "E2"],
    ["PLAN-B0", "E3"],
    ["E1", "H0"],
    ["E2", "H0"],
    ["E3", "H0"],
    ["H0", "WDL-M0A"],
    ["H0", "MK0A"],
    ["WDL-M0A", "WDL-M0B"],
    ["WDL-M0B", "WDL-M0C"],
    ["WDL-M0C", "PLAN-K0"],
    ["MK0A", "PLAN-K0"],
    ["PLAN-K0", "P0"],
    ["P0", "UI"],
    ["UI", "V0A"],
    ["V0A", "X0"],
    ["X0", "O0"],
    ["O0", "V0B"],
    ["V0B", "A0"],
    ["V0B", "HERMES"],
    ["V0B", "L0"],
]
EXECUTABLE_GRAPH_NODES = [
    "R0",
    "F0A",
    "SEC0",
    "E0",
    "D0",
    "G0",
    "SCOPE0",
    "DISCOVERY_COMPLETE",
]
FUTURE_GRAPH_NODES = [
    "F0B",
    "PLAN-B0",
    "E1",
    "E2",
    "E3",
    "H0",
    "WDL-M0A",
    "WDL-M0B",
    "WDL-M0C",
    "MK0A",
    "PLAN-K0",
    "P0",
    "UI",
    "V0A",
    "X0",
    "O0",
    "V0B",
    "A0",
    "HERMES",
    "L0",
]


def _custody_symbol_forbidden(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    words = re.split(r"[^A-Za-z0-9]|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", name)
    return (
        "automaticbackup" in normalized
        or "automaticarchive" in normalized
        or "compact" in normalized
        or "rollingdelet" in normalized
        or ("retention" in normalized and "daemon" in normalized)
        or "automaticcleanup" in normalized
        or normalized.startswith("restore")
        or ("delete" in normalized and (
            "deleteack" in normalized or any(word.casefold().startswith("ack") for word in words)
        ))
    )


def validate_runtime_custody_prohibitions(root: Path | None = None) -> None:
    root = root or Path.cwd()
    source_roots = (root / "src", root / "tools", root / "extension/src")
    typescript: list[Path] = []
    for source_root in source_roots:
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".ts"}:
                continue
            if path.suffix == ".py":
                tree = ast.parse(path.read_text(), filename=str(path))
                symbols: Iterable[str] = (
                    node.id
                    if isinstance(node, ast.Name)
                    else node.attr
                    if isinstance(node, ast.Attribute)
                    else node.name
                    for node in ast.walk(tree)
                    if isinstance(
                        node,
                        (
                            ast.Name,
                            ast.Attribute,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                            ast.ClassDef,
                        ),
                    )
                )
            else:
                typescript.append(path)
                continue
            if any(_custody_symbol_forbidden(symbol) for symbol in symbols):
                raise AssertionError(f"E_CUSTODY_PATH_DENIED:{path.relative_to(root)}")
    if typescript:
        # Use the already pinned compiler: comments are not identifiers, and
        # template expressions still contain executable identifiers to inspect.
        node = shutil.which("node")
        assert node is not None, "E_CUSTODY_SOURCE_PARSE"
        script = """
const ts = require('typescript'), fs = require('node:fs');
const result = JSON.parse(fs.readFileSync(0, 'utf8')).map(([path, text]) => {
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  if (source.parseDiagnostics.length) throw new Error('E_CUSTODY_SOURCE_PARSE');
  const symbols = [];
  function visit(node) {
    if (ts.isIdentifier(node)) symbols.push(node.text);
    else if (ts.isStringLiteralLike(node) || ts.isTemplateLiteralToken(node)) {
      symbols.push(...(node.text.match(/[$A-Za-z_][$0-9A-Za-z_]*/g) || []));
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return symbols;
});
process.stdout.write(JSON.stringify(result));
"""
        try:
            result = subprocess.run(  # noqa: S603 -- fixed parser; scanned code is never executed.
                [node, "-e", script],
                cwd=Path(__file__).resolve().parents[2] / "extension",
                input=json.dumps([(str(path), path.read_text()) for path in typescript]),
                text=True, capture_output=True, check=True, timeout=30,
            )
            parsed = json.loads(result.stdout)
            assert isinstance(parsed, list) and len(parsed) == len(typescript)
            for path, names in zip(typescript, parsed, strict=True):
                assert isinstance(names, list) and all(isinstance(name, str) for name in names)
                if any(_custody_symbol_forbidden(name) for name in names):
                    raise AssertionError(f"E_CUSTODY_PATH_DENIED:{path.relative_to(root)}")
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise AssertionError("E_CUSTODY_SOURCE_PARSE") from error


def validate_graph_partition(vendor: Path = VENDOR) -> None:
    executable = json.loads((vendor / "graphs/executable-discovery-graph.v1.json").read_text())
    future = json.loads((vendor / "graphs/non-authoritative-future-roadmap.v1.json").read_text())
    assert isinstance(executable, dict) and set(executable) == {
        "edges",
        "graph_type",
        "nodes",
        "schema_version",
        "terminal",
    }
    assert isinstance(future, dict) and set(future) == {
        "authority",
        "auto_activate",
        "edges",
        "executable",
        "graph_type",
        "may_start",
        "nodes",
        "schema_version",
    }
    assert executable["schema_version"] == "v1" and future["schema_version"] == "v1"
    assert executable["nodes"] == EXECUTABLE_GRAPH_NODES
    assert isinstance(future["nodes"], list)
    assert all(isinstance(node, dict) for node in future["nodes"])
    future_node_ids = [node["node_id"] for node in future["nodes"]]
    assert future_node_ids == FUTURE_GRAPH_NODES
    assert len(future_node_ids) == len(set(future_node_ids))
    executable_ids = set(EXECUTABLE_GRAPH_NODES)
    future_ids = set(future_node_ids)
    assert executable["graph_type"] == "EXECUTABLE_DISCOVERY_GRAPH"
    assert executable["terminal"] == "DISCOVERY_COMPLETE"
    assert future["graph_type"] == "NON_AUTHORITATIVE_FUTURE_ROADMAP"
    assert future["authority"] == "NONE" and future["executable"] is False
    assert future["may_start"] is False and future["auto_activate"] is False
    expected_stamp = {
        "graph_type": "NON_AUTHORITATIVE_FUTURE_ROADMAP",
        "executable": False,
        "authority": "NONE",
        "may_start": False,
        "auto_activate": False,
    }
    for node in future["nodes"]:
        assert set(node) == {"node_id", *expected_stamp}
        assert all(node[key] == value for key, value in expected_stamp.items())
    assert executable_ids.isdisjoint(future_ids)
    assert executable["edges"] == EXECUTABLE_GRAPH_EDGES
    assert future["edges"] == FUTURE_GRAPH_EDGES
    _validate_graph_edges(executable_ids, executable["edges"])
    _validate_graph_edges(future_ids, future["edges"])
    assert not any(endpoint in future_ids for edge in executable["edges"] for endpoint in edge)
    assert not any(endpoint in executable_ids for edge in future["edges"] for endpoint in edge)


def _validate_graph_edges(nodes: set[str], edges: list[list[str]]) -> None:
    assert all(len(edge) == 2 and set(edge) <= nodes for edge in edges)
    incoming = {node: 0 for node in nodes}
    outgoing: dict[str, set[str]] = {node: set() for node in nodes}
    for source, target in edges:
        assert target not in outgoing[source]
        outgoing[source].add(target)
        incoming[target] += 1
    ready = [node for node, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for target in outgoing[source]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    assert visited == len(nodes)


def validate_task_dependencies(
    manifest_path: Path | None = None,
) -> None:
    runtime = Path(__file__).resolve().parents[2]
    manifest_path = manifest_path or plan_root(runtime) / "docs/tasks/task-manifest.v6.3.6.json"
    manifest = json.loads(manifest_path.read_text())
    tasks = manifest["tasks"]
    assert manifest["declared_task_count"] == 62 and len(tasks) == 62
    seen: set[str] = set()
    for task in tasks:
        task_id = task["task_id"]
        assert isinstance(task_id, str) and task_id not in seen
        assert set(task["dependencies"]) <= seen
        seen.add(task_id)
    assert len(seen) == 62


def validate_capability_artifacts(vendor: Path = VENDOR) -> None:
    manifest = json.loads((vendor / "security/discovery-capability-manifest.v1.json").read_text())
    vectors = json.loads((vendor / "vectors/capability-negative-v1.json").read_text())
    chrome = manifest["chrome_manifest"]
    assert chrome["manifest_version"] == 3
    assert chrome["minimum_chrome_version"] == "116"
    assert chrome["permissions"] == [
        "activeTab",
        "debugger",
        "scripting",
        "unlimitedStorage",
        "webNavigation",
    ]
    for field in (
        "optional_permissions",
        "host_permissions",
        "optional_host_permissions",
        "content_scripts",
        "web_accessible_resources",
    ):
        assert chrome[field] == []
    assert "externally_connectable" not in chrome
    assert manifest["production_authority"] == "NONE"
    assert manifest["body_classes"] == []
    assert manifest["network_get_response_body_present"] is False
    assert [command["method"] for command in manifest["cdp_commands"]] == [
        "Network.enable",
        "Network.disable",
    ]
    assert manifest["cdp_commands"][1]["parameters"] == {}
    assert manifest["target_policy"]["target_types"] == ["page"]
    assert manifest["target_policy"]["max_targets"] == 1
    assert manifest["target_policy"]["max_frames"] == 32
    assert manifest["target_policy"]["recursive_attachment"] == "DENY"
    assert manifest["loopback"]["url"] == "ws://127.0.0.1:8765"
    assert manifest["loopback"]["command_channel"] is False
    assert len(manifest["public_messages"]) == 5
    assert len(manifest["private_operations"]) == 7
    assert len(manifest["fixed_probes"]) == 2
    assert all(
        probe["arguments"] == []
        and probe["selectors"] == []
        and probe["script_or_expression_input"] is False
        for probe in manifest["fixed_probes"]
    )
    negative = vectors["vectors"]
    assert [vector["vector_id"] for vector in negative] == [
        f"CAP-NEG-{index:03d}" for index in range(1, 79)
    ]
    assert all(vector["expected_result"] == "BUILD_REJECTED" for vector in negative)
    positive = vectors["required_allowed_controls"]
    assert [control["control_id"] for control in positive] == [
        f"CAP-POS-{index:03d}" for index in range(1, 8)
    ]
    escape_cases = {vector["escape_case"] for vector in negative}
    assert set(manifest["negative_escape_cases"]) <= escape_cases
    assert vectors["production_authority"] == "NONE"
    lock = json.loads((vendor / "security/cdp-protocol-lock.v1.json").read_text())
    for item in lock["files"]:
        path = vendor / "cdp" / item["path"]
        assert path.stat().st_size == item["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def validate_canonical_registry(vendor: Path = VENDOR, runtime_root: Path | None = None) -> None:
    registry = parse_strict_json(
        (vendor / "registries/canonical-hash-domains.v1.json").read_bytes()
    )
    vectors = parse_strict_json((vendor / "vectors/canonical-hashing-v1.json").read_bytes())
    assert isinstance(registry, dict) and isinstance(vectors, dict)
    assert registry["schema_version"] == "canonical-hash-domains/v1"
    assert registry["algorithm_id"] == "HD-JCS-SHA256-v1"
    assert registry["closed_world"] is True
    assert registry["production_authority"] == "NONE"
    domains = registry["domains"]
    assert isinstance(domains, list) and len(domains) == 83
    assert all(isinstance(domain, dict) for domain in domains)
    domain_by_type = {domain["artifact_type"]: domain for domain in domains}
    assert len(domain_by_type) == 83
    for artifact_type, domain in domain_by_type.items():
        assert domain["domain_version"] == "v1"
        assert domain["domain"] == f"HYBRID-DISCOVERY/v6.2/{artifact_type}/v1\0"
        exclusions = domain["excluded_json_pointers"]
        assert isinstance(exclusions, list) and len(exclusions) == len(set(exclusions))
        assert all(
            isinstance(pointer, str)
            and re.fullmatch(r"/(?:[^/~]|~[01])+", pointer) is not None
            and "*" not in pointer
            for pointer in exclusions
        )

    classes = registry["domain_validation_classes"]
    assert isinstance(classes, list) and len(classes) == 2
    class_by_id = {entry["class_id"]: entry for entry in classes}
    assert set(class_by_id) == {"SCHEMA_GATED_SELF_HASH", "GOVERNED_NO_EXCLUSION"}
    gated = set(class_by_id["SCHEMA_GATED_SELF_HASH"]["artifact_types"])
    governed = set(class_by_id["GOVERNED_NO_EXCLUSION"]["artifact_types"])
    assert len(gated) == class_by_id["SCHEMA_GATED_SELF_HASH"]["expected_count"] == 65
    assert len(governed) == class_by_id["GOVERNED_NO_EXCLUSION"]["expected_count"] == 18
    assert gated.isdisjoint(governed) and gated | governed == set(domain_by_type)
    assert gated == {
        artifact_type
        for artifact_type, domain in domain_by_type.items()
        if domain["excluded_json_pointers"]
    }
    assert governed == set(domain_by_type) - gated
    subclasses = class_by_id["GOVERNED_NO_EXCLUSION"]["subclasses"]
    assert isinstance(subclasses, list) and len(subclasses) == 2
    subclass_by_id = {entry["subclass_id"]: set(entry["artifact_types"]) for entry in subclasses}
    assert set(subclass_by_id) == {"STATIC_PACK_ASSET", "GOLDEN_OR_CURSOR_VECTOR_INPUT"}
    assert len(subclass_by_id["STATIC_PACK_ASSET"]) == 11
    assert len(subclass_by_id["GOLDEN_OR_CURSOR_VECTOR_INPUT"]) == 7
    assert subclass_by_id["STATIC_PACK_ASSET"].isdisjoint(
        subclass_by_id["GOLDEN_OR_CURSOR_VECTOR_INPUT"]
    )
    assert set().union(*subclass_by_id.values()) == governed

    bindings = registry["no_exclusion_validation_bindings"]
    assert isinstance(bindings, list) and len(bindings) == 18
    assert {binding["artifact_type"] for binding in bindings} == governed
    command_ids = _current_command_ids(vendor, runtime_root)
    historical_command_ids, obligations = _historical_command_obligations(vendor)
    bound_historical_ids: set[str] = set()
    for binding in bindings:
        source = _runtime_vendor_path(vendor, binding["canonical_source_path"])
        assert source.is_file()
        bound_historical_ids.update(binding["command_ids"])
        vector_binding = binding.get("vector_binding")
        if vector_binding is not None:
            vector_path = _runtime_vendor_path(vendor, vector_binding["vector_path"])
            vector_data = parse_strict_json(vector_path.read_bytes())
            assert set(vector_binding["vector_ids"]) <= _artifact_ids(vector_data)
        schema_binding = binding.get("schema_binding")
        if schema_binding is not None:
            _resolve_schema_binding(vendor, schema_binding)
        for symbol in binding["verifier_symbols"]:
            _assert_verifier_symbol(symbol)
    assert len(bound_historical_ids) == 12
    assert set(obligations) == bound_historical_ids <= historical_command_ids
    for successor_ids in obligations.values():
        assert successor_ids and len(successor_ids) == len(set(successor_ids))
        assert set(successor_ids) <= command_ids

    groups = registry["schema_binding_groups"]
    assert isinstance(groups, list)
    group_types = {artifact_type for group in groups for artifact_type in group["artifact_types"]}
    assert group_types == gated
    assert sum(group["source_kind"] == "CLOSED_JSON_SCHEMA" for group in groups) == 12
    assert (
        sum(
            len(group["artifact_types"])
            for group in groups
            if group["source_kind"] == "CLOSED_JSON_SCHEMA"
        )
        == 63
    )
    assert (
        sum(
            len(group["artifact_types"])
            for group in groups
            if group["source_kind"] == "TEST_ONLY_CLOSED_VECTOR_SCHEMA"
        )
        == 2
    )
    for group in groups:
        for artifact_type in group["artifact_types"]:
            assert (
                domain_by_type[artifact_type]["excluded_json_pointers"]
                == group["required_excluded_json_pointers"]
            )
        if group["source_kind"] == "CLOSED_JSON_SCHEMA":
            _resolve_schema_binding(vendor, group)
        else:
            assert group["source_kind"] == "TEST_ONLY_CLOSED_VECTOR_SCHEMA"
            assert _runtime_vendor_path(vendor, group["vector_path"]).is_file()
    exclusions = [pointer for domain in domains for pointer in domain["excluded_json_pointers"]]
    assert exclusions.count("/content_hash") == 63
    assert exclusions.count("/approval_hash") == 1
    assert exclusions.count("/revocation_hash") == 1
    assert exclusions.count("/signature") == 6
    assert {"BuildManifest", "PackManifest"}.isdisjoint(domain_by_type)
    consistency = vectors["registry_schema_consistency_vectors"]
    assert consistency["valid_vector"]["expected_counts"] == {
        "registered_domains": 83,
        "domains_with_exclusions": 65,
        "schema_gated_self_hash_domains": 65,
        "governed_no_exclusion_domains": 18,
        "static_pack_asset_domains": 11,
        "golden_or_cursor_vector_input_domains": 7,
        "no_exclusion_validation_bindings": 18,
        "schema_bound_domains": 63,
        "test_only_vector_schema_bound_domains": 2,
        "content_hash_self_hash_domains": 63,
        "approval_hash_self_hash_domains": 1,
        "revocation_hash_self_hash_domains": 1,
        "signature_excluded_domains": 6,
        "non_hd_jcs_manifest_hash_artifacts": 2,
    }
    assert len(consistency["invalid_vectors"]) == 9


def _current_command_ids(vendor: Path, runtime_root: Path | None) -> set[str]:
    root = runtime_root or vendor.parents[1]
    root_registry_path = root / "task-command-registry.json"
    vendor_registry_path = vendor / "docs/registries/task-command-registry.v1.json"
    root_bytes = root_registry_path.read_bytes()
    assert root_bytes == vendor_registry_path.read_bytes()
    registry = parse_strict_json(root_bytes)
    schema = parse_strict_json((vendor / "docs/schemas/command-registry.schema.json").read_bytes())
    assert isinstance(registry, dict) and isinstance(schema, dict)
    validator = Draft202012Validator(
        {"$ref": "#/$defs/CommandRegistry", "$defs": schema["$defs"]},
        format_checker=STRICT_FORMAT_CHECKER,
    )
    assert next(validator.iter_errors(registry), None) is None
    commands = registry["commands"]
    assert isinstance(commands, list)
    command_ids = [entry["command_id"] for entry in commands if isinstance(entry, dict)]
    assert len(command_ids) == len(commands) == len(set(command_ids))
    assert all(isinstance(command_id, str) for command_id in command_ids)
    return set(command_ids)


def _historical_command_obligations(vendor: Path) -> tuple[set[str], dict[str, list[str]]]:
    inherited = parse_strict_json(
        (vendor / "docs/registries/inherited-baseline-qualification.v1.json").read_bytes()
    )
    assert isinstance(inherited, dict)
    fixtures = inherited["fixtures"]
    assert isinstance(fixtures, list)
    matches = [
        fixture
        for fixture in fixtures
        if isinstance(fixture, dict)
        and fixture.get("runtime_vendor_relative")
        == "docs/fixtures/inherited/v6.2/task-command-registry.json"
    ]
    assert len(matches) == 1
    fixture = matches[0]
    assert fixture["classification"] == "IMMUTABLE_TEST_DATA_NEVER_EXECUTABLE"
    fixture_path = vendor / str(fixture["runtime_vendor_relative"])
    fixture_bytes = fixture_path.read_bytes()
    assert len(fixture_bytes) == fixture["size"]
    assert hashlib.sha256(fixture_bytes).hexdigest() == fixture["sha256"]
    historical = parse_strict_json(fixture_bytes)
    assert isinstance(historical, dict)
    entries = historical["verification_commands"]
    assert isinstance(entries, list)
    historical_ids = [entry["command_id"] for entry in entries if isinstance(entry, dict)]
    assert len(historical_ids) == len(entries) == len(set(historical_ids))
    assert all(isinstance(command_id, str) for command_id in historical_ids)

    rows = inherited["inherited_command_obligations"]
    assert isinstance(rows, list) and len(rows) == 12
    obligations: dict[str, list[str]] = {}
    for row in rows:
        assert isinstance(row, dict)
        inherited_id = row["inherited_command_id"]
        successor_ids = row["successor_command_ids"]
        assert (
            isinstance(inherited_id, str)
            and inherited_id not in obligations
            and isinstance(successor_ids, list)
            and all(isinstance(command_id, str) for command_id in successor_ids)
            and row["role"] == "COVERAGE_MAPPING_ONLY_NOT_EXECUTION_ALIAS"
        )
        obligations[inherited_id] = successor_ids
    return set(historical_ids), obligations


def _runtime_vendor_path(vendor: Path, canonical_path: object) -> Path:
    assert isinstance(canonical_path, str) and canonical_path.startswith("docs/")
    runtime_path = vendor / canonical_path.removeprefix("docs/")
    return runtime_path if runtime_path.exists() else vendor / canonical_path


def _artifact_ids(value: object) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and (key == "id" or key.endswith("_id")):
                ids.add(child)
            ids.update(_artifact_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.update(_artifact_ids(child))
    return ids


def _resolve_schema_binding(vendor: Path, binding: dict[str, object]) -> None:
    schema_path = _runtime_vendor_path(vendor, binding["schema_path"])
    schema = parse_strict_json(schema_path.read_bytes())
    assert isinstance(schema, dict)
    assert schema["$id"] == binding["schema_id"]
    fragment = binding.get("schema_fragment")
    if fragment is not None:
        assert isinstance(fragment, str)
        registry = _published_schema_registry(vendor)
        registry.resolver(str(binding["schema_id"])).lookup(fragment)


def _assert_verifier_symbol(symbol: object) -> None:
    assert isinstance(symbol, str)
    if "#" in symbol:
        path_value, name = symbol.split("#", 1)
        path = Path(path_value)
        assert path.is_file()
        assert re.search(rf"\b{re.escape(name)}\b", path.read_text()) is not None
        return
    module_name, _, name = symbol.rpartition(".")
    assert module_name and name and hasattr(importlib.import_module(module_name), name)


def validate_schema_closure(vendor: Path = VENDOR) -> None:
    schemas: list[tuple[str, dict[str, object]]] = []
    for path in sorted((vendor / "schemas").glob("*.json")):
        schema = parse_strict_json(path.read_bytes())
        assert isinstance(schema, dict)
        schema_id = schema["$id"]
        assert isinstance(schema_id, str)
        schemas.append((schema_id, schema))
        Draft202012Validator.check_schema(schema)
        assert not any(value.get("additionalProperties") is True for value in _objects(schema))
    assert schemas
    registry = Registry().with_resources(
        (schema_id, Resource.from_contents(schema)) for schema_id, schema in schemas
    )
    for schema_id, schema in schemas:
        resolver = registry.resolver(schema_id)
        for value in _objects(schema):
            reference = value.get("$ref")
            if reference is not None:
                assert isinstance(reference, str)
                resolver.lookup(reference)


def _objects(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def validate_authorization_vectors(vendor: Path = VENDOR) -> None:
    # Keep this bootstrap verifier separate from any future authorization runtime.
    # It recomputes schema, trust, semantic, binding, time, replay, and precedence outcomes.
    from .authorization_semantics import validate_authorization_semantics

    validate_authorization_semantics(vendor)


def validate_ddl(vendor: Path = VENDOR) -> None:
    with tempfile.TemporaryDirectory(prefix="discovery-ddl-") as temporary:
        connection = sqlite3.connect(Path(temporary) / "store.sqlite")
        try:
            connection.executescript((vendor / "sql/discovery-store-v1.sql").read_text())
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            assert tables == DDL_TABLES
            strict_tables = {
                row[1]
                for row in connection.execute("PRAGMA table_list")
                if row[2] == "table" and not row[1].startswith("sqlite_") and row[5] == 1
            }
            assert strict_tables == DDL_TABLES
            assert connection.execute(
                "SELECT count(*) FROM sqlite_schema WHERE type='index'"
            ).fetchone() == (68,)
            triggers = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='trigger'")
            }
            assert len(triggers) == 59
            for table in IMMUTABLE_TABLES:
                assert f"{table}_no_update" in triggers
                assert f"{table}_no_delete" in triggers
            pragma_expectations: dict[str, int | str] = {
                "page_size": 4096,
                "journal_mode": "delete",
                "synchronous": 2,
                "foreign_keys": 1,
                "trusted_schema": 0,
                "temp_store": 2,
                "auto_vacuum": 0,
                "busy_timeout": 5000,
                "max_page_count": 32768,
                "user_version": 1,
            }
            for pragma, expected in pragma_expectations.items():
                assert connection.execute(f"PRAGMA {pragma}").fetchone() == (expected,)
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            connection.close()
    validate_durability_vectors(vendor)


def validate_durability_vectors(vendor: Path = VENDOR) -> None:
    vectors = json.loads((vendor / "vectors/durability-crash-v1.json").read_text())
    assert vectors["guarantee"] == "EFFECTIVELY_ONCE_AFTER_DURABLE_LOCAL_SPOOL_COMMIT"
    assert vectors["normal_transaction_order"] == [
        "raw_commits",
        "application_records",
        "derived_revisions",
        "reducer_cursors",
        "ack_outbox",
    ]
    assert len(vectors["gap_transaction_order"]) == 8
    assert vectors["cursor_chain"] == {
        "seed_domain": "HYBRID-DISCOVERY/v6.2/CursorSeed/v1\0",
        "step_domain": "HYBRID-DISCOVERY/v6.2/CursorStep/v1\0",
        "H0": "149300a0e3954885a1d6c0f13a9d1101227cc21cce37bd6b7c72eab641741c0c",
        "H1": "739669d828057e94c856e7725ed05218e26639610d4ce58c2a5568244a16fc28",
    }
    cases = vectors["cases"]
    assert len(cases) == 46
    assert len({case["id"] for case in cases}) == 46
    harness = vectors["harness_contract"]
    assert harness["sql_crash_injection"] == "KILL_REAL_CHILD_PROCESS_WITH_SIGKILL"
    assert harness["python_exception_is_sufficient"] is False
    assert harness["restart_each_case_with_new_process"] is True
    assert harness["unlisted_sql_table_delta"] == 0
    assert harness["commit_boundary_rule"] == "ONLY_PRECOMMIT_OR_FULLY_COMMITTED_STATE_IS_ALLOWED"
    sql_negatives = vectors["sql_negative_vectors"]
    assert len(sql_negatives) == 14
    assert {vector["expected_error"] for vector in sql_negatives} == {
        "E_CURSOR_FIRST_STEP_NOT_H0",
        "E_CURSOR_PREDECESSOR_LINK",
        "E_ACK_WITHOUT_DURABLE_CHAIN",
        "E_ACK_REGRESSION",
        "E_GENERATION_CLOSE_WITHOUT_COHERENCE_CLOSURE",
        "E_GENERATION_OPEN_WITHOUT_COHERENCE_CLOSURE",
        "E_DESTRUCTION_AUTHORITY_RUN",
        "E_DESTRUCTION_AUTHORITY_HASH",
        "E_DESTRUCTION_AUTHORITY_TYPE",
        "E_DESTRUCTION_AUTHORITY_SCOPE",
        "E_DESTRUCTION_AUTHORITY_REQUIRED",
        "E_DESTRUCTION_AUTHORITY_REPLAY",
        "E_DESTRUCTION_INTENT_PRECOMMIT",
    }
    contract = vectors["destruction_authority_contract"]
    assert contract["receipt_record_type"] == "GateReceipt"
    assert contract["gate_kind"] == "EVIDENCE_EXPORT_ACCEPTED"
    assert contract["scope"] == "WHOLE_RUN_DESTRUCTION_AFTER_ACCEPTED_EXPORT"
    assert contract["one_use"] is True
    assert contract["explicit_human_invocation"] is True
    assert contract["automatic_trigger"] is False
    assert contract["pre_intent_crash_rule"] == (
        "CONSUMED_RECEIPT_REMAINS_PERMANENTLY_BURNED_STORES_REMAIN_INTACT_AND_RECOVERY_"
        "MAY_ONLY_REVALIDATE_THE_SAME_RECEIPT_BYTES_TO_RECONSTRUCT_THE_BYTE_IDENTICAL_"
        "PRECOMMITTED_EXTERNAL_INTENT_WITHOUT_SECOND_CONSUMPTION_OR_NEW_AUTHORITY"
    )
    assert contract["external_intent_gate"] == (
        "DESTRUCTION_PENDING_AND_STORE_DELETE_REQUIRE_PERSISTED_EXTERNAL_INTENT_BYTES_"
        "MATCHING_THE_IMMUTABLE_PRECOMMIT"
    )
    assert len(vectors["destruction_authority_negative_vectors"]) == 7
    assert len(vectors["authorization_consumption_positive_vectors"]) == 5
    reconstruction = vectors["destruction_intent_reconstruction_vector"]
    assert reconstruction["expected_content_hash"] == (
        "d78555bc433052db4b9d6840857e066429cb538b8f814b567393c973335755ca"
    )
    assert reconstruction["recovery_rule"] == (
        "REVALIDATE_SAME_RECEIPT_BYTES_AS_DATA_ONLY_RECONSTRUCT_BYTE_IDENTICAL_INTENT_"
        "NO_SECOND_CONSUMPTION_NO_NEW_AUTHORITY"
    )
    crash = next(
        case for case in cases if case["id"] == "DESTROY-01A-AFTER-CONSUMPTION-BEFORE-INTENT"
    )
    expected = crash["expected"]
    assert expected["indexeddb_store"] == "PRESENT"
    assert expected["backend_database"] == "PRESENT"
    assert expected["run_status"] == "CLOSED"
    assert expected["receipt_state"] == "CONSUMED_ONE_USE_PERMANENTLY_BURNED"
    assert expected["second_authorization_consumption_allowed"] is False
    assert expected["new_authority_required"] is False
    expected_case_ids = {
        "IDB-01-BEFORE-TRANSACTION",
        "IDB-02-DURING-SEQUENCE-ALLOCATION",
        "IDB-03-DURING-ROW-PUT",
        "IDB-04-AFTER-COMMIT",
        "SEND-01-AFTER-SEND-BEFORE-BACKEND-BEGIN",
        *{
            f"SQL-{index:02d}-{suffix}"
            for index, suffix in (
                (1, "AFTER-RAW-COMMIT-STATEMENT"),
                (2, "AFTER-APPLICATION-STATEMENT"),
                (3, "AFTER-DERIVED-REVISION-STATEMENT"),
                (4, "AFTER-REDUCER-CURSOR-STATEMENT"),
                (5, "AFTER-ACK-OUTBOX-STATEMENT"),
                (6, "DURING-COMMIT"),
                (7, "AFTER-COMMIT-BEFORE-ACK-SEND"),
            )
        },
        *{
            f"ACK-{index:02d}-{suffix}"
            for index, suffix in (
                (1, "BEFORE-EXTENSION-ACK-TRANSACTION"),
                (2, "DURING-EXTENSION-ACK-TRANSACTION"),
                (3, "AFTER-EXTENSION-ACK-TRANSACTION"),
                (4, "BEFORE-BACKEND-CONFIRMATION-COMMIT"),
                (5, "AFTER-BACKEND-CONFIRMATION-COMMIT"),
                (6, "DUPLICATE-IDENTICAL"),
            )
        },
        *{
            f"GAP-{index:02d}-{suffix}"
            for index, suffix in (
                (1, "AFTER-GAP-INSERT"),
                (2, "AFTER-SHOCK-INSERT"),
                (3, "AFTER-COHERENCE-TRANSITION"),
                (4, "AFTER-CONTROLLER-CLOSE"),
                (5, "AFTER-EPOCH-BINDING"),
                (6, "AFTER-PREDECESSOR-CLOSE"),
                (7, "AFTER-GENERATION-TRANSITION"),
                (8, "AFTER-SUCCESSOR-INSERT"),
                (9, "DURING-COMMIT"),
                (10, "AFTER-COMMIT"),
                (11, "REPEATED-GAP-IN-SUCCESSOR"),
            )
        },
        "CONFLICT-01-SAME-POSITION-DIFFERENT-HASH",
        "LATE-01-MISSING-POSITION-AFTER-GAP",
        "CAPACITY-01-NORMAL-LIMIT-REACHED",
        "CLOCK-01-AFTER-MAPPING-CLOSURE-INSERT",
        "CLOCK-02-AFTER-CLOSURE-COMMIT-BEFORE-SHOCK",
        *{
            f"EPOCH-{index:02d}-{suffix}"
            for index, suffix in (
                (1, "AFTER-SHOCK-BEFORE-CLOSE-COMMIT"),
                (2, "AFTER-SHOCK-CLOSE-COMMIT"),
                (3, "AFTER-PENDING-WRITES-BEFORE-COMMIT"),
                (4, "DURING-NEW-EPOCH-OPEN-COMMIT"),
                (5, "NEW-SHOCK-WHILE-PENDING"),
            )
        },
        "DESTROY-01-BEFORE-AUTHORITY",
        "DESTROY-01A-AFTER-CONSUMPTION-BEFORE-INTENT",
        *{
            f"DESTROY-{index:02d}-{suffix}"
            for index, suffix in (
                (2, "AFTER-INTENT-BEFORE-DELETION"),
                (3, "AFTER-EXTENSION-DELETION"),
                (4, "AFTER-BACKEND-DELETION"),
                (5, "AFTER-BOTH-DELETIONS-BEFORE-PROOF"),
                (6, "AFTER-PROOF"),
            )
        },
    }
    assert {case["id"] for case in cases} == expected_case_ids
    for case in cases:
        assert set(case) == {"id", "boundary", "kill", "expected"}, case["id"]
        assert case["boundary"] and case["kill"]
        observed = case["expected"]
        assert isinstance(observed, dict), case["id"]
        outcomes = observed.get("allowed_atomic_outcomes")
        if outcomes is not None:
            assert len(outcomes) == 2, case["id"]
            assert outcomes[0] != outcomes[1], case["id"]
            for outcome in outcomes:
                assert outcome["recovery_action"], case["id"]
                assert "reducer_cursor" in outcome or "reducer_cursor" in observed
                assert "backend_ack" in outcome or "backend_ack" in observed
                assert "coherence_state" in outcome or "coherence_state" in observed
                deltas = outcome["sql_row_deltas"]
                assert all(value >= 0 for value in deltas.values()), case["id"]
        else:
            assert observed["recovery_action"], case["id"]
            assert "reducer_cursor" in observed, case["id"]
            assert "backend_ack" in observed, case["id"]
            assert "coherence_state" in observed, case["id"]
        assert "extension_ack" in observed, case["id"]
        deltas = observed.get("sql_row_deltas")
        if isinstance(deltas, dict):
            assert all(value >= 0 for value in deltas.values()), case["id"]
        if case["id"].startswith("GAP-0") and case["id"] < "GAP-09":
            assert all(value == 0 for value in observed["sql_row_deltas"].values())
            assert observed["coherence_state"] == "OPEN"
        if case["id"] == "DESTROY-06-AFTER-PROOF":
            assert observed["indexeddb_store"] == "DELETED"
            assert observed["backend_database"] == "DELETED"
            assert observed["external_proof_delta"] == 1


def validate_clock_vectors(vendor: Path = VENDOR) -> None:
    vectors = json.loads((vendor / "vectors/clock-coherence-v1.json").read_text())
    contract = vectors["four_timestamp_contract"]
    assert contract == {
        "t1": "SOURCE_IMMEDIATELY_BEFORE_PING",
        "t2": "TARGET_IMMEDIATELY_AFTER_AUTHENTICATED_RECEIPT",
        "t3": "TARGET_IMMEDIATELY_BEFORE_PONG",
        "t4": "SOURCE_IMMEDIATELY_AFTER_AUTHENTICATED_VALIDATION",
        "offset_sign": "THETA_EQUALS_TARGET_CLOCK_MINUS_SOURCE_CLOCK",
        "raw_lower": "t3-t4",
        "raw_upper": "t2-t1",
        "network_rtt": "(t4-t1)-(t3-t2)",
        "padding": "source_resolution+target_resolution",
        "offset_lower": "raw_lower-padding",
        "offset_upper": "raw_upper+padding",
        "offset_midpoint": "(offset_lower+offset_upper)/2",
        "base_uncertainty": "(offset_upper-offset_lower)/2",
        "drift_us": "ceil(relative_drift_ppm*abs(x-source_anchor_us)/1000000)",
    }
    value = vectors["golden_mapping"]
    expected = value["expected"]
    raw_lower = value["t3"] - value["t4"]
    raw_upper = value["t2"] - value["t1"]
    rtt = (value["t4"] - value["t1"]) - (value["t3"] - value["t2"])
    padding = value["source"]["resolution_us"] + value["target"]["resolution_us"]
    lower, upper = raw_lower - padding, raw_upper + padding
    assert expected == {
        "raw_lower_us": raw_lower,
        "raw_upper_us": raw_upper,
        "network_rtt_us": rtt,
        "padding_us": padding,
        "offset_interval_us": [lower, upper],
        "offset_midpoint_us": lower + (upper - lower) // 2,
        "base_uncertainty_us": (upper - lower) // 2,
        "accepted": True,
    }
    assert vectors["guardrails"] == {
        "sample_period_us": 1_000_000,
        "sample_window_count": 32,
        "minimum_valid_samples": 8,
        "max_network_rtt_us": 250_000,
        "max_base_uncertainty_us": 125_000,
        "relative_drift_ppm": 100,
        "max_mapping_segment_age_us": 30_000_000,
        "wall_step_tolerance_us": 1_000_000,
    }
    state_machine = vectors["coherence_state_machine"]
    assert state_machine["states"] == [
        "OPEN",
        "SHOCKED_CLOSED",
        "WAITING_FOR_RESNAPSHOT",
        "NEW_EPOCH_PENDING",
        "NEW_EPOCH_OPEN",
    ]
    assert state_machine["required_path"] == [
        "OPEN->SHOCKED_CLOSED",
        "SHOCKED_CLOSED->WAITING_FOR_RESNAPSHOT",
        "WAITING_FOR_RESNAPSHOT->NEW_EPOCH_PENDING",
        "NEW_EPOCH_PENDING->NEW_EPOCH_OPEN",
    ]
    assert state_machine["pending_shock_path"] == "NEW_EPOCH_PENDING->WAITING_FOR_RESNAPSHOT"
    assert all(vector["permanent"] for vector in vectors["closure_vectors"][:10])
    assert all(
        vector["reopen_attempt_error"] == "E_MAPPING_PERMANENTLY_CLOSED"
        for vector in vectors["closure_vectors"][:10]
    )
    for vector in vectors["drift_vectors"]:
        calculated = math.ceil(
            vector["relative_drift_ppm"] * abs(vector["x"] - vector["source_anchor_us"]) / 1_000_000
        )
        assert calculated == vector["expected_drift_us"]
    for vector in vectors["mapping_selection_vectors"]:
        selected = min(
            vector["candidates"],
            key=lambda candidate: (
                candidate["width_us"],
                -candidate["valid_from_us"],
                candidate["mapping_id"],
            ),
        )
        assert selected["mapping_id"] == vector["expected_mapping_id"]
    assert {vector["id"] for vector in vectors["candidate_acceptance_negative_vectors"]} == {
        "CANDIDATE-NEG-01-JSON-UNKNOWN",
        "CANDIDATE-NEG-02-SQL-UNKNOWN",
        "CANDIDATE-NEG-03-NOT-OBSERVED",
        "CANDIDATE-NEG-04-UNSIGNED-UNVERIFIED",
    }
    assert all(
        vector["expected_state"] == "WAITING_FOR_RESNAPSHOT"
        for vector in vectors["candidate_acceptance_negative_vectors"]
    )
    positive = vectors["release_positive_vector"]
    assert positive["proof_bound_mappings_open_unclosed_valid_at_release"] is True
    assert positive["freshness_bindings_valid_at_release"] is True
    assert positive["continuity_bindings_valid_at_release"] is True
    assert positive["expected_transition"] == "NEW_EPOCH_PENDING->NEW_EPOCH_OPEN"
    assert len(vectors["release_negative_vectors"]) == 19
    mapping_closed = next(
        vector
        for vector in vectors["release_negative_vectors"]
        if vector["id"] == "RELEASE-NEG-09-MAPPING-CLOSED"
    )
    assert mapping_closed["expected_state"] == "NEW_EPOCH_PENDING"
    assert mapping_closed["expected_sql_error"] == "E_RELEASE_BINDING"

    allowed_transitions = {
        ("OPEN", "SHOCK"): "SHOCKED_CLOSED",
        ("SHOCKED_CLOSED", "BEGIN_RESNAPSHOT"): "WAITING_FOR_RESNAPSHOT",
        ("WAITING_FOR_RESNAPSHOT", "ACCEPT_CANDIDATE"): "NEW_EPOCH_PENDING",
        ("NEW_EPOCH_PENDING", "RELEASE"): "NEW_EPOCH_OPEN",
        ("NEW_EPOCH_PENDING", "SHOCK"): "WAITING_FOR_RESNAPSHOT",
    }
    state = "OPEN"
    for event in ("SHOCK", "BEGIN_RESNAPSHOT", "ACCEPT_CANDIDATE", "RELEASE"):
        state = allowed_transitions[(state, event)]
    assert state == "NEW_EPOCH_OPEN"
    assert ("SHOCKED_CLOSED", "REOPEN") not in allowed_transitions
    assert ("NEW_EPOCH_OPEN", "REOPEN_PREDECESSOR") not in allowed_transitions

    def release_result(candidate: dict[str, object]) -> tuple[str, str]:
        attempt = candidate.get("attempt")
        if attempt == "REOPEN_CLOSED_PREDECESSOR_EPOCH":
            return "CLOSED_FOREVER", "E_PREDECESSOR_EPOCH_IMMUTABLE"
        if attempt == "NEW_EPOCH_PENDING_TO_NEW_EPOCH_OPEN_WITH_CANDIDATE_NOT_CREATED":
            return "NEW_EPOCH_PENDING", "E_RELEASE_BINDING"
        if attempt == "CONTROLLER_RELEASE_RETAINS_PREDECESSOR_AS_CURRENT_EPOCH":
            return "NEW_EPOCH_PENDING", "E_INVALID_COHERENCE_TRANSITION"
        if attempt == "CREATE_NON_GENESIS_EPOCH_WITH_PREDECESSOR_PERMANENTLY_CLOSED_FALSE":
            return "WAITING_FOR_RESNAPSHOT", "E_NON_GENESIS_PREDECESSOR_NOT_CLOSED"
        if attempt == (
            "RELEASE_WITH_OBSERVED_PROOF_NOT_BOUND_TO_CANDIDATE_FRESHNESS_"
            "SHOCK_MAPPINGS_AND_CONTINUITY"
        ):
            return "NEW_EPOCH_PENDING", "E_RELEASE_BINDING"
        if candidate["predecessor_closed"] is not True:
            return "WAITING_FOR_RESNAPSHOT", "E_PREDECESSOR_NOT_CLOSED"
        if candidate["signed_accepted_capability_evidence"] is not True:
            return "WAITING_FOR_RESNAPSHOT", "E_CAPABILITY_EVIDENCE_NOT_ACCEPTED"
        if candidate["proof_status"] == "NOT_OBSERVED":
            return "WAITING_FOR_RESNAPSHOT", "E_RESNAPSHOT_NOT_OBSERVED"
        if candidate["proof_status"] != "OBSERVED":
            return "WAITING_FOR_RESNAPSHOT", "E_RESNAPSHOT_UNKNOWN"
        predicates = (
            ("football_state", "FRESH", "E_FOOTBALL_STATE_NOT_FRESH"),
            ("operator_state", "FRESH", "E_OPERATOR_STATE_NOT_FRESH"),
            ("market_book", "FRESH_COMPLETE_OPEN", "E_MARKET_BOOK_NOT_COMPLETE_OPEN"),
            (
                "conservative_lower_bounds_strictly_after_shock_upper",
                True,
                "E_NOT_STRICTLY_POST_SHOCK",
            ),
            (
                "proof_bound_mappings_open_unclosed_valid_at_release",
                True,
                "E_MAPPING_CLOSED",
            ),
            (
                "identities_orientation_generations_agree",
                True,
                "E_IDENTITY_OR_GENERATION_MISMATCH",
            ),
            ("cursor_ranges_contiguous", True, "E_CURSOR_NOT_CONTIGUOUS"),
        )
        for field, required, error in predicates:
            if candidate[field] != required:
                return "NEW_EPOCH_PENDING", error
        if candidate["gap_conflict_schema_lifecycle_mapping_or_later_shock_absent"] is not True:
            if candidate.get("blocker") == "LATER_OR_INTERSECTING_SHOCK":
                return "WAITING_FOR_RESNAPSHOT", "E_CANDIDATE_CLOSED_BY_NEW_SHOCK"
            return "NEW_EPOCH_PENDING", "E_RELEASE_BLOCKED"
        if candidate["score_period_suspension_and_shock_fields_agree"] is not True:
            return "NEW_EPOCH_PENDING", "E_STATE_FIELDS_DISAGREE"
        if (
            candidate["freshness_bindings_valid_at_release"] is not True
            or candidate["continuity_bindings_valid_at_release"] is not True
        ):
            return "NEW_EPOCH_PENDING", "E_RELEASE_BINDING"
        return "NEW_EPOCH_OPEN", "ACCEPT"

    assert release_result(positive) == ("NEW_EPOCH_OPEN", "ACCEPT")
    for vector in vectors["release_negative_vectors"]:
        candidate = dict(positive)
        failed = vector.get("failed_predicate")
        if isinstance(failed, str):
            if "value" in vector:
                candidate[failed] = vector["value"]
            elif failed == "proof_status":
                candidate[failed] = vector["proof_status"]
            else:
                candidate[failed] = False
        for field in ("proof_status", "blocker", "attempt"):
            if field in vector:
                candidate[field] = vector[field]
        observed_state, observed_error = release_result(candidate)
        assert observed_state == vector["expected_state"], vector["id"]
        assert observed_error == vector["expected_error"], vector["id"]

    for vector in vectors["candidate_acceptance_negative_vectors"]:
        accepted = (
            vector.get("proof_status_at_transition", vector.get("proof_status")) == "OBSERVED"
            and vector["proof_verified"] is True
            and vector["release_predicate"] == "SATISFIED"
            and vector.get("freshness_binding_verified", False) is True
            and vector.get("shock_binding_verified", False) is True
            and vector.get("mapping_bindings_verified", False) is True
            and vector.get("continuity_bindings_verified", False) is True
        )
        assert accepted is False, vector["id"]
        assert vector["expected_state"] == "WAITING_FOR_RESNAPSHOT", vector["id"]


def validate_semantic_vector_file(name: str, vendor: Path = VENDOR) -> None:
    expected_cases = {
        "e0-evidence-v1.json": (40, 9),
        "d0-evidence-v1.json": (26, 1),
        "scope-semantic-v1.json": (34, 17),
        "review-semantic-v1.json": (28, 4),
    }
    assert name in expected_cases
    data = parse_strict_json((vendor / "vectors" / name).read_bytes())
    assert isinstance(data, dict)
    assert data["production_authority"] == "NONE"
    contract = data["vector_contract"]
    assert isinstance(contract, dict)
    assert contract["patch_semantics"] == "RFC6902"
    assert contract["error_selection"] == "LOWEST_PRECEDENCE_RANK_ONLY"
    for key in ("schema_ref", "base_schema_ref", "case_schema_ref"):
        assert str(contract[key]).startswith("urn:hybrid-discovery:v6.2:meta-records:v1#")

    precedence = data["error_precedence"]
    assert isinstance(precedence, list)
    assert [entry["precedence_rank"] for entry in precedence] == [1, 5, 10, 15, 20, 30]
    assert [entry["stage"] for entry in precedence] == [
        "UNIVERSAL_DENIAL",
        "JSON_PATCH",
        "SCHEMA",
        "REFERENCE",
        "SEMANTIC",
        "AUTHORITY",
    ]

    scope_policy: dict[str, object] | None = None
    evidence_evaluator: EvidenceSemanticEvaluator | None = None
    if name == "scope-semantic-v1.json":
        parsed_policy = parse_strict_json(
            (vendor / "registries/scope0-input-policy.v1.json").read_bytes()
        )
        assert isinstance(parsed_policy, dict)
        validate_scope_policy(parsed_policy)
        scope_policy = parsed_policy
    elif name == "review-semantic-v1.json":
        decision_registry = parse_strict_json(
            (vendor / "registries/required-discovery-decisions.v1.json").read_bytes()
        )
        consumer_registry = parse_strict_json(
            (vendor / "registries/discovery-capability-consumers.v1.json").read_bytes()
        )
        assert isinstance(decision_registry, dict)
        assert isinstance(consumer_registry, dict)
        validate_required_decision_registry(decision_registry)
        validate_consumer_registry(consumer_registry)
    else:
        evidence_evaluator = EvidenceSemanticEvaluator(vendor)

    bases = _semantic_bases(data)
    assert len(bases) == len({str(base["case_id"]) for base in bases})
    by_id = {str(base["case_id"]): base for base in bases}
    registry = _published_schema_registry(vendor)
    for base in bases:
        assert _record_validates(base, registry)
        if name in {"scope-semantic-v1.json", "review-semantic-v1.json"}:
            assert semantic_vector_error(name, base, base, scope_policy=scope_policy) is None
        elif evidence_evaluator is not None:
            assert (
                evidence_evaluator.evaluate(
                    name,
                    base,
                    schema_valid=True,
                    require_failure=False,
                )
                is None
            )

    cases = data["counterexamples"]
    assert isinstance(cases, list)
    expected_count, expected_semantic_count = expected_cases[name]
    assert len(cases) == expected_count
    assert len({case["case_id"] for case in cases}) == expected_count
    semantic_count = sum(case["candidate_schema_state"] == "VALID" for case in cases)
    assert semantic_count == expected_semantic_count
    for case in cases:
        assert case["base_case_id"] in by_id
        assert isinstance(case["expected_error"], str) and case["expected_error"].startswith("E_")
        assert case["precedence_rank"] in {1, 10, 20}
        candidate = _apply_json_patch(by_id[case["base_case_id"]], case["operations"])
        schema_valid = _record_validates(candidate, registry)
        assert schema_valid is (case["candidate_schema_state"] == "VALID")
        if schema_valid:
            assert case["precedence_rank"] == 20
        else:
            assert case["precedence_rank"] in {1, 10}
        if name in {"scope-semantic-v1.json", "review-semantic-v1.json"}:
            observed_error = semantic_vector_error(
                name,
                by_id[case["base_case_id"]],
                candidate,
                scope_policy=scope_policy,
            )
            assert observed_error == case["expected_error"]
        elif evidence_evaluator is not None:
            observed_failure = evidence_evaluator.evaluate(
                name,
                candidate,
                schema_valid=schema_valid,
            )
            assert observed_failure is not None
            assert observed_failure.error_code == case["expected_error"]
            assert observed_failure.precedence_rank == case["precedence_rank"]


def _semantic_bases(data: dict[str, object]) -> list[dict[str, object]]:
    bases: list[dict[str, object]] = []
    for key in ("valid_records", "semantic_bases", "valid_capabilities"):
        collection = data.get(key, [])
        assert isinstance(collection, list)
        assert all(isinstance(base, dict) for base in collection)
        bases.extend(collection)
    valid_review = data.get("valid_review")
    if valid_review is not None:
        assert isinstance(valid_review, dict)
        bases.append(valid_review)
    return bases


def _published_schema_registry(vendor: Path) -> Registry[dict[str, object]]:
    resources: list[tuple[str, Resource[dict[str, object]]]] = []
    for path in sorted((vendor / "schemas").glob("*.json")):
        schema = parse_strict_json(path.read_bytes())
        assert isinstance(schema, dict)
        schema_id = schema.get("$id")
        assert isinstance(schema_id, str)
        assert schema_id.startswith(
            ("urn:hybrid-discovery:v6.2:", "https://hybrid-discovery.local/schemas/v6.2/")
        )
        resources.append((schema_id, Resource.from_contents(schema)))
    assert len(resources) == 13
    return Registry().with_resources(resources)


def _record_validates(case: dict[str, object], registry: Registry[dict[str, object]]) -> bool:
    schema_ref = case["record_schema_ref"]
    assert isinstance(schema_ref, str) and schema_ref.startswith(
        ("urn:hybrid-discovery:v6.2:", "https://hybrid-discovery.local/schemas/v6.2/")
    )
    return cast(
        bool,
        Draft202012Validator(
            {"$ref": schema_ref}, registry=registry, format_checker=STRICT_FORMAT_CHECKER
        ).is_valid(case["record"]),
    )


def _pointer_parts(pointer: object) -> list[str]:
    assert isinstance(pointer, str) and pointer.startswith("/")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _pointer_parent(document: object, pointer: object) -> tuple[object, str]:
    parts = _pointer_parts(pointer)
    assert parts
    parent = document
    for part in parts[:-1]:
        if isinstance(parent, dict):
            assert part in parent
            parent = parent[part]
        else:
            assert isinstance(parent, list)
            parent = parent[int(part)]
    return parent, parts[-1]


def _pointer_value(document: object, pointer: object) -> object:
    value = document
    for part in _pointer_parts(pointer):
        if isinstance(value, dict):
            assert part in value
            value = value[part]
        else:
            assert isinstance(value, list)
            value = value[int(part)]
    return value


def _apply_json_patch(base: dict[str, object], operations: object) -> dict[str, object]:
    assert isinstance(operations, list) and operations
    document = copy.deepcopy(base)
    for operation in operations:
        assert isinstance(operation, dict)
        op = operation["op"]
        assert op in {"add", "copy", "remove", "replace"}
        value = (
            copy.deepcopy(_pointer_value(document, operation["from"]))
            if op == "copy"
            else copy.deepcopy(operation.get("value"))
        )
        parent, pointer_component = _pointer_parent(document, operation["path"])
        if isinstance(parent, dict):
            if op in {"remove", "replace"}:
                assert pointer_component in parent
            if op == "remove":
                del parent[pointer_component]
            else:
                parent[pointer_component] = value
        else:
            assert isinstance(parent, list)
            if op == "add" or op == "copy":
                index = len(parent) if pointer_component == "-" else int(pointer_component)
                assert 0 <= index <= len(parent)
                parent.insert(index, value)
            else:
                index = int(pointer_component)
                assert 0 <= index < len(parent)
                if op == "remove":
                    parent.pop(index)
                else:
                    parent[index] = value
    return document


def validate_custody_and_authority(vendor: Path = VENDOR) -> None:
    manifest = parse_strict_json(
        (vendor / "security/discovery-capability-manifest.v1.json").read_bytes()
    )
    trust = parse_strict_json((vendor / "security/trust-root.v1.json").read_bytes())
    assert isinstance(manifest, dict) and isinstance(trust, dict)
    assert manifest["production_authority"] == "NONE" and manifest["body_classes"] == []
    assert trust["trusted_keys"] == [] and trust["production_authority"] == "NONE"
    assert trust["signing_key_custody"] == "USER_SCOPED_OS_BACKED_OUTSIDE_PACK_AND_RUNTIME"
    assert trust["schema_version"] == "trust-root/v1"
    assert trust["signature_algorithm"] == "Ed25519"
    assert (
        trust["public_key_encoding"]
        == "RAW_32_BYTES_UNPADDED_BASE64URL_CANONICAL_REENCODE_REQUIRED"
    )
    assert trust["key_id_derivation"] == "key:ed25519:<sha256-lowercase-hex-of-raw-public-key>"
    assert trust["signature_domain"] == "HYBRID-DISCOVERY/v6.2/SIGNATURE/Ed25519/v1\0"
    assert trust["runtime_key_material"] == "VERIFIER_PUBLIC_KEYS_ONLY"
    assert trust["trust_roles"] == [
        "PACK_REVIEWER",
        "DISCOVERY_OPERATOR",
        "PROVIDER_OPERATOR",
        "REVOCATION_AUTHORITY",
    ]
    expected_audiences = {
        "hybrid-discovery:bootstrap-gate:v1": ["PACK_REVIEWER"],
        "hybrid-discovery:extension-run-controller:v1": ["DISCOVERY_OPERATOR"],
        "hybrid-discovery:body-broker:v1": ["DISCOVERY_OPERATOR"],
        "hybrid-discovery:provider-protocol:v1": ["PACK_REVIEWER", "PROVIDER_OPERATOR"],
        "hybrid-discovery:provider-client:v1": ["PROVIDER_OPERATOR"],
        "hybrid-discovery:revocation-ledger:v1": ["REVOCATION_AUTHORITY"],
    }
    audience_bindings = trust["audience_role_bindings"]
    assert isinstance(audience_bindings, list)
    actual_audiences = {binding["audience"]: binding["roles"] for binding in audience_bindings}
    assert actual_audiences == expected_audiences
    test_keys = trust["test_only_untrusted_keys"]
    assert isinstance(test_keys, list) and len(test_keys) == 1
    test_key = test_keys[0]
    assert test_key["label"] == "RFC8032_TEST_VECTOR_1"
    assert test_key["trust"] == "TEST_ONLY_UNTRUSTED"
    public_key = base64.urlsafe_b64decode(str(test_key["public_key"]) + "==")
    assert len(public_key) == 32
    assert test_key["key_id"] == f"key:ed25519:{hashlib.sha256(public_key).hexdigest()}"
    forbidden_key_fields = {"private_key", "private_key_hex", "private_key_seed", "seed"}
    assert not any(forbidden_key_fields & set(item) for item in _objects(trust))
    protocol_lock = parse_strict_json((vendor / "security/cdp-protocol-lock.v1.json").read_bytes())
    assert isinstance(protocol_lock, dict)
    assert protocol_lock["production_authority"] == "NONE"
