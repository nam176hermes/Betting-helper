from moj_discovery.errors import ContractNotImplementedError


def test_contract_is_intentionally_unimplemented() -> None:
    raise ContractNotImplementedError("F0A-T01")
