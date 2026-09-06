from moj_discovery.lifecycle import LifecycleReducer


def test_contract_is_intentionally_unimplemented() -> None:
    LifecycleReducer().apply()
