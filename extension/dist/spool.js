import { ContractNotImplementedError } from "./errors.js";
export class Spool {
    append(value) {
        Object.is(value, value);
        throw new ContractNotImplementedError("F0A-T03");
    }
}
