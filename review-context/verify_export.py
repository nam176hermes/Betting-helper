"""Verify every inventoried export file without network or third-party packages."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'review-context/EXPORT_MANIFEST.json').read_text())
failures = []
seen = set()
for entry in manifest['files']:
    name = entry['path']
    relative = Path(name)
    path = root / relative
    if (relative.is_absolute() or '..' in relative.parts or name in seen
            or path.is_symlink() or not path.resolve().is_relative_to(root)):
        failures.append(name)
        continue
    seen.add(name)
    if not path.is_file():
        failures.append(name)
        continue
    data = path.read_bytes()
    if len(data) != entry['size_bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        failures.append(name)
print(json.dumps({'result': 'FAIL' if failures else 'PASS',
                  'checked_files': len(seen), 'failures': failures}))
raise SystemExit(bool(failures))
