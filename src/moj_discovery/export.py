from .errors import ContractNotImplementedError


def build_sanitized_export(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("F0A-T08")
