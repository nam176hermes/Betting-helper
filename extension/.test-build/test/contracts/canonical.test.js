import test from "node:test";
import { canonicalContentHash } from "../..//src/canonical.js";
void test("F0A-T01 is intentionally unimplemented", () => {
    void canonicalContentHash("x", {});
});
