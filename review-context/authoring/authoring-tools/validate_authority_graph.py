"""Keep executable work and non-authoritative roadmap work disconnected."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _edges(graph: dict[str, object], nodes: set[str]) -> None:
    for edge in graph["edges"]:
        if not isinstance(edge, list) or len(edge) != 2 or any(
            not isinstance(node, str) for node in edge
        ):
            raise ValueError("E_GRAPH_EDGE_SHAPE")
        if edge[0] not in nodes or edge[1] not in nodes:
            raise ValueError("E_GRAPH_EDGE_ENDPOINT")


def validate_graph_partition(executable_path: Path, future_path: Path) -> dict[str, object]:
    executable = _load(executable_path)
    future = _load(future_path)
    if executable.get("graph_type") != "EXECUTABLE_DISCOVERY_GRAPH":
        raise ValueError("E_EXECUTABLE_GRAPH_TYPE")
    executable_nodes = executable.get("nodes")
    if not isinstance(executable_nodes, list) or not executable_nodes or any(
        not isinstance(node, str) for node in executable_nodes
    ):
        raise ValueError("E_EXECUTABLE_NODE_SHAPE")
    executable_set = set(executable_nodes)
    if len(executable_set) != len(executable_nodes) or executable.get("terminal") not in executable_set:
        raise ValueError("E_EXECUTABLE_NODES")
    _edges(executable, executable_set)
    if future.get("graph_type") != "NON_AUTHORITATIVE_FUTURE_ROADMAP":
        raise ValueError("E_FUTURE_GRAPH_TYPE")
    expected = {"authority": "NONE", "executable": False, "may_start": False, "auto_activate": False}
    if any(future.get(key) != value for key, value in expected.items()):
        raise ValueError("E_FUTURE_AUTHORITY")
    future_nodes = future.get("nodes")
    if not isinstance(future_nodes, list) or not future_nodes:
        raise ValueError("E_FUTURE_NODE_SHAPE")
    future_set: set[str] = set()
    expected_keys = {"node_id", "graph_type", "executable", "authority", "may_start", "auto_activate"}
    for node in future_nodes:
        if not isinstance(node, dict) or set(node) != expected_keys:
            raise ValueError("E_FUTURE_NODE_SHAPE")
        if node["graph_type"] != "NON_AUTHORITATIVE_FUTURE_ROADMAP" or node["authority"] != "NONE" or node["executable"] is not False or node["may_start"] is not False or node["auto_activate"] is not False:
            raise ValueError("E_FUTURE_NODE_AUTHORITY")
        future_set.add(node["node_id"])
    if len(future_set) != len(future_nodes):
        raise ValueError("E_FUTURE_DUPLICATE_NODE")
    _edges(future, future_set)
    if executable_set & future_set:
        raise ValueError("E_GRAPH_CROSS_CLASS")
    return {"result": "PASS", "executable_nodes": len(executable_set), "future_nodes": len(future_set)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--future", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_graph_partition(args.executable, args.future), sort_keys=True))


if __name__ == "__main__":
    main()
