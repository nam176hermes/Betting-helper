from pathlib import Path
import ast

def test_bootstrap_scripts_parse():
    root=Path(__file__).resolve().parent
    for name in ["verify_extracted_plan.py","create_authoring_workspace.py","initialize_authoring_repository.py"]:
        ast.parse((root/name).read_text(encoding="utf-8"))
