from moj_discovery.capability import validate_discovery_capability


def test_contract_is_intentionally_unimplemented() -> None:
    validate_discovery_capability()
