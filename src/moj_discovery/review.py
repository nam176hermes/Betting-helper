from .errors import ContractNotImplementedError


def validate_codex_review_output(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("R0-T05")


def validate_scenario_sufficiency(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("G0-T02")


def build_discovery_acceptance(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("G0-T04")
