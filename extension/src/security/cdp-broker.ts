import { ContractNotImplementedError } from "../errors.js";
export const sendLiteralCommand = (): never => {
  throw new ContractNotImplementedError("SEC0-T02");
};
export class ClosedCdpBroker {
  readonly taskId = "SEC0-T02";
  constructor() { throw new ContractNotImplementedError("SEC0-T02"); }
}
