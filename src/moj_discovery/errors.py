class ContractNotImplementedError(NotImplementedError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"E_CONTRACT_NOT_IMPLEMENTED:{task_id}")
