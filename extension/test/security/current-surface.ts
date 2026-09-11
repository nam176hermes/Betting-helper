import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { bootstrapSelfCheck } from "../../src/bootstrap.js";
import { ContractNotImplementedError } from "../../src/errors.js";
import { ClosedCdpBroker, sendLiteralCommand } from "../../src/security/cdp-broker.js";
import { assertOwnedTarget } from "../../src/security/target-policy.js";
import { verifyCapabilityGraph, verifyCapabilityManifest } from "../../tools/verify-capability-graph.js";
// Actual current codec, binding, UI command and durable-spool obligations remain
// mandatory alongside the inherited denial/mutation corpus.
import "../live/wire.test.js";
import "../live/capture.test.js";
import "../live/panel.test.js";
import "../live/spool.test.js";

/** Current package scope; never report the dormant metadata runtime as implemented. */
export function verifyCurrentSurface(): void {
  assert.deepEqual(bootstrapSelfCheck(), {
    READY_TO_IMPLEMENT_DISCOVERY_PACK: "NO", AUTHORIZED_PRODUCTION_PHASES: "NONE",
  });
  assert.throws(sendLiteralCommand, ContractNotImplementedError);
  assert.throws(assertOwnedTarget, ContractNotImplementedError);
  assert.throws(() => new ClosedCdpBroker(), ContractNotImplementedError);
  assert.deepEqual(verifyCapabilityManifest(resolve("extension/manifest.json"),
    resolve("vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json")), []);
  const scratch = mkdtempSync(resolve(tmpdir(), "part-b-security-surface-"));
  const closed = resolve(scratch, "inert");
  const emitted = resolve(scratch, "inert-emitted");
  mkdirSync(resolve(closed, "security"), {recursive: true});
  mkdirSync(resolve(emitted, "security"), {recursive: true});
  for (const file of ["bootstrap.ts", "errors.ts", "security/cdp-broker.ts", "security/target-policy.ts"]) {
    copyFileSync(resolve("extension/src", file), resolve(closed, file));
    const javascript = file.replace(/\.ts$/u, ".js");
    copyFileSync(new URL(`../../src/${javascript}`, import.meta.url), resolve(emitted, javascript));
  }
  // These are current source bytes. Unresolved imports or added privileges fail
  // the unchanged v1 scanner; the full negative corpus still calls that scanner.
  assert.deepEqual(verifyCapabilityGraph(closed), []);
  assert.deepEqual(verifyCapabilityGraph(emitted), []);
  const environment: NodeJS.ProcessEnv = {
    PATH: process.env["PATH"], UV_OFFLINE: "1", PYTHONDONTWRITEBYTECODE: "1",
  };
  const pythonEnvironment = process.env["UV_PROJECT_ENVIRONMENT"];
  if (pythonEnvironment) environment["UV_PROJECT_ENVIRONMENT"] = pythonEnvironment;
  const result = spawnSync("uv", ["run", "--frozen", "--offline", "python", "-B", "-c",
    "import json,sys;from pathlib import Path;from tools.qualify_live_platform import build_live_extension;" +
    "build_live_extension(Path(sys.argv[1]));print('PART_B_STATIC_PACKAGE_BOUNDARY_PASS; LEGACY_PRODUCT_IMPLEMENTATION_NOT_QUALIFIED')",
    resolve(scratch, "build")], {cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 60000});
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /PART_B_STATIC_PACKAGE_BOUNDARY_PASS; LEGACY_PRODUCT_IMPLEMENTATION_NOT_QUALIFIED/u);
}
