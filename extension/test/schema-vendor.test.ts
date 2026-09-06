import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

import type { AnySchemaObject } from "ajv";

import { parseStrictJson } from "../src/canonical.js";
import { validateArtifact } from "../src/schema-registry.js";

const vendor = "vendor/hybrid-discovery-v6.3.6";
const schemas = readdirSync(`${vendor}/schemas`).map(
  (name) => parseStrictJson(readFileSync(`${vendor}/schemas/${name}`)) as AnySchemaObject,
);

void test("vendored schema registry validates its capability manifest", () => {
  const manifest = parseStrictJson(
    readFileSync(`${vendor}/security/discovery-capability-manifest.v1.json`),
  ) as Record<string, unknown>;
  validateArtifact(manifest, "urn:hybrid-discovery:v6.2:capability-manifest", schemas);
  assert.throws(
    () => { validateArtifact({ ...manifest, unexpected: true }, "urn:hybrid-discovery:v6.2:capability-manifest", schemas); },
    /E_SCHEMA:INVALID/u,
  );
});

void test("root lock and registry are the exact vendored copies", () => {
  const manifest = parseStrictJson(
    readFileSync(`${vendor}/SCHEMA_SHA256.json`),
  ) as Record<string, unknown>;
  const lock = parseStrictJson(readFileSync("schema-lock.json")) as Record<string, unknown>;
  assert.equal(lock.vendor_tree_sha256, manifest.tree_sha256);
  assert.deepEqual(lock.files, manifest.files);
  assert.deepEqual(
    readFileSync("task-command-registry.json"),
    readFileSync(`${vendor}/docs/registries/task-command-registry.v1.json`),
  );
});
