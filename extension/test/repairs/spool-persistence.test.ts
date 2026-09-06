import assert from "node:assert/strict";
import { test } from "node:test";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Spool } from "../../src/spool.js";
import type { PersistableSanitizedObservationV1 } from "../../src/security/redaction.js";

void test("append rejects malformed unvalidated input before touching storage", async () => {
  // This deliberate trust-boundary violation must never reach indexedDB.open.
  await assert.rejects(
    async () => new Spool().append({} as PersistableSanitizedObservationV1),
    /E_SPOOL_UNVALIDATED/,
  );
});

void test("the legacy Node entrypoint cannot qualify a browser case", () => {
  const child = fileURLToPath(new URL("../../test-harness/indexeddb-crash-child.js", import.meta.url));
  const result = spawnSync(process.execPath, [child, "--vector-id", "IDB-04-AFTER-COMMIT"], { encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04/);
  assert.equal(result.stdout, "");
});
