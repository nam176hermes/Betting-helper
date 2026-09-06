from .errors import ContractNotImplementedError


def generate_candidate_scopes(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("SCOPE0-T02")


def validate_scope0_record(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("SCOPE0-T03")


def validate_scope_revocation_chain(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("SCOPE0-T04")
