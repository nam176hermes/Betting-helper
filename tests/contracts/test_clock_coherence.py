from moj_discovery.clock import ClockMapper


def test_contract_is_intentionally_unimplemented() -> None:
    ClockMapper().select()
