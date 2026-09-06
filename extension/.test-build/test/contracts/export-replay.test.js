import test from "node:test";
import { ContractNotImplementedError } from "../../src/errors.js";
const raise = (id) => { throw new ContractNotImplementedError(id); };
void test("F0A-T08 is intentionally unimplemented", () => {
    raise("F0A-T08");
});
