import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tools.prepare_review_workspace import build_bubblewrap_argv


def _mount(source: Path) -> dict[str, str]:
    return {"source_root": str(source), "workspace_mount": str(source), "mode": "READ_ONLY"}


def test_security_boundary() -> None:
    # /tmp is replaced by the generated namespace; keep its inputs outside it.
    with TemporaryDirectory(prefix="TEST_ONLY-isolation-", dir=Path.home()) as directory:
        _check_generated_boundary(Path(directory))


def _check_generated_boundary(tmp_path: Path) -> None:
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

    # Only synthetic sentinels: never inspect a real key, state or peer output.
    excluded = tmp_path / "TEST_ONLY-host"
    excluded.mkdir()
    sentinels = [excluded / name for name in ("authoring", "peer", "key", "state")]
    for path in sentinels:
        path.write_text("TEST_ONLY")
    script = """
import json, os, sys
from pathlib import Path
runtime, output, *sentinels = map(Path, sys.argv[1:])
observed = {
    'net': os.readlink('/proc/self/ns/net'),
    'visible': [p.exists() for p in sentinels],
    'proc_escape': [Path('/proc/1/root' + str(p)).exists() for p in sentinels],
}
(output / 'allowed').write_text('TEST_ONLY')
observed['output'] = (output / 'allowed').read_text()
try:
    (runtime / 'escape-probe').write_text('TEST_ONLY')
    observed['write_errno'] = 0
except OSError as error:
    observed['write_errno'] = error.errno
print(json.dumps(observed))
"""
    command = {"argv": ["/usr/bin/python3", "-c", script, str(runtime), str(output),
                        *map(str, sentinels)], "cwd": str(runtime)}
    generated = build_bubblewrap_argv(config, command)

    def observe(arguments: list[str]) -> dict[str, object]:
        completed = subprocess.run(  # noqa: S603 -- generated boundary, owned synthetic inputs.
            arguments, check=False, capture_output=True, text=True, timeout=15,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)  # type: ignore[no-any-return]

    observed = observe(generated)
    assert observed["net"] != os.readlink("/proc/self/ns/net"), vectors["allow"]
    assert observed["visible"] == observed["proc_escape"] == [False] * len(sentinels), (
        vectors["deny"]
    )
    assert observed["write_errno"] == 30  # EROFS from the actual readonly mount.
    assert observed["output"] == "TEST_ONLY"
    assert not (runtime / "escape-probe").exists()

    # Each mutation must change the corresponding observed boundary result.
    shared_network = [arg for arg in generated if arg != "--unshare-net"]
    assert observe(shared_network)["net"] == os.readlink("/proc/self/ns/net")
    writable_runtime = generated.copy()
    index = next(i for i in range(len(generated) - 2)
                 if generated[i:i + 3] == ["--ro-bind", str(runtime), str(runtime)])
    writable_runtime[index] = "--bind"
    assert observe(writable_runtime)["write_errno"] == 0
    assert (runtime / "escape-probe").read_text() == "TEST_ONLY"
    (runtime / "escape-probe").unlink()
    escaped = generated.copy()
    index = escaped.index("--")
    escaped[index:index] = ["--ro-bind", str(excluded), str(excluded)]
    assert observe(escaped)["visible"] == [True] * len(sentinels), vectors["mutate"]
