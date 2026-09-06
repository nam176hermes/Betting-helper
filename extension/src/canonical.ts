import { ContractNotImplementedError } from "./errors.js";

import canonicalize from "canonicalize";

interface CanonicalDomain {
  readonly artifact_type: string;
  readonly domain: string;
  readonly excluded_json_pointers: readonly string[];
}

interface DomainValidationClass {
  readonly artifact_types: readonly string[];
  readonly class_id: string;
}

interface SchemaBindingGroup {
  readonly artifact_types: readonly string[];
  readonly required_excluded_json_pointers: readonly string[];
}

export interface CanonicalRegistry {
  readonly domains: readonly CanonicalDomain[];
  readonly domain_validation_classes: readonly DomainValidationClass[];
  readonly schema_binding_groups: readonly SchemaBindingGroup[];
}

class StrictJsonParser {
  private offset = 0;

  public constructor(private readonly source: string) {}

  public parse(): unknown {
    const value = this.value();
    this.whitespace();
    if (this.offset !== this.source.length) {
      throw new Error("MALFORMED_UTF8_OR_JSON");
    }
    return value;
  }

  private value(): unknown {
    this.whitespace();
    const character = this.source[this.offset];
    if (character === "{") return this.object();
    if (character === "[") return this.array();
    if (character === '"') return this.string();
    if (character === "t") return this.literal("true", true);
    if (character === "f") return this.literal("false", false);
    if (character === "n") return this.literal("null", null);
    return this.number();
  }

  private object(): Record<string, unknown> {
    this.offset += 1;
    const result: Record<string, unknown> = {};
    const keys = new Set<string>();
    this.whitespace();
    if (this.source[this.offset] === "}") {
      this.offset += 1;
      return result;
    }
    for (;;) {
      this.whitespace();
      if (this.source[this.offset] !== '"') throw new Error("MALFORMED_UTF8_OR_JSON");
      const key = this.string();
      if (keys.has(key)) throw new Error("DUPLICATE_JSON_KEY");
      keys.add(key);
      this.whitespace();
      if (this.source[this.offset] !== ":") throw new Error("MALFORMED_UTF8_OR_JSON");
      this.offset += 1;
      result[key] = this.value();
      this.whitespace();
      const delimiter = this.source[this.offset];
      if (delimiter === "}") {
        this.offset += 1;
        return result;
      }
      if (delimiter !== ",") throw new Error("MALFORMED_UTF8_OR_JSON");
      this.offset += 1;
    }
  }

  private array(): unknown[] {
    this.offset += 1;
    const result: unknown[] = [];
    this.whitespace();
    if (this.source[this.offset] === "]") {
      this.offset += 1;
      return result;
    }
    for (;;) {
      result.push(this.value());
      this.whitespace();
      const delimiter = this.source[this.offset];
      if (delimiter === "]") {
        this.offset += 1;
        return result;
      }
      if (delimiter !== ",") throw new Error("MALFORMED_UTF8_OR_JSON");
      this.offset += 1;
    }
  }

  private string(): string {
    const start = this.offset;
    this.offset += 1;
    let escaped = false;
    while (this.offset < this.source.length) {
      const character = this.source[this.offset];
      this.offset += 1;
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        return JSON.parse(this.source.slice(start, this.offset)) as string;
      }
    }
    throw new Error("MALFORMED_UTF8_OR_JSON");
  }

  private literal(token: string, value: boolean | null): boolean | null {
    if (!this.source.startsWith(token, this.offset)) throw new Error("MALFORMED_UTF8_OR_JSON");
    this.offset += token.length;
    return value;
  }

  private number(): number {
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(
      this.source.slice(this.offset),
    );
    if (match === null) throw new Error("MALFORMED_UTF8_OR_JSON");
    this.offset += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) throw new Error("MALFORMED_UTF8_OR_JSON");
    return value;
  }

  private whitespace(): void {
    while ([" ", "\t", "\n", "\r"].includes(this.source[this.offset] ?? "x")) {
      this.offset += 1;
    }
  }
}

const validateUnicode = (value: unknown): void => {
  if (typeof value === "string") {
    for (let index = 0; index < value.length; index += 1) {
      const unit = value.charCodeAt(index);
      if (unit >= 0xd800 && unit <= 0xdbff) {
        const next = value.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error("NON_NFC_OR_INVALID_UNICODE");
        index += 1;
      } else if (unit >= 0xdc00 && unit <= 0xdfff) {
        throw new Error("NON_NFC_OR_INVALID_UNICODE");
      }
    }
    if (value.normalize("NFC") !== value) throw new Error("NON_NFC_OR_INVALID_UNICODE");
  } else if (Array.isArray(value)) {
    for (const item of value) validateUnicode(item);
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      validateUnicode(key);
      validateUnicode(item);
    }
  }
};

export const parseStrictJson = (raw: Uint8Array): unknown => {
  if (raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) {
    throw new Error("MALFORMED_UTF8_OR_JSON");
  }
  let source: string;
  try {
    source = new TextDecoder("utf-8", { fatal: true }).decode(raw);
  } catch {
    throw new Error("MALFORMED_UTF8_OR_JSON");
  }
  const value = new StrictJsonParser(source).parse();
  validateUnicode(value);
  return value;
};

export const canonicalContentHash = (
  artifactType: string,
  value: unknown,
  registry?: CanonicalRegistry,
): Promise<string> => {
  if (registry === undefined) throw new ContractNotImplementedError("F0A-T01");
  const preimage = canonicalPreimage(artifactType, value, registry);
  return crypto.subtle.digest("SHA-256", preimage).then((digest) =>
    Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(""),
  );
};

export const verifyCanonicalContentHash = async (
  artifactType: string,
  value: unknown,
  expectedHash: string,
  registry: CanonicalRegistry,
): Promise<void> => {
  const computed = await canonicalContentHash(artifactType, value, registry);
  if (computed !== expectedHash) throw new Error("CONTENT_HASH_MISMATCH");
};

export const canonicalPreimage = (
  artifactType: string,
  value: unknown,
  registry: CanonicalRegistry,
): Uint8Array<ArrayBuffer> => {
  const domains = registry.domains.filter((entry) => entry.artifact_type === artifactType);
  if (domains.length !== 1) throw new Error("UNSUPPORTED_VERSION_OR_ALGORITHM");
  const domain = domains[0];
  if (domain === undefined || value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("SCHEMA_INVALID");
  }
  validateRegisteredExclusions(artifactType, domain.excluded_json_pointers, registry);
  const projected = structuredClone(value) as Record<string, unknown>;
  const excludedKeys = new Set<string>();
  for (const pointer of domain.excluded_json_pointers) {
    if (!/^\/(?:[^/~]|~[01])+$/u.test(pointer)) throw new Error("UNREGISTERED_HASH_EXCLUSION");
    const key = pointer.slice(1).replaceAll("~1", "/").replaceAll("~0", "~");
    if (!Object.hasOwn(projected, key)) {
      throw new Error("SCHEMA_INVALID_BEFORE_CANONICAL_HASH");
    }
    excludedKeys.add(key);
  }
  const hashable = Object.fromEntries(
    Object.entries(projected).filter(([key]) => !excludedKeys.has(key)),
  );
  validateUnicode(hashable);
  const canonical = canonicalize(hashable);
  if (canonical === undefined) throw new Error("SCHEMA_INVALID");
  const preimage = new Uint8Array([
    ...new TextEncoder().encode(domain.domain),
    ...new TextEncoder().encode(canonical),
  ]);
  return preimage;
};

const validateRegisteredExclusions = (
  artifactType: string,
  exclusions: readonly string[],
  registry: CanonicalRegistry,
): void => {
  const classes = registry.domain_validation_classes.filter((entry) =>
    entry.artifact_types.includes(artifactType),
  );
  if (classes.length !== 1) throw new Error("UNREGISTERED_HASH_EXCLUSION");
  const domainClass = classes[0];
  if (domainClass?.class_id === "GOVERNED_NO_EXCLUSION") {
    if (exclusions.length !== 0) throw new Error("UNREGISTERED_HASH_EXCLUSION");
    return;
  }
  if (domainClass?.class_id !== "SCHEMA_GATED_SELF_HASH") {
    throw new Error("UNREGISTERED_HASH_EXCLUSION");
  }
  const groups = registry.schema_binding_groups.filter((entry) =>
    entry.artifact_types.includes(artifactType),
  );
  const registered = groups[0]?.required_excluded_json_pointers;
  if (
    groups.length !== 1 ||
    registered === undefined ||
    registered.length !== exclusions.length ||
    registered.some((pointer, index) => pointer !== exclusions[index])
  ) {
    throw new Error("UNREGISTERED_HASH_EXCLUSION");
  }
};
