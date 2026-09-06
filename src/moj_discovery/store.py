from .errors import ContractNotImplementedError


class RunStore:
    def bootstrap_v1(self, *_args: object, **_kwargs: object) -> None:
        raise ContractNotImplementedError("F0A-T04")
