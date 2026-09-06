from .errors import ContractNotImplementedError


def validate_identifier_namespace(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("R0-T03")
