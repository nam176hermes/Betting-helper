import test from "node:test";
import { validateArtifact } from "../../src/schema-registry.js";

void test("F0A-T02 is intentionally unimplemented", () => {
  validateArtifact({});
});

