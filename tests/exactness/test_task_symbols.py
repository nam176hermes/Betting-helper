from pathlib import Path

import pytest

from moj_discovery.symbol_inventory import resolve_python_symbol


ROOT = Path(__file__).parents[2]


def test_task_symbols_resolve_from_exact_source_files() -> None:
    assert resolve_python_symbol(
        ROOT / "src/moj_discovery/task_contracts.py", "validate_task_manifest_semantics"
    )
    assert resolve_python_symbol(
        ROOT / "src/moj_discovery/durability_registry.py", "validate_crash_harness_registry"
    )
    with pytest.raises(ValueError, match="E_SYMBOL_UNRESOLVED"):
        resolve_python_symbol(ROOT / "src/moj_discovery/task_contracts.py", "missing")
