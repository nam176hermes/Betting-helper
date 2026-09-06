from .errors import ContractNotImplementedError


def validate_e0_evidence_set(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("E0-T10")


def validate_d0_evidence_set(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("D0-T06")


def validate_evidence_inventory(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("G0-T01")
