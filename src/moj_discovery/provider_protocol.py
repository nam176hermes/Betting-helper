from .errors import ContractNotImplementedError


def verify_probe_protocol(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T01")


def verify_call_authorization(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T01")
