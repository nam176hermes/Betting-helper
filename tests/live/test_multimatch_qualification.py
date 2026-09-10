"""Scope ordering tests use explicit mocks; none produces real-source acceptance."""

import hashlib
import json
from typing import Any

import pytest

from moj_discovery.live_config import LiveConfig
from tools import qualify_live_readonly as gate


@pytest.mark.parametrize("limit,needed", [(1, []), (3, [1]), (5, [1, 3])])
def test_preceding_scopes_reopen_physical_recordings(
    tmp_path: Any, monkeypatch: Any, limit: int, needed: list[int]
) -> None:
    folder = tmp_path / ".local/part-b"
    folder.mkdir(parents=True)
    refs, reports, called = {}, {}, []
    for scope in needed:
        run = folder / ("run-" + str(scope))
        run.mkdir()
        report = dict(
            schema_version="part-b-live-qualification/v1",
            run_id=str(scope),
            run_directory=str(run),
            source_tree_sha256="a" * 64,
            config_sha256="b" * 64,
            scope={"max_matches": scope},
            observed_fixture_ids=list(range(scope)),
            ft_checks_by_binding={str(i): 3 for i in range(scope)},
            artifacts={},
            real_http_attempts=10,
            LIVE_READ_ONLY_PASS=True,
        )
        reports[scope] = report
        path = folder / (str(scope) + ".json")
        path.write_text(json.dumps(report))
        refs[str(scope)] = dict(
            path=str(path.relative_to(tmp_path)),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def requalify(run: Any, *, expected_scope: int) -> Any:
        assert run == folder / ("run-" + str(expected_scope))
        called.append(expected_scope)
        return reports[expected_scope]

    monkeypatch.setattr(gate, "qualify_recorded_run", requalify)
    config = LiveConfig({"runtime": {"max_matches": limit}}, "b" * 64)
    review = {"scope": {"previous_scope_refs": refs}}
    gate.verify_preceding_scope(config, review, tmp_path)
    assert called == needed
    if needed:
        with pytest.raises(ValueError, match="REQUIRED"):
            gate.verify_preceding_scope(config, {"scope": {}}, tmp_path)
        reports[needed[0]]["LIVE_READ_ONLY_PASS"] = False
        with pytest.raises(ValueError, match="NOT_QUALIFIED"):
            gate.verify_preceding_scope(config, review, tmp_path)
        path = folder / (str(needed[0]) + ".json")
        path.write_text("{}")
        with pytest.raises(ValueError, match="HASH"):
            gate.verify_preceding_scope(config, review, tmp_path)
