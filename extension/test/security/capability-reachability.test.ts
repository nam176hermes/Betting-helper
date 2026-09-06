import test from "node:test";
import { assertClosedPrivilegeGraph } from "../../src/security/capability-graph.js";

void test("SEC0-T05 is intentionally unimplemented", () => {
  assertClosedPrivilegeGraph();
});

