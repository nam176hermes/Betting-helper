from moj_discovery.store import RunStore


def test_contract_is_intentionally_unimplemented() -> None:
    RunStore().bootstrap_v1()
