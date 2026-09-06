import test from "node:test";
import { verifyE0Preflight } from "../../src/e0/e0-preflight.js";
void test("E0-T01 is intentionally unimplemented", () => {
    verifyE0Preflight();
});
