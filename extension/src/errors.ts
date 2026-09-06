export class ContractNotImplementedError extends Error {
  constructor(taskId: string) { super(`E_CONTRACT_NOT_IMPLEMENTED:${taskId}`); }
}

