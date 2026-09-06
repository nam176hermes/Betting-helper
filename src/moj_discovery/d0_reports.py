from .errors import ContractNotImplementedError


def build_provider_capability_report(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T03")


def build_identity_report(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T03")


def build_latency_report(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T04")


def build_correction_report(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T05")
