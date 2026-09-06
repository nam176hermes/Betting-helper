import test from "node:test";
import { assertBodyCaptureDisabled } from "../../src/e0/body-policy.js";
void test("E0-T03 is intentionally unimplemented", () => {
    assertBodyCaptureDisabled();
});
