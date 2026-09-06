from moj_discovery.schema_registry import validate_artifact


def test_contract_is_intentionally_unimplemented() -> None:
    validate_artifact({})
