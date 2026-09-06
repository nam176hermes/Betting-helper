import pytest

from moj_discovery.executable_gate import issue_executable_reference_complete_receipt


def test_gate_rejects_intentional_stub_or_unexecuted_command() -> None:
    reference = {"result": "PASS", "task_count": 46, "command_count": 142}
    topology = {"result": "PASS", "group_count": 11, "command_count": 45}
    receipt = issue_executable_reference_complete_receipt(reference, topology)
    assert receipt["production_authority"] == "NONE"
    with pytest.raises(ValueError, match="E_EXECUTABLE_REFERENCE_COMPLETE"):
        issue_executable_reference_complete_receipt({"result": "PASS"}, topology)
