from .errors import ContractNotImplementedError


def verify_replay_equivalence(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("F0A-T08")
