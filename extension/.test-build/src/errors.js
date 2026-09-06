export class ContractNotImplementedError extends Error {
    constructor(taskId) { super(`E_CONTRACT_NOT_IMPLEMENTED:${taskId}`); }
}
