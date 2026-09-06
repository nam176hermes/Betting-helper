import assert from "node:assert/strict";
import test from "node:test";
import { bootstrapSelfCheck } from "../src/bootstrap.js";
void test("bootstrap is inert", () => {
    assert.deepEqual(bootstrapSelfCheck(), { READY_TO_IMPLEMENT_DISCOVERY_PACK: "NO", AUTHORIZED_PRODUCTION_PHASES: "NONE" });
});
