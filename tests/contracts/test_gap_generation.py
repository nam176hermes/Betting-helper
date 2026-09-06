from moj_discovery.generation import GenerationController


def test_generation_replacement_is_exact_and_monotonic() -> None:
    assert GenerationController().replace_after_gap({"0": "ACTIVE"}, 0) == {
        "0": "CLOSED",
        "1": "ACTIVE",
    }
