import subprocess
from pathlib import Path

from tools.create_zero_parent_repository import create_zero_parent_repository


def test_delivered_repository_has_one_zero_parent_commit_and_no_remote(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "app.py").write_text("pass\n")
    (root / ".gitignore").write_text("generated/\n")
    (root / "generated").mkdir()
    (root / "generated/result.js").write_text("export {};\n")

    result = create_zero_parent_repository(root)

    assert result["result"] == "PASS"
    assert (root / ".git").is_dir()
    tracked = subprocess.run(  # noqa: S603 - fixed Git executable and argv
        ["/usr/bin/git", "-C", str(root), "ls-files"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.splitlines()
    assert tracked == [".gitignore", "app.py", "generated/result.js"]
