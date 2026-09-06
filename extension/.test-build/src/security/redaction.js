import { ContractNotImplementedError } from "../errors.js";
export const projectBeforePersistence = (input) => {
    String(input);
    throw new ContractNotImplementedError("SEC0-T06");
};
