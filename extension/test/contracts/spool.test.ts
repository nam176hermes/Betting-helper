import test from "node:test";
import { Spool } from "../../src/spool.js";
import type { PersistableSanitizedObservationV1 } from "../../src/security/redaction.js";

void test("F0A-T03 is intentionally unimplemented", () => {
  const value = undefined as never as PersistableSanitizedObservationV1;
  void new Spool().append(value);
});
