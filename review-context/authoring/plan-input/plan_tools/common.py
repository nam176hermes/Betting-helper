"""Offline plan-file integrity. No discovery/runtime operations."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import stat
import unicodedata

VERSION = 'v6.3.6'
EXCLUDED = {'GOVERNED_CONTENT_ROOT.json', 'SELF_REVIEW_REPORT.md',
            'SELF_REVIEW_REPORT.json', 'MANIFEST_SHA256.json'}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()

def relative_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or p.as_posix() != name or
            any(x in {'', '.', '..', '.git', '.env'} for x in p.parts) or
            '\\' in name or any(ord(x) < 32 or ord(x) == 127 for x in name) or
            unicodedata.normalize('NFC', name) != name):
        raise ValueError('E_PATH:' + repr(name))
    return p

def safe_ancestors(path):
    path = Path(path).absolute()
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise ValueError('E_SYMLINK:' + str(p))

def files(root):
    root = Path(root)
    safe_ancestors(root)
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            relative_name(rel)
            s = p.lstat()
            if stat.S_ISLNK(s.st_mode):
                raise ValueError('E_SYMLINK:' + rel)
            if stat.S_ISDIR(s.st_mode):
                continue
            if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
                raise ValueError('E_FILE_TYPE:' + rel)
            if stat.S_IMODE(s.st_mode) not in {0o644, 0o755}:
                raise ValueError('E_FILE_MODE:' + rel)
            result[rel] = p.read_bytes()
    return result

def verify_manifest(root):
    data = files(root)
    manifest = json.loads(data['MANIFEST_SHA256.json'])
    rows = manifest['entries']
    names = [x['path'] for x in rows]
    if len(names) != len(set(names)) or set(data) != set(names) | {'MANIFEST_SHA256.json'}:
        raise ValueError('E_MANIFEST_FILE_SET')
    for row in rows:
        relative_name(row['path'])
        b = data[row['path']]
        if len(b) != row['size'] or sha(b) != row['sha256']:
            raise ValueError('E_MANIFEST_BYTES:' + row['path'])
    return {'manifest_sha256': sha(data['MANIFEST_SHA256.json']), 'verified_entries': len(rows)}

def governed_root(data):
    h = hashlib.sha256(b'HYBRID-DISCOVERY/v6.3.6/GOVERNED-ROOT/v1\0')
    for name in sorted(set(data) - EXCLUDED, key=lambda x: x.encode('utf-8')):
        b = name.encode('utf-8')
        leaf = hashlib.sha256(b'HYBRID-DISCOVERY/v6.3.6/GOVERNED-FILE/v1\0' + b + b'\0' + hashlib.sha256(data[name]).digest()).digest()
        h.update(len(b).to_bytes(4, 'big') + b + leaf)
    return h.hexdigest()
