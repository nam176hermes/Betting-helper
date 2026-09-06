import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { verifyCapabilityGraph } from "../../tools/verify-capability-graph.js";
export const testSecurityBoundary = () => {
    const vectors = {
        allow: "SEC_PRODUCTION_BUILD_EXCLUSION-ALLOW",
        deny: "SEC_PRODUCTION_BUILD_EXCLUSION-DENY",
        mutate: "SEC_PRODUCTION_BUILD_EXCLUSION-MUTATE",
    };
    const build = JSON.parse(readFileSync(resolve(process.cwd(), "extension/tsconfig.build.json"), "utf8"));
    assert.deepEqual(build.exclude, ["test", "test-red", "test-harness", "tools"], vectors.allow);
    const distFiles = readdirSync(resolve("extension/dist"), { recursive: true }).map(String);
    assert.equal(distFiles.some((path) => /(?:test|harness|tools)/u.test(path)), false, vectors.deny);
    const root = mkdtempSync(resolve(tmpdir(), "sec-build-"));
    cpSync(resolve("extension/src"), resolve(root, "extension/src"), { recursive: true });
    cpSync(resolve("extension/dist"), resolve(root, "extension/dist"), { recursive: true });
    cpSync(resolve("extension/manifest.json"), resolve(root, "extension/manifest.json"));
    mkdirSync(resolve(root, "extension/dist/test-harness"), { recursive: true });
    writeFileSync(resolve(root, "extension/dist/test-harness/privileged.js"), "export const escape=true");
    assert.ok(verifyCapabilityGraph(resolve(root, "extension/src")).includes("E_COMPILED_CHUNK_SET"), vectors.mutate);
};
void test("production compilation excludes review and harness inputs", testSecurityBoundary);
