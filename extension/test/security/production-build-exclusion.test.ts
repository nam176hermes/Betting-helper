import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";

import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";

export const testSecurityBoundary = (): void => {
  const vectors = {
    allow: "SEC_PRODUCTION_BUILD_EXCLUSION-ALLOW",
    deny: "SEC_PRODUCTION_BUILD_EXCLUSION-DENY",
    mutate: "SEC_PRODUCTION_BUILD_EXCLUSION-MUTATE",
  };
  const build = JSON.parse(readFileSync(resolve(process.cwd(), "extension/tsconfig.build.json"), "utf8")) as {
    exclude: unknown;
  };
  assert.deepEqual(build.exclude, ["test", "test-red", "test-harness", "tools"], vectors.allow);
  const distFiles = readdirSync(resolve("extension/dist"), { recursive: true }).map(String);
  assert.equal(distFiles.some((path) => /(?:test|harness|tools)/u.test(path)), false, vectors.deny);
  assert.equal(verifyCapabilityGraph(resolve("extension/src")).includes("E_COMPILED_CHUNK_SET"), false);

  const root = mkdtempSync(resolve(tmpdir(), "sec-build-"));
  cpSync(resolve("extension/src"), resolve(root, "extension/src"), { recursive: true });
  cpSync(resolve("extension/dist"), resolve(root, "extension/dist"), { recursive: true });
  cpSync(resolve("extension/manifest.json"), resolve(root, "extension/manifest.json"));
  mkdirSync(resolve(root, "extension/dist/test-harness"), { recursive: true });
  writeFileSync(resolve(root, "extension/dist/test-harness/privileged.js"), "export const escape=true");
  assert.ok(
    verifyCapabilityGraph(resolve(root, "extension/src")).includes("E_COMPILED_CHUNK_SET"),
    vectors.mutate,
  );

  const liveScratch = mkdtempSync(resolve(tmpdir(), "live-package-exclusion-"));
  const environment: NodeJS.ProcessEnv = {PATH: process.env["PATH"], UV_OFFLINE: "1",
    PYTHONDONTWRITEBYTECODE: "1", HOME: resolve(liveScratch, "home"),
    UV_CACHE_DIR: resolve(liveScratch, "uv-cache")};
  if (process.env["UV_PROJECT_ENVIRONMENT"]) environment["UV_PROJECT_ENVIRONMENT"] = process.env["UV_PROJECT_ENVIRONMENT"];
  const script = `
import sys
from pathlib import Path
from tools.qualify_live_platform import build_live_extension
from tools.verify_live_package import verify_live_package
package, _ = build_live_extension(Path(sys.argv[1]))
assert verify_live_package(package)['result'] == 'PASS'
def denied(code):
    try:
        verify_live_package(package)
    except ValueError as error:
        assert str(error) == code, str(error)
    else:
        raise AssertionError('TEST_ONLY_PRIVILEGED_PACKAGE_ACCEPTED')
harness = package / 'src/live/test-harness/privileged.js'
harness.parent.mkdir()
harness.write_text('export const TEST_ONLY_privileged = true;')
denied('E_LIVE_PACKAGE_INVENTORY')
harness.unlink()
module = package / 'src/live/background.js'
original = module.read_text()
for dependency in ('./test-harness/privileged.js', 'node:fs'):
    module.write_text(original + '\\nimport "' + dependency + '";\\n')
    denied('E_LIVE_PACKAGE_IMPORT')
module.write_text(original)
assert verify_live_package(package)['result'] == 'PASS'
print('CURRENT_LIVE_PACKAGE_EXCLUSION_PASS')
`;
  const checked = spawnSync("uv", ["run", "--frozen", "--offline", "python", "-B", "-c", script,
    resolve(liveScratch, "build")], {cwd: process.cwd(), env: environment, encoding: "utf8", timeout: 90000});
  assert.equal(checked.status, 0, checked.stderr);
  assert.equal(checked.stdout.trim(), "CURRENT_LIVE_PACKAGE_EXCLUSION_PASS");
};

void test("production compilation excludes review and harness inputs", testSecurityBoundary);
