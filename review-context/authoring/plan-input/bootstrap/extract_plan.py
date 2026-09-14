"""This exact stdlib source is also frozen inline in BOOT0_EXTRACT_PLAN argv."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import stat
import unicodedata
import zipfile

def extract(archive, destination, sidecar):
    archive, destination, sidecar = Path(archive), Path(destination), Path(sidecar)
    for path in [archive, destination, sidecar]:
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError('E_BOOT0_SYMLINK')
    if destination.exists():
        raise ValueError('E_BOOT0_DESTINATION_EXISTS')
    side = sidecar.read_text().split()
    if len(side) != 2 or side[1] != archive.name or hashlib.sha256(archive.read_bytes()).hexdigest() != side[0]:
        raise ValueError('E_BOOT0_SIDECAR')
    expected_root = 'hybrid-discovery-v6.3.6-authoritative-design-plan'
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if not infos or len(infos) > 4096 or sum(i.file_size for i in infos) > 64 * 1024 * 1024:
            raise ValueError('E_BOOT0_ARCHIVE_LIMIT')
        payload = {}
        for i in infos:
            n = PurePosixPath(i.filename)
            if (n.is_absolute() or n.as_posix() != i.filename or len(n.parts) < 2 or
                    n.parts[0] != expected_root or any(x in {'', '.', '..', '.git', '.env'} for x in n.parts) or
                    '\\' in i.filename or any(ord(x) < 32 or ord(x) == 127 for x in i.filename) or
                    unicodedata.normalize('NFC', i.filename) != i.filename or
                    i.is_dir() or stat.S_IFMT(i.external_attr >> 16) not in {0, stat.S_IFREG} or
                    i.flag_bits & 1):
                raise ValueError('E_BOOT0_ARCHIVE_PATH')
            rel = '/'.join(n.parts[1:])
            if rel in payload:
                raise ValueError('E_BOOT0_DUPLICATE')
            payload[rel] = z.read(i)
        rows = json.loads(payload['MANIFEST_SHA256.json'])['entries']
        names = [r['path'] for r in rows]
        if len(names) != len(set(names)) or set(payload) != set(names) | {'MANIFEST_SHA256.json'}:
            raise ValueError('E_BOOT0_MANIFEST_FILE_SET')
        for r in rows:
            b = payload[r['path']]
            if len(b) != r['size'] or hashlib.sha256(b).hexdigest() != r['sha256']:
                raise ValueError('E_BOOT0_MANIFEST_BYTES')
        destination.mkdir(parents=True, exist_ok=False)
        for name, b in payload.items():
            f = destination / name
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open('xb') as stream:
                stream.write(b)
            f.chmod(0o644)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--sidecar', required=True)
    a = parser.parse_args()
    extract(a.zip, a.destination, a.sidecar)
