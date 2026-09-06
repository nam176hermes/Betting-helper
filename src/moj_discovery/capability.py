from .errors import ContractNotImplementedError


def validate_discovery_capability(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("G0-T03")
