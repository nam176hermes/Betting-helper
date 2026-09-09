"""Parent-only negative/report cases. Readers never receive expected state."""

import copy
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from moj_discovery.diagnostic import render_diagnostic
from moj_discovery.live_preflight import check_live_readiness
from tools.offline_browser import ROOT
from tools.offline_harness import source_hashes


def run_meta(case: str, root: Path, verify: Callable[[Path], dict[str, Any]]) -> None:
    directory = root / case
    directory.mkdir()
    if case == "OFF-20":
        value = verify(root / "reference.json")
        value["cases"][0]["reason"] = (
            '<script>alert("synthetic")</script><img src=https://example.invalid/x>'
        )
        (directory / "input.json").write_text(json.dumps(value))
        (directory / "diagnostic.html").write_text(render_diagnostic(value))
    elif case == "OFF-21":
        config = json.loads((ROOT / "config/live.example.json").read_text())
        (directory / "config.json").write_text(json.dumps(config))
        with (
            patch.object(socket, "socket", side_effect=AssertionError("NETWORK_ATTEMPT")) as direct,
            patch.object(
                socket, "create_connection", side_effect=AssertionError("NETWORK_ATTEMPT")
            ) as connection,
        ):
            result = check_live_readiness(config, {}, {})
            observed = {
                "result": result,
                "network_attempts": direct.call_count + connection.call_count,
            }
        (directory / "observed.json").write_text(json.dumps(observed))
    elif case == "OFF-22":
        value = json.loads((root / "reference.json").read_text())
        targets = []
        for mutation in ["missing", "tampered", "duplicate", "forged"]:
            poisoned = copy.deepcopy(value)
            if mutation in {"missing", "tampered"}:
                artifact = poisoned["records"][0]["artifacts"][0]
                target = directory / (mutation + ".bin")
                if mutation == "tampered":
                    target.write_bytes((root / artifact["relative_path"]).read_bytes() + b"changed")
                artifact["relative_path"] = str(target.relative_to(root))
            elif mutation == "duplicate":
                poisoned["records"].append(copy.deepcopy(poisoned["records"][0]))
            else:
                poisoned["OFFLINE_SLICE_PASS"] = "YES"  # noqa: S105 -- qualification status, not a secret
            target = root / ("negative-" + case + "-" + mutation + ".json")
            target.write_text(json.dumps(poisoned))
            try:
                verify(target)
            except (ValueError, OSError, AssertionError):
                targets.append(target.name)
            else:
                raise AssertionError("E_OFFLINE_GATE_NEGATIVE_ACCEPTED")
        (directory / "observed.json").write_text(json.dumps({"rejected_inputs": targets}))
    elif case == "OFF-25":
        target = ROOT / "config/live.example.json"
        original = target.read_bytes()
        (directory / "original-config.json").write_bytes(original)
        changed = original + b"\n"
        (directory / "changed-config.json").write_bytes(changed)
        try:
            target.write_bytes(changed)
            (directory / "changed-sources.json").write_text(json.dumps(source_hashes()))
            try:
                verify(root / "reference.json")
            except ValueError as error:
                if str(error) != "E_OFFLINE_SOURCE_STALE":
                    raise
            else:
                raise AssertionError("E_OFFLINE_SOURCE_CHANGE_ACCEPTED")
        finally:
            target.write_bytes(original)
        (directory / "observed.json").write_text(
            json.dumps({"source_path": "config/live.example.json"})
        )
    else:
        raise ValueError("E_OFFLINE_META_CASE")


def check_meta(case: str, root: Path, verify: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    if not __debug__:
        raise RuntimeError("E_OFFLINE_OPTIMIZED_EXECUTION")
    import hashlib
    from html.parser import HTMLParser

    directory = root / case
    if case == "OFF-20":
        actual = json.loads((directory / "input.json").read_text())
        base = verify(root / "reference.json")
        base["cases"][0]["reason"] = (
            '<script>alert("synthetic")</script><img src=https://example.invalid/x>'
        )
        assert actual == base
        content = (directory / "diagnostic.html").read_text()
        assert content == render_diagnostic(actual)
        tags: list[tuple[str, Any]] = []

        class TagReader(HTMLParser):
            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                tags.append((tag, attrs))

        parser = TagReader()
        parser.feed(content)
        assert not any(
            tag in {"script", "img", "iframe", "object", "embed", "link"} for tag, _ in tags
        )
        assert "UNKNOWN" in content and "&lt;script&gt;" in content
        try:
            render_diagnostic({**actual, "verified": False})
        except ValueError:
            pass
        else:
            raise AssertionError("E_OFFLINE_BAD_DIAGNOSTIC_ACCEPTED")
    elif case == "OFF-21":
        config = json.loads((directory / "config.json").read_text())
        assert config == json.loads((ROOT / "config/live.example.json").read_text())
        with (
            patch.object(socket, "socket", side_effect=AssertionError("NETWORK_ATTEMPT")) as direct,
            patch.object(
                socket, "create_connection", side_effect=AssertionError("NETWORK_ATTEMPT")
            ) as connection,
        ):
            result = check_live_readiness(config, {}, {})
            actual = {
                "result": result,
                "network_attempts": direct.call_count + connection.call_count,
            }
        assert actual == json.loads((directory / "observed.json").read_text())
        assert actual["network_attempts"] == 0
        assert result["LIVE_READ_ONLY_READY"] == "PENDING_REAL_INPUTS_AND_LIVE_REVIEW"
        assert result["checks"]["provider_key"] == "PENDING_KEY"
        assert result["checks"]["capture_profile"] == "PENDING_REAL_INPUTS"
    elif case == "OFF-22":
        verify(root / "reference.json")
        actual = json.loads((directory / "observed.json").read_text())
        required = [
            "negative-" + case + "-" + kind + ".json"
            for kind in ["missing", "tampered", "duplicate", "forged"]
        ]
        assert actual == {"rejected_inputs": required}
        baseline = json.loads((root / "reference.json").read_text())
        for kind, name in zip(
            ["missing", "tampered", "duplicate", "forged"], required, strict=True
        ):
            expected = copy.deepcopy(baseline)
            if kind in {"missing", "tampered"}:
                ref = expected["records"][0]["artifacts"][0]
                if kind == "tampered":
                    assert (directory / "tampered.bin").read_bytes() == (
                        (root / ref["relative_path"]).read_bytes() + b"changed"
                    )
                ref["relative_path"] = f"{case}/{kind}.bin"
            elif kind == "duplicate":
                expected["records"].append(copy.deepcopy(expected["records"][0]))
            else:
                expected["OFFLINE_SLICE_PASS"] = "YES"  # noqa: S105 -- status
            assert json.loads((root / name).read_text()) == expected
            try:
                verify(root / name)
            except FileNotFoundError:
                assert kind == "missing"
            except ValueError as exc:
                assert str(exc) == {
                    "tampered": "E_OFFLINE_ARTIFACT_HASH",
                    "duplicate": "E_OFFLINE_CASE_INVENTORY",
                    "forged": "E_OFFLINE_FORGED_PASS",
                }.get(kind)
            else:
                raise AssertionError("E_OFFLINE_GATE_NEGATIVE_ACCEPTED")
    elif case == "OFF-25":
        verify(root / "reference.json")
        actual = json.loads((directory / "observed.json").read_text())
        assert actual == {"source_path": "config/live.example.json"}
        original = (directory / "original-config.json").read_bytes()
        changed = (directory / "changed-config.json").read_bytes()
        assert original == (ROOT / actual["source_path"]).read_bytes() and changed != original
        current = source_hashes()
        expected_changed = {**current, actual["source_path"]: hashlib.sha256(changed).hexdigest()}
        assert json.loads((directory / "changed-sources.json").read_text()) == expected_changed
        baseline = json.loads((root / "reference.json").read_text())["provenance"][
            "source_tree_sha256"
        ]
        assert (
            hashlib.sha256(json.dumps(expected_changed, sort_keys=True).encode()).hexdigest()
            != baseline
        )
    else:
        raise ValueError("E_OFFLINE_META_CASE")
    return {"case_id": case, "oracle_passed": True, "reason": "VERIFIED_REPORT_OR_NEGATIVE_CONTROL"}
