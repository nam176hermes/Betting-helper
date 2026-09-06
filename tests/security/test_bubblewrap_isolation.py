import os
import subprocess
from pathlib import Path

import pytest

from tools.prepare_review_workspace import build_bubblewrap_argv


def _mount(source: Path) -> dict[str, str]:
    return {"source_root": str(source), "workspace_mount": str(source), "mode": "READ_ONLY"}


def test_security_boundary(tmp_path: Path) -> None:
    vectors = {
        "allow": "SEC_BUBBLEWRAP_ISOLATION-ALLOW",
        "deny": "SEC_BUBBLEWRAP_ISOLATION-DENY",
        "mutate": "SEC_BUBBLEWRAP_ISOLATION-MUTATE",
    }
    scratch = tmp_path / "workspace/scratch"
    output = tmp_path / "output"
    runtime = tmp_path / "runtime"
    pack = tmp_path / "pack"
    scratch.mkdir(parents=True)
    output.mkdir()
    for name in ("control", "home", "tmp"):
        (scratch / name).mkdir()
    runtime.mkdir()
    pack.mkdir()
    for path in (tmp_path / "seal.json", tmp_path / "pack.zip", tmp_path / "pack.zip.sha256"):
        path.write_text(path.name)
    python_dependencies = scratch / "node-project/node_modules"
    node_dependencies = scratch / "node-project/extension/node_modules"
    python_dependencies.mkdir(parents=True)
    node_dependencies.mkdir(parents=True)
    config: dict[str, object] = {
        "environment": {"UV_OFFLINE": "1"},
        "excluded_roots": [str(tmp_path / "authoring"), str(tmp_path / "peer")],
        "input_mounts": [
            _mount(pack),
            _mount(runtime),
            _mount(tmp_path / "seal.json"),
            _mount(tmp_path / "pack.zip"),
            _mount(tmp_path / "pack.zip.sha256"),
        ],
        "node_environment": {
            "dependency_mounts": [_mount(python_dependencies), _mount(node_dependencies)]
        },
        "scratch_root": str(scratch),
        "output_root": str(output),
    }
    argv = build_bubblewrap_argv(config, {"argv": ["python", "-c", "pass"], "cwd": str(runtime)})
    assert {"--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-uts"} <= set(argv)
    assert str(tmp_path / "authoring") not in argv
    assert str(tmp_path / "peer") not in argv
    pairs = [argv[index : index + 2] for index in range(len(argv) - 1)]
    assert "--die-with-parent" not in argv
    assert [str(scratch), str(scratch)] not in pairs
    assert [str(scratch / "tmp"), str(Path("/") / "tmp")] in pairs

    unsafe = dict(config)
    unsafe["input_mounts"] = [{**_mount(pack), "mode": "READ_WRITE"}]
    with pytest.raises(ValueError, match="E_REVIEW_WORKSPACE_ISOLATION"):
        build_bubblewrap_argv(unsafe, {"argv": ["python"], "cwd": str(runtime)})

    probe = subprocess.run(  # noqa: S603 -- fixed argv exercises the isolation boundary
        [
            "/usr/bin/bwrap",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--unshare-uts",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/usr/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--ro-bind",
            str(runtime),
            "/runtime",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            str(Path("/") / "tmp"),
            "--chdir",
            "/runtime",
            "--",
            "/bin/sh",
            "-c",
            "readlink /proc/self/ns/net; test ! -e /authoring && ! touch ./escape-probe",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, (vectors["allow"], vectors["deny"], probe.stderr)
    assert probe.stdout.strip() != os.readlink("/proc/self/ns/net"), vectors["deny"]
    assert not (runtime / "escape-probe").exists(), vectors["mutate"]
