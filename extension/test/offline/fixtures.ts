import { readFileSync, readdirSync } from "node:fs";
import type { AnySchemaObject } from "ajv/dist/2020.js";
import type { CanonicalRegistry } from "../../src/canonical.js";
const vendor = "vendor/hybrid-discovery-v6.3.6";
export const schemas = readdirSync(`${vendor}/schemas`).filter(n => n.endsWith(".json"))
.map(n => JSON.parse(readFileSync(`${vendor}/schemas/${n}`, "utf8")) as AnySchemaObject);
export const canonicalRegistry = JSON.parse(readFileSync(`${vendor}/registries/canonical-hash-domains.v1.json`, "utf8")) as CanonicalRegistry;
// Synthetic accounting input, never observed football data or an authorization receipt.
export const raw = {
  "schema_version": "raw-observation/v1",
  "raw_observation_id": "observation:ef134f2a180ba05de91ab32d2976f51de13b68d823ea784171b1b0dafee67be4",
  "observation_kind": "TERMINAL",
  "pack_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "build_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "implementation_baseline_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "capability_manifest_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "discovery_run_id": "00000000-0000-4000-8000-000000000010",
  "run_receipt_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "stream_id": "00000000-0000-4000-8000-000000000002",
  "generation": "0",
  "sequence": "1",
  "context": {
    "context_kind": "RUN_BOUND_NOT_DOCUMENT",
    "browser_run_id": "00000000-0000-4000-8000-000000000001",
    "browser_boot_id": "00000000-0000-4000-8000-000000000001",
    "binding_reason": "TERMINAL_ACCOUNTING"
  },
  "clock_context": {
    "clock_domain_id": "00000000-0000-4000-8000-000000000003",
    "boot_id": "00000000-0000-4000-8000-000000000001",
    "unit": "MICROSECOND",
    "monotonic_value": "1",
    "resolution_us": "1",
    "owner": "BACKEND",
    "mapping_id": "NOT_APPLICABLE",
    "mapping_status": "NOT_APPLICABLE"
  },
  "sanitizer_version": "sanitizer/v1",
  "content_hash": "c179fe89b16558a24ffcc15cd6e0ff0aabae786c6fa37d267db6b1d937d05b43",
  "production_authority": "NONE",
  "facts": {
    "terminal_code": "MANUAL_STOP",
    "final_generation": "0",
    "final_sequence": "1",
    "observation_count": "1",
    "gap_count": "0",
    "safety_disposition": "PARTIAL_EVIDENCE_ONLY"
  }
};
