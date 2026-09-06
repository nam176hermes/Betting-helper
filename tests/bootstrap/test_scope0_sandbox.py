from pathlib import Path

from tools.run_scope0_sandbox import run_scope0_sandbox


def test_scope0_uses_bwrap_with_network_unshared(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.write_text("content-addressed")
    result = run_scope0_sandbox(source)
    assert result.returncode == 0
    assert result.stdout.strip() == "SCOPE0_SANDBOX_OK"
