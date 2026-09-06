from tools.verify_test_discovery import verify_verification_topology


def test_all_proof_groups_are_discovered_and_registry_bound() -> None:
    result = verify_verification_topology()
    assert result == {"result": "PASS", "group_count": 11, "command_count": 45}
