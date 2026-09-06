from .errors import ContractNotImplementedError


class Ingestor:
    def apply(self, *_args: object, **_kwargs: object) -> None:
        raise ContractNotImplementedError("F0A-T04")
