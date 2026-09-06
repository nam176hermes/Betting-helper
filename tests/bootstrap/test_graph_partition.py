import json
import shutil
from pathlib import Path

import pytest

from moj_discovery.governance import validate_graph_partition, validate_task_dependencies


def test_executable_and_future_graphs_are_partitioned() -> None:
    validate_graph_partition()
    validate_task_dependencies()


@pytest.mark.parametrize("mutation", ["missing", "extra", "rewired", "reordered"])
def test_graph_partition_requires_exact_approved_edges(tmp_path: Path, mutation: str) -> None:
    vendor = tmp_path / "vendor"
    shutil.copytree(Path("vendor/hybrid-discovery-v6.3.6/graphs"), vendor / "graphs")
    path = vendor / "graphs/executable-discovery-graph.v1.json"
    graph = json.loads(path.read_text())
    if mutation == "missing":
        graph["edges"].pop()
    elif mutation == "extra":
        graph["edges"].append(["R0", "E0"])
    elif mutation == "rewired":
        graph["edges"][0] = ["R0", "SEC0"]
    else:
        graph["edges"][0], graph["edges"][1] = graph["edges"][1], graph["edges"][0]
    path.write_text(json.dumps(graph))

    with pytest.raises(AssertionError):
        validate_graph_partition(vendor)


@pytest.mark.parametrize(
    ("artifact", "mutation"),
    [
        ("executable", "duplicate_node"),
        ("executable", "reordered_nodes"),
        ("executable", "extra_key"),
        ("executable", "wrong_version"),
        ("future", "duplicate_node"),
        ("future", "reordered_nodes"),
        ("future", "extra_key"),
        ("future", "wrong_version"),
    ],
)
def test_graph_artifacts_require_closed_shape_and_ordered_unique_nodes(
    tmp_path: Path, artifact: str, mutation: str
) -> None:
    vendor = tmp_path / "vendor"
    shutil.copytree(Path("vendor/hybrid-discovery-v6.3.6/graphs"), vendor / "graphs")
    filename = (
        "executable-discovery-graph.v1.json"
        if artifact == "executable"
        else "non-authoritative-future-roadmap.v1.json"
    )
    path = vendor / "graphs" / filename
    graph = json.loads(path.read_text())
    if mutation == "duplicate_node":
        graph["nodes"][1] = graph["nodes"][0]
    elif mutation == "reordered_nodes":
        graph["nodes"][0], graph["nodes"][1] = graph["nodes"][1], graph["nodes"][0]
    elif mutation == "extra_key":
        graph["unexpected"] = False
    else:
        graph["schema_version"] = "v2"
    path.write_text(json.dumps(graph))

    with pytest.raises(AssertionError):
        validate_graph_partition(vendor)
