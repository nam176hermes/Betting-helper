from moj_discovery.pack_verifier import validate_finding_coverage


def test_contract_is_intentionally_unimplemented() -> None:
    validate_finding_coverage()
