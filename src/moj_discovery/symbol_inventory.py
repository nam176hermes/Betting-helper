"""Exact source-symbol resolution without importing untrusted modules."""
from __future__ import annotations

import ast
from pathlib import Path


def resolve_python_symbol(path: Path, symbol: str) -> bool:
    if not path.is_file() or path.is_symlink():
        raise ValueError("E_SYMBOL_SOURCE")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise ValueError("E_SYMBOL_SYNTAX") from error
    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == symbol
        for node in tree.body
    ):
        return True
    raise ValueError("E_SYMBOL_UNRESOLVED")
