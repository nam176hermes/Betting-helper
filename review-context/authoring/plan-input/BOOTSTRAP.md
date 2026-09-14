# BOOT0 — exact bootstrap inputs and commands

Before execution the human must supply this plan ZIP and its SHA-256 sidecar under /home/thenam176/betting-helper/inputs. Both names are frozen below. The predecessor is retained under docs/sources solely as provenance; it is not executed.

Prerequisites: /usr/bin/python3.12; git; jsonschema==4.26.0 and pytest available to the verifier; the pinned local v6.2 runtime source and its offline dependency caches. Missing prerequisite is HOLD, never an implicit network install. BOOT0 uses only stdlib until the plan schema tests. Initial local Git creation requires explicit authorization during implementation. No authoring-root command executes before BOOT0_CREATE_WORKSPACE.

Run in this task/command order, using cwd and argv directly (no shell interpolation). Extraction uses the exact bundled stdlib extractor inline before an extracted script is trusted; it verifies ZIP/sidecar/manifest closure and rejects existing destinations.

## BOOT0_PREPARE_INPUT_DIRS

```json
{
  "cwd": "/home/thenam176/betting-helper",
  "argv": [
    "mkdir",
    "-p",
    "/home/thenam176/betting-helper/inputs",
    "/home/thenam176/betting-helper/plan-input"
  ]
}
```

## BOOT0_VERIFY_SIDECAR

```json
{
  "cwd": "/home/thenam176/betting-helper/inputs",
  "argv": [
    "sha256sum",
    "-c",
    "hybrid-discovery-v6.3.6-authoritative-design-plan.zip.sha256"
  ]
}
```

## BOOT0_EXTRACT_PLAN

```json
{
  "cwd": "/home/thenam176/betting-helper/inputs",
  "argv": [
    "python3.12",
    "-B",
    "-c",
    "\"\"\"This exact stdlib source is also frozen inline in BOOT0_EXTRACT_PLAN argv.\"\"\"\nfrom pathlib import Path, PurePosixPath\nimport argparse\nimport hashlib\nimport json\nimport stat\nimport unicodedata\nimport zipfile\n\ndef extract(archive, destination, sidecar):\n    archive, destination, sidecar = Path(archive), Path(destination), Path(sidecar)\n    for path in [archive, destination, sidecar]:\n        if any(p.is_symlink() for p in [path, *path.parents]):\n            raise ValueError('E_BOOT0_SYMLINK')\n    if destination.exists():\n        raise ValueError('E_BOOT0_DESTINATION_EXISTS')\n    side = sidecar.read_text().split()\n    if len(side) != 2 or side[1] != archive.name or hashlib.sha256(archive.read_bytes()).hexdigest() != side[0]:\n        raise ValueError('E_BOOT0_SIDECAR')\n    expected_root = 'hybrid-discovery-v6.3.6-authoritative-design-plan'\n    with zipfile.ZipFile(archive) as z:\n        infos = z.infolist()\n        if not infos or len(infos) > 4096 or sum(i.file_size for i in infos) > 64 * 1024 * 1024:\n            raise ValueError('E_BOOT0_ARCHIVE_LIMIT')\n        payload = {}\n        for i in infos:\n            n = PurePosixPath(i.filename)\n            if (n.is_absolute() or n.as_posix() != i.filename or len(n.parts) < 2 or\n                    n.parts[0] != expected_root or any(x in {'', '.', '..', '.git', '.env'} for x in n.parts) or\n                    '\\\\' in i.filename or any(ord(x) < 32 or ord(x) == 127 for x in i.filename) or\n                    unicodedata.normalize('NFC', i.filename) != i.filename or\n                    i.is_dir() or stat.S_IFMT(i.external_attr >> 16) not in {0, stat.S_IFREG} or\n                    i.flag_bits & 1):\n                raise ValueError('E_BOOT0_ARCHIVE_PATH')\n            rel = '/'.join(n.parts[1:])\n            if rel in payload:\n                raise ValueError('E_BOOT0_DUPLICATE')\n            payload[rel] = z.read(i)\n        rows = json.loads(payload['MANIFEST_SHA256.json'])['entries']\n        names = [r['path'] for r in rows]\n        if len(names) != len(set(names)) or set(payload) != set(names) | {'MANIFEST_SHA256.json'}:\n            raise ValueError('E_BOOT0_MANIFEST_FILE_SET')\n        for r in rows:\n            b = payload[r['path']]\n            if len(b) != r['size'] or hashlib.sha256(b).hexdigest() != r['sha256']:\n                raise ValueError('E_BOOT0_MANIFEST_BYTES')\n        destination.mkdir(parents=True, exist_ok=False)\n        for name, b in payload.items():\n            f = destination / name\n            f.parent.mkdir(parents=True, exist_ok=True)\n            with f.open('xb') as stream:\n                stream.write(b)\n            f.chmod(0o644)\n\nif __name__ == '__main__':\n    parser = argparse.ArgumentParser()\n    parser.add_argument('--zip', required=True)\n    parser.add_argument('--destination', required=True)\n    parser.add_argument('--sidecar', required=True)\n    a = parser.parse_args()\n    extract(a.zip, a.destination, a.sidecar)\n",
    "--zip",
    "/home/thenam176/betting-helper/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip",
    "--sidecar",
    "/home/thenam176/betting-helper/inputs/hybrid-discovery-v6.3.6-authoritative-design-plan.zip.sha256",
    "--destination",
    "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan"
  ]
}
```

## BOOT0_VERIFY_EXTRACTED

```json
{
  "cwd": "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
  "argv": [
    "python3.12",
    "-B",
    "bootstrap/verify_extracted_plan.py",
    "--root",
    "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
    "--receipt",
    "/home/thenam176/betting-helper/plan-input/.receipts/hybrid-discovery-v6.3.6-plan-input.json"
  ]
}
```

## PLAN_PREFLIGHT

```json
{
  "cwd": "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
  "argv": [
    "python3.12",
    "-B",
    "plan_tools/check_plan.py",
    "--root",
    "."
  ]
}
```

## PLAN_SCHEMA_TESTS

```json
{
  "cwd": "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
  "argv": [
    "python3.12",
    "-B",
    "-m",
    "unittest",
    "discover",
    "-s",
    "plan_tests",
    "-v"
  ]
}
```

## BOOT0_CREATE_WORKSPACE

```json
{
  "cwd": "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
  "argv": [
    "python3.12",
    "-B",
    "bootstrap/create_authoring_workspace.py",
    "--plan-root",
    "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan",
    "--authoring-root",
    "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring",
    "--receipt",
    "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring/.bootstrap/authoring-workspace-receipt.json"
  ]
}
```

## BOOT0_INIT_AUTHORING_REPO

```json
{
  "cwd": "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring",
  "argv": [
    "python3.12",
    "-B",
    "/home/thenam176/betting-helper/plan-input/hybrid-discovery-v6.3.6-authoritative-design-plan/bootstrap/initialize_authoring_repository.py",
    "--root",
    "/home/thenam176/betting-helper/hybrid-discovery-v6.3.6-authoring",
    "--receipt",
    "/home/thenam176/betting-helper/authoring-evidence/hybrid-discovery-v6.3.6/bootstrap/authoring-repository-receipt.json"
  ]
}
```
