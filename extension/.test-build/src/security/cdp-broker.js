import { ContractNotImplementedError } from "../errors.js";
export const sendLiteralCommand = () => {
    throw new ContractNotImplementedError("SEC0-T02");
};
export class ClosedCdpBroker {
    taskId = "SEC0-T02";
    constructor() { throw new ContractNotImplementedError("SEC0-T02"); }
}
