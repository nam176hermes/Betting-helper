from .errors import ContractNotImplementedError


def append_observation(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T02")


def append_correction(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T02")
