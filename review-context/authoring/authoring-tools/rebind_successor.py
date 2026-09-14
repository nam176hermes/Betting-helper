"""Apply only declared, hash-guarded successor replacements."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def _target(root: Path, value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("E_REBIND_PATH")
    return root / Path(*path.parts)


def apply_rebinding_plan(registry_path: Path, root: Path = Path.cwd()) -> dict[str, object]:
    patches = json.loads(registry_path.read_text(encoding="utf-8"))["patches"]
    changed = 0
    seen: set[str] = set()
    for patch in patches:
        relative = patch["path"]
        if relative in seen:
            raise ValueError("E_REBIND_DUPLICATE")
        seen.add(relative)
        target = _target(root, relative)
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"E_REBIND_MISSING:{relative}")
        before = target.read_bytes()
        digest = hashlib.sha256(before).hexdigest()
        if digest == patch["after_sha256"]:
            continue
        if digest != patch["before_sha256"]:
            raise ValueError(f"E_REBIND_HASH:{relative}")
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"E_REBIND_UTF8:{relative}") from error
        for replacement in patch["replacements"]:
            if not replacement["old"] or replacement["old"] not in text:
                raise ValueError(f"E_REBIND_LITERAL:{relative}")
            text = text.replace(replacement["old"], replacement["new"])
        after = text.encode("utf-8")
        if hashlib.sha256(after).hexdigest() != patch["after_sha256"]:
            raise ValueError(f"E_REBIND_RESULT:{relative}")
        target.write_bytes(after)
        changed += 1
    return {"result": "PASS", "patch_count": len(patches), "changed_paths": changed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(apply_rebinding_plan(args.registry), sort_keys=True))


if __name__ == "__main__":
    main()
