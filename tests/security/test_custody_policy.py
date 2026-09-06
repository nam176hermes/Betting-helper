from moj_discovery.errors import ContractNotImplementedError


def test_contract_is_intentionally_unimplemented() -> None:
    raise ContractNotImplementedError("SEC0-T06")
