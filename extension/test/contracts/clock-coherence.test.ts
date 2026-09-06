import { strict as assert } from "node:assert";
import test from "node:test";
import {
  closeClockMapping,
  reopenClockMapping,
  selectClockMapping,
} from "../../src/contracts/clock-vectors.js";

void test("closed mappings retain history and cannot reopen or be selected", () => {
  const mappingId = `MAP:${"c".repeat(64)}`;
  const history = closeClockMapping(mappingId, "SLEEP_RESUME");
  assert.deepEqual(history, [{
    mapping_id: mappingId,
    reason: "SLEEP_RESUME",
    permanent: true,
    reopen_permitted: false,
  }]);
  assert.throws(() => reopenClockMapping(mappingId, history), {
    message: "E_MAPPING_PERMANENTLY_CLOSED",
  });
  assert.throws(
    () => selectClockMapping([{ mapping_id: mappingId, width_us: 1, valid_from_us: 1 }], history),
    { message: "E_NO_VALID_MAPPING" },
  );
});
