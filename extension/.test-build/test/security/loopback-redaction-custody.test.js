import assert from "node:assert/strict";
import test from "node:test";
import { projectBeforePersistence } from "../../src/security/redaction.js";
void test("unconfigured projector fails closed", async () => {
    await assert.rejects(async () => await Reflect.apply(projectBeforePersistence, undefined, [undefined]));
});
