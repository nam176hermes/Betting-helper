from moj_discovery.generation import GenerationController


def test_contract_is_intentionally_unimplemented() -> None:
    GenerationController().replace_after_gap()
