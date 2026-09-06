from .errors import ContractNotImplementedError


def build_scope_input_view(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("SCOPE0-T01")
