from moj_discovery.pack_verifier import verify_imports


def test_contract_is_intentionally_unimplemented() -> None:
    verify_imports()
