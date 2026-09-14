from pathlib import Path
import argparse
import json
import shutil
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plan_tools.common import encoded, relative_name, safe_ancestors, verify_manifest

def create_authoring_workspace(plan_root, authoring_root, receipt):
    plan_root, authoring_root, receipt = map(Path, [plan_root, authoring_root, receipt])
    verified = verify_manifest(plan_root)
    safe_ancestors(authoring_root); safe_ancestors(receipt)
    if authoring_root.exists():
        raise ValueError('E_BOOT0_AUTHORING_ROOT_EXISTS')
    if receipt.absolute() != authoring_root.absolute() / '.bootstrap/authoring-workspace-receipt.json':
        raise ValueError('E_BOOT0_RECEIPT_PATH')
    seeds = json.loads((plan_root / 'docs/registries/seed-artifacts.v1.json').read_text())['entries']
    for row in seeds:
        relative_name(row['source']); relative_name(row['destination'])
        if not row['destination'].startswith('pack/') or not (plan_root / row['source']).is_file():
            raise ValueError('E_BOOT0_SEED')
    authoring_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(plan_root, authoring_root / 'plan-input')
    copied = verify_manifest(authoring_root / 'plan-input')
    if copied != verified:
        raise ValueError('E_BOOT0_COPY_CHANGED')
    for name in ['runtime', 'pack', 'authoring-tools', 'authoring-tests', '.bootstrap']:
        (authoring_root / name).mkdir(exist_ok=True)
    for row in seeds:
        target = authoring_root / row['destination']; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(authoring_root / 'plan-input' / row['source'], target)
    result = {'schema_version': 'boot0-authoring-workspace-receipt/v2', 'authoring_root': str(authoring_root), 'plan_input_root': str(authoring_root / 'plan-input'), **verified}
    with receipt.open('xb') as f:
        f.write(encoded(result))
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--plan-root', required=True); p.add_argument('--authoring-root', required=True); p.add_argument('--receipt', required=True)
    a = p.parse_args(); create_authoring_workspace(a.plan_root, a.authoring_root, a.receipt)
