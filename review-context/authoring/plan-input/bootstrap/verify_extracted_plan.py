from pathlib import Path
import argparse
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plan_tools.common import encoded, safe_ancestors, verify_manifest

def verify_extracted_plan(root, receipt):
    root, receipt = Path(root), Path(receipt)
    safe_ancestors(receipt)
    if root.resolve() == receipt.resolve() or root.resolve() in receipt.resolve().parents:
        raise ValueError('E_BOOT0_RECEIPT_INSIDE_INPUT')
    result = {'schema_version': 'boot0-plan-input-receipt/v2', 'root': str(root), **verify_manifest(root)}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open('xb') as f:
        f.write(encoded(result))
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', required=True); p.add_argument('--receipt', required=True)
    a = p.parse_args(); verify_extracted_plan(a.root, a.receipt)
