from .errors import ContractNotImplementedError


def verify_phase_gate(*, bootstrap_only: bool = False) -> bool:
    if not bootstrap_only:
        raise ContractNotImplementedError("R0-T07")
    return False


def verify_sec0_gate(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("SEC0-T07")
