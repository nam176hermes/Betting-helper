from pathlib import Path
import argparse
import subprocess
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plan_tools.common import encoded, safe_ancestors

def initialize(root, receipt):
    root, receipt = Path(root), Path(receipt)
    safe_ancestors(root); safe_ancestors(receipt)
    if (root / '.git').exists() or root.resolve() in receipt.resolve().parents or receipt.exists():
        raise ValueError('E_BOOT0_GIT_OR_RECEIPT')
    def run(*args):
        return subprocess.check_output(args, cwd=root, text=True).strip()
    run('git', 'init', '-b', 'main')
    run('git', 'config', 'user.name', 'Hybrid Discovery Author')
    run('git', 'config', 'user.email', 'hybrid-discovery@local.invalid')
    run('git', 'add', '.')
    run('git', '-c', 'commit.gpgsign=false', 'commit', '-m', 'Initialize authorized plan workspace')
    if run('git', 'remote') or run('git', 'status', '--porcelain=v1'):
        raise ValueError('E_BOOT0_GIT_STATE')
    result = {'schema_version': 'boot0-authoring-repository-receipt/v2', 'root': str(root), 'head': run('git', 'rev-parse', 'HEAD'), 'tree': run('git', 'rev-parse', 'HEAD^{tree}'), 'status': ''}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open('xb') as f:
        f.write(encoded(result))
    if run('git', 'status', '--porcelain=v1'):
        raise ValueError('E_BOOT0_DIRTY_AFTER_RECEIPT')
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', required=True); p.add_argument('--receipt', required=True)
    a = p.parse_args(); initialize(a.root, a.receipt)
