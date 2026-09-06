from .errors import ContractNotImplementedError


def validate_graph_partition(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("R0-T04")


def validate_task_dependencies(*_args: object, **_kwargs: object) -> None:
    raise ContractNotImplementedError("R0-T04")
