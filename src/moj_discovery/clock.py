from .errors import ContractNotImplementedError


class ClockMapper:
    def select(self, *_args: object, **_kwargs: object) -> None:
        raise ContractNotImplementedError("F0A-T06")
