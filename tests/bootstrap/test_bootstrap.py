from moj_discovery.bootstrap import bootstrap_self_check


def test_bootstrap_is_inert_and_has_no_authority() -> None:
    assert bootstrap_self_check() == {
        "READY_TO_IMPLEMENT_DISCOVERY_PACK": "NO",
        "AUTHORIZED_PRODUCTION_PHASES": "NONE",
    }
