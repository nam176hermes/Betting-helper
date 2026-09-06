from .errors import ContractNotImplementedError


class CoherenceController:
    def evaluate_release(self, *_args: object, **_kwargs: object) -> None:
        raise ContractNotImplementedError("F0A-T06")
