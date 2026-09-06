import test from "node:test";
import { Spool } from "../../src/spool.js";
void test("F0A-T03 is intentionally unimplemented", () => {
    const value = undefined;
    void new Spool().append(value);
});
