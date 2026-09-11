/* eslint-disable @typescript-eslint/no-unnecessary-condition -- fail-closed AST checks intentionally retain guards for malformed and JavaScript inputs */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, relative, resolve, sep } from "node:path";
import process from "node:process";
import {
  type BinaryExpression,
  type Expression,
  type Node,
  type SourceFile,
  ScriptKind,
  ScriptTarget,
  SyntaxKind,
  createSourceFile,
  isArrowFunction,
  isArrayLiteralExpression,
  isAsExpression,
  isBinaryExpression,
  isCallExpression,
  isBlock,
  isClassDeclaration,
  isElementAccessExpression,
  isExportDeclaration,
  isFunctionDeclaration,
  isFunctionExpression,
  isIdentifier,
  isImportDeclaration,
  isIfStatement,
  isMethodDeclaration,
  isNewExpression,
  isNonNullExpression,
  isNoSubstitutionTemplateLiteral,
  isObjectBindingPattern,
  isObjectLiteralExpression,
  isParameter,
  isParenthesizedExpression,
  isPropertyAccessExpression,
  isPropertyAssignment,
  isQualifiedName,
  isReturnStatement,
  isShorthandPropertyAssignment,
  isStringLiteral,
  isSatisfiesExpression,
  isVariableDeclaration,
  isVariableStatement,
} from "typescript";

import { parseStrictJson } from "../src/canonical.js";

const ALLOWED_CDP = new Set(["Network.enable", "Network.disable"]);
const ALLOWED_BARE_IMPORTS = new Set(["ajv-formats", "ajv/dist/2020.js", "canonicalize"]);
const FORBIDDEN_CDP_DOMAINS = new Set([
  "CSS",
  "DOM",
  "Emulation",
  "Fetch",
  "Input",
  "Runtime",
  "Storage",
]);
const EXPECTED_ENABLE_ARGUMENTS = {
  maxPostDataSize: 0,
  maxResourceBufferSize: 2_097_152,
  maxTotalBufferSize: 33_554_432,
};
const ALLOWED_NETWORK_EVENTS = [
  "Network.requestWillBeSent",
  "Network.responseReceived",
  "Network.dataReceived",
  "Network.loadingFinished",
  "Network.loadingFailed",
  "Network.webSocketCreated",
  "Network.webSocketWillSendHandshakeRequest",
  "Network.webSocketHandshakeResponseReceived",
  "Network.webSocketFrameReceived",
  "Network.webSocketFrameSent",
  "Network.webSocketFrameError",
  "Network.webSocketClosed",
  "Network.eventSourceMessageReceived",
];
const PUBLIC_MESSAGE_TYPES = [
  "DISCOVERY_BEGIN_V1",
  "DISCOVERY_STOP_V1",
  "DISCOVERY_STATUS_GET_V1",
  "DISCOVERY_EXPORT_SANITIZED_V1",
  "DESTROY_WHOLE_RUN_WORKING_STORAGE_V1",
];
const STORAGE_METHOD_NAMES = new Set([
  "abort",
  "add",
  "bound",
  "close",
  "continue",
  "createIndex",
  "createObjectStore",
  "get",
  "objectStore",
  "open",
  "openCursor",
  "put",
  "transaction",
]);
const STORAGE_HANDLER_NAMES = new Set([
  "onabort",
  "onblocked",
  "oncomplete",
  "onerror",
  "onsuccess",
  "onupgradeneeded",
  "onversionchange",
]);
const DESTRUCTIVE_STORAGE_NAMES = new Set([
  "advance",
  "clear",
  "compact",
  "continuePrimaryKey",
  "delete",
  "deleteDatabase",
  "deleteIndex",
  "deleteObjectStore",
  "restore",
  "update",
]);
const UNLISTED_STORAGE_METHOD_NAMES = new Set([
  "count",
  "databases",
  "getAll",
  "getAllKeys",
  "getKey",
  "openKeyCursor",
]);
const DOM_MUTATION_NAMES = new Set([
  "append",
  "appendChild",
  "after",
  "before",
  "click",
  "deleteContents",
  "deleteFromDocument",
  "extractContents",
  "insertAdjacentElement",
  "insertAdjacentHTML",
  "insertAdjacentText",
  "insertBefore",
  "prepend",
  "remove",
  "removeAttribute",
  "removeChild",
  "replaceChild",
  "replaceChildren",
  "replaceWith",
  "setAttribute",
  "setProperty",
  "surroundContents",
  "toggleAttribute",
  "write",
  "writeln",
]);
const NAVIGATION_MUTATION_NAMES = new Set([
  "assign",
  "back",
  "forward",
  "go",
  "pushState",
  "reload",
  "replace",
  "replaceState",
]);
const OWNER_IMPORTED_HELPERS = new Map<string, ReadonlySet<string>>([
  ["cdp-broker", new Set(["projectCdpEvent", "safetyStopAndSealRun"])],
  ["loopback", new Set(["decodeAuthenticatedFact", "encodeAuthenticatedFact"])],
  ["run-controller", new Set(["handlePublicMessage"])],
  ["target-policy", new Set(["projectNavigationEvent", "safetyStopAndSealRun"])],
]);

type JsonObject = Record<string, unknown>;

type CapabilityPolicy = Readonly<{
  chromeOwners: ReadonlyMap<string, string>;
  storageHandlers: ReadonlySet<string>;
  storageMethods: ReadonlySet<string>;
  storageOwner: string;
}>;

const allFilesBelow = (root: string): string[] => readdirSync(root).flatMap((name) => {
  const path = resolve(root, name);
  return statSync(path).isDirectory()
    ? allFilesBelow(path)
    : [path];
});

const filesBelow = (root: string): string[] =>
  allFilesBelow(root).filter((path) => path.endsWith(".ts") || path.endsWith(".js"));

const unique = (values: readonly string[]): string[] => [...new Set(values)];

const isRecord = (value: unknown): value is JsonObject =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const equalJson = (left: unknown, right: unknown): boolean => {
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length && left.every((item, index) => equalJson(item, right[index]));
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return equalJson(leftKeys, rightKeys) && leftKeys.every((key) => equalJson(left[key], right[key]));
  }
  return left === right;
};

const loadCapabilityPolicy = (): CapabilityPolicy | undefined => {
  try {
    const manifest = parseStrictJson(readFileSync(resolve(
      process.cwd(),
      "vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json",
    )));
    if (!isRecord(manifest)
      || !isRecord(manifest.privileged_chrome_api_policy)
      || !isRecord(manifest.privileged_storage_api_policy)) return undefined;
    const chrome = manifest.privileged_chrome_api_policy;
    const storage = manifest.privileged_storage_api_policy;
    const methodCalls = chrome.allowed_method_calls;
    const eventListeners = chrome.allowed_event_listeners;
    const storageMethods = storage.allowed_method_calls;
    const storageHandlers = storage.allowed_event_handlers;
    if (!Array.isArray(methodCalls)
      || !Array.isArray(eventListeners)
      || !Array.isArray(storageMethods)
      || !Array.isArray(storageHandlers)
      || typeof storage.sole_owner !== "string") return undefined;
    const chromeOwners = new Map<string, string>();
    const chromeCalls = [
      ...(methodCalls as unknown[]),
      ...(eventListeners as unknown[]),
    ];
    for (const value of chromeCalls) {
      if (!isRecord(value) || typeof value.member !== "string" || typeof value.owner !== "string") {
        return undefined;
      }
      chromeOwners.set(value.member, value.owner);
    }
    const storageMethodSet = new Set<string>();
    for (const value of storageMethods) {
      if (!isRecord(value) || typeof value.member !== "string" || value.owner !== storage.sole_owner) {
        return undefined;
      }
      storageMethodSet.add(value.member);
    }
    const storageHandlerSet = new Set<string>();
    for (const value of storageHandlers) {
      if (!isRecord(value) || typeof value.member !== "string" || value.owner !== storage.sole_owner) {
        return undefined;
      }
      storageHandlerSet.add(value.member);
    }
    const expectedChrome = [
      "chrome.action.onClicked.addListener",
      "chrome.debugger.attach",
      "chrome.debugger.detach",
      "chrome.debugger.onDetach.addListener",
      "chrome.debugger.onEvent.addListener",
      "chrome.debugger.sendCommand",
      "chrome.runtime.onMessage.addListener",
      "chrome.scripting.executeScript",
      "chrome.webNavigation.getAllFrames",
      "chrome.webNavigation.onBeforeNavigate.addListener",
      "chrome.webNavigation.onCommitted.addListener",
      "chrome.webNavigation.onErrorOccurred.addListener",
      "chrome.webNavigation.onHistoryStateUpdated.addListener",
      "chrome.webNavigation.onReferenceFragmentUpdated.addListener",
      "chrome.webNavigation.onTabReplaced.addListener",
    ];
    if (!equalJson([...chromeOwners.keys()].sort(), expectedChrome)) return undefined;
    return {
      chromeOwners,
      storageHandlers: storageHandlerSet,
      storageMethods: storageMethodSet,
      storageOwner: storage.sole_owner,
    };
  } catch {
    return undefined;
  }
};

export const verifyCapabilityManifest = (
  manifestPath: string,
  canonicalManifestPath: string,
): string[] => {
  let actual: unknown;
  let canonical: unknown;
  try {
    actual = parseStrictJson(readFileSync(manifestPath));
    canonical = parseStrictJson(readFileSync(canonicalManifestPath));
  } catch {
    return ["E_MANIFEST_CAPABILITY_MISMATCH"];
  }
  if (!isRecord(actual) || !isRecord(canonical) || !isRecord(canonical.chrome_manifest)) {
    return ["E_MANIFEST_CAPABILITY_MISMATCH"];
  }
  const expected = canonical.chrome_manifest;
  const extensionIdentity = canonical.extension_identity;
  if (!equalJson(canonical.body_classes, []) || canonical.production_authority !== "NONE") {
    return ["E_BODY_CLASS_NOT_PERMITTED"];
  }
  if (!isRecord(extensionIdentity) || typeof extensionIdentity.manifest_public_key !== "string") {
    return ["E_MANIFEST_CAPABILITY_MISMATCH"];
  }
  const valid = expected.key === extensionIdentity.manifest_public_key
    && equalJson(actual, expected)
    && !(Array.isArray(actual.permissions) && actual.permissions.includes("nativeMessaging"));
  return valid ? [] : ["E_MANIFEST_CAPABILITY_MISMATCH"];
};

const constantString = (
  expression: Expression,
  constants: ReadonlyMap<string, string>,
): string | undefined => {
  if (isStringLiteral(expression) || isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text;
  }
  if (isIdentifier(expression)) return constants.get(expression.text);
  if (
    isParenthesizedExpression(expression)
    || isAsExpression(expression)
    || isSatisfiesExpression(expression)
    || isNonNullExpression(expression)
  ) {
    return constantString(expression.expression, constants);
  }
  if (isBinaryExpression(expression) && expression.operatorToken.kind === SyntaxKind.PlusToken) {
    const left = constantString(expression.left, constants);
    const right = constantString(expression.right, constants);
    return left === undefined || right === undefined ? undefined : left + right;
  }
  return undefined;
};

const expressionPath = (
  expression: Expression,
  constants: ReadonlyMap<string, string>,
): string[] | undefined => {
  if (isIdentifier(expression)) return [expression.text];
  if (
    isParenthesizedExpression(expression)
    || isAsExpression(expression)
    || isSatisfiesExpression(expression)
    || isNonNullExpression(expression)
  ) {
    return expressionPath(expression.expression, constants);
  }
  if (isBinaryExpression(expression) && expression.operatorToken.kind === SyntaxKind.CommaToken) {
    return expressionPath(expression.right, constants);
  }
  if (isPropertyAccessExpression(expression)) {
    const prefix = expressionPath(expression.expression, constants);
    return prefix === undefined ? undefined : [...prefix, expression.name.text];
  }
  if (isElementAccessExpression(expression)) {
    const prefix = expressionPath(expression.expression, constants);
    const property = constantString(expression.argumentExpression, constants);
    return prefix === undefined || property === undefined ? undefined : [...prefix, property];
  }
  return undefined;
};

const resolveAlias = (
  path: readonly string[] | undefined,
  aliases: ReadonlyMap<string, readonly string[]>,
): string[] | undefined => {
  if (path === undefined) return undefined;
  if (path.length === 0) return [];
  const alias = aliases.get(path[0] ?? "");
  return alias === undefined ? [...path] : [...alias, ...path.slice(1)];
};

const normalizeChromeRoot = (path: readonly string[] | undefined): string[] | undefined =>
  path !== undefined
  && ["globalThis", "self", "window"].includes(path[0] ?? "")
  && path[1] === "chrome"
    ? [...path.slice(1)]
    : path === undefined ? undefined : [...path];

const hasChromeRoot = (
  expression: Expression,
  constants: ReadonlyMap<string, string>,
): boolean => {
  const path = normalizeChromeRoot(expressionPath(expression, constants));
  if (path?.[0] === "chrome") return true;
  if (isElementAccessExpression(expression) || isPropertyAccessExpression(expression)) {
    return hasChromeRoot(expression.expression, constants);
  }
  if (
    isParenthesizedExpression(expression)
    || isAsExpression(expression)
    || isSatisfiesExpression(expression)
    || isNonNullExpression(expression)
  ) return hasChromeRoot(expression.expression, constants);
  return false;
};

const hasGlobalRoot = (expression: Expression): boolean => {
  if (isIdentifier(expression)) return ["globalThis", "self", "window"].includes(expression.text);
  if (isElementAccessExpression(expression) || isPropertyAccessExpression(expression)) {
    return hasGlobalRoot(expression.expression);
  }
  if (isParenthesizedExpression(expression)
    || isAsExpression(expression)
    || isSatisfiesExpression(expression)
    || isNonNullExpression(expression)) return hasGlobalRoot(expression.expression);
  return false;
};

const pathEndsWith = (path: readonly string[] | undefined, suffix: readonly string[]): boolean =>
  path !== undefined
  && path.length >= suffix.length
  && suffix.every((part, index) => path[path.length - suffix.length + index] === part);

const finalPathPart = (path: readonly string[] | undefined): string => path?.at(-1) ?? "";

const propertyName = (
  node: Node,
  constants: ReadonlyMap<string, string>,
): string | undefined => {
  if (isIdentifier(node) || isStringLiteral(node) || isNoSubstitutionTemplateLiteral(node)) {
    return node.text;
  }
  if (node.kind === SyntaxKind.ComputedPropertyName) {
    return constantString((node as Node & { expression: Expression }).expression, constants);
  }
  return undefined;
};

const objectValue = (
  expression: Expression,
  constants: ReadonlyMap<string, string>,
  objects: ReadonlyMap<string, unknown> = new Map(),
): unknown => {
  if (isIdentifier(expression) && objects.has(expression.text)) return objects.get(expression.text);
  if (isStringLiteral(expression) || isNoSubstitutionTemplateLiteral(expression)) return expression.text;
  if (expression.kind === SyntaxKind.TrueKeyword) return true;
  if (expression.kind === SyntaxKind.FalseKeyword) return false;
  if (expression.kind === SyntaxKind.NullKeyword) return null;
  if (expression.kind === SyntaxKind.NumericLiteral) return Number(expression.getText());
  if (isArrayLiteralExpression(expression)) {
    const values = expression.elements.map((element) => objectValue(element, constants, objects));
    return values.some((value) => value === undefined) ? undefined : values;
  }
  if (!isObjectLiteralExpression(expression)) return undefined;
  const result: JsonObject = {};
  for (const property of expression.properties) {
    if (!isPropertyAssignment(property)) return undefined;
    const name = propertyName(property.name, constants);
    const value = objectValue(property.initializer, constants, objects);
    if (name === undefined || value === undefined) return undefined;
    result[name] = value;
  }
  return result;
};

const classifyCdpMethod = (method: string): string | undefined => {
  if (ALLOWED_CDP.has(method)) return undefined;
  const domain = method.split(".", 1)[0] ?? "";
  if (domain === "Target") return "E_TARGET_DOMAIN_DENIED";
  if (domain === "Runtime") return "E_CDP_METHOD_DENIED";
  if (FORBIDDEN_CDP_DOMAINS.has(domain)) return "E_CDP_DOMAIN_DENIED";
  if (domain === "Page" || domain === "Network") return "E_CDP_METHOD_DENIED";
  return "E_CDP_METHOD_DENIED";
};

const moduleTarget = (sourcePath: string, specifier: string, root: string): string | undefined => {
  if (!specifier.startsWith(".")) return ALLOWED_BARE_IMPORTS.has(specifier) ? specifier : undefined;
  const candidate = resolve(dirname(sourcePath), specifier);
  const candidates = extname(candidate) === ".js"
    ? [`${candidate.slice(0, -3)}.ts`, candidate]
    : [candidate, `${candidate}.ts`, resolve(candidate, "index.ts")];
  return candidates.find((path) => {
    const pathRelative = relative(root, path);
    return pathRelative !== ""
      && !pathRelative.startsWith(`..${sep}`)
      && pathRelative !== ".."
      && !pathRelative.startsWith(sep)
      && existsSync(path)
      && statSync(path).isFile();
  });
};

const pathMatchesOwnerFile = (path: string, owner: string): boolean => {
  const [ownerPath] = owner.split("#", 1);
  if (ownerPath === undefined) return false;
  const sourceSuffix = ownerPath.startsWith("extension/")
    ? ownerPath.slice("extension/".length).split("/").join(sep)
    : ownerPath.split("/").join(sep);
  const compiledSuffix = sourceSuffix.endsWith(".ts")
    ? `${sourceSuffix.slice(0, -3)}.js`
    : sourceSuffix;
  const compiledDistSuffix = compiledSuffix.startsWith(`src${sep}`)
    ? `dist${sep}${compiledSuffix.slice(`src${sep}`.length)}`
    : compiledSuffix;
  return path.endsWith(sourceSuffix)
    || path.endsWith(compiledSuffix)
    || path.endsWith(compiledDistSuffix);
};

const ownerMatches = (node: Node, path: string, owner: string): boolean => {
  const [, symbol] = owner.split("#", 2);
  if (symbol === undefined || !pathMatchesOwnerFile(path, owner)) return false;
  let current = node.parent;
  while (current !== undefined) {
    if (isClassDeclaration(current) && current.name?.text === symbol) return true;
    if (isFunctionDeclaration(current) && current.name?.text === symbol) return true;
    if (isArrowFunction(current) || isFunctionExpression(current)) {
      if (isFunctionExpression(current) && current.name?.text === symbol) return true;
      const declaration = current.parent;
      if (isVariableDeclaration(declaration)
        && isIdentifier(declaration.name)
        && declaration.name.text === symbol) return true;
    }
    current = current.parent;
  }
  return false;
};

const callbackParameters = (expression: Expression): readonly string[] | undefined => {
  if (!isArrowFunction(expression) && !isFunctionExpression(expression)) return undefined;
  const names: string[] = [];
  for (const parameter of expression.parameters) {
    if (!isIdentifier(parameter.name)) return undefined;
    names.push(parameter.name.text);
  }
  return names;
};

const callbackReturnsValue = (expression: Expression): boolean => {
  if (!isArrowFunction(expression) && !isFunctionExpression(expression)) return true;
  if (expression.modifiers?.some((modifier) => modifier.kind === SyntaxKind.AsyncKeyword) === true) {
    return true;
  }
  if (expression.body.kind !== SyntaxKind.Block) return true;
  let returns = false;
  const inspect = (node: Node): void => {
    if (node !== expression.body
      && (isArrowFunction(node) || isFunctionExpression(node) || isFunctionDeclaration(node))) return;
    if (isReturnStatement(node) && node.expression !== undefined) returns = true;
    node.forEachChild(inspect);
  };
  inspect(expression.body);
  return returns;
};

const compactSource = (node: Node): string => node.getText().replace(/\s+/gu, "");

const callbackStartsWithGuard = (
  expression: Expression,
  exactCondition: string,
): boolean => {
  if ((!isArrowFunction(expression) && !isFunctionExpression(expression))
    || !isBlock(expression.body)) return false;
  const statement = expression.body.statements[0];
  if (statement === undefined || !isIfStatement(statement)) return false;
  const condition = compactSource(statement.expression);
  const guarded = statement.thenStatement;
  const guardedText = compactSource(guarded);
  return condition === exactCondition && (
    guarded.kind === SyntaxKind.ThrowStatement
    || guardedText === "{thrownewError('SAFETY_STOP');}"
    || guardedText === "{thrownewError(\"SAFETY_STOP\");}"
    || guardedText === "{return;}"
  );
};

const callbackHasExactLocationGuard = (
  expression: Expression,
  urlPath: readonly string[],
  offset: number,
): boolean => {
  if ((!isArrowFunction(expression) && !isFunctionExpression(expression))
    || !isBlock(expression.body)) return false;
  const declaration = expression.body.statements[offset];
  const guard = expression.body.statements[offset + 1];
  if (declaration === undefined || !isVariableStatement(declaration)
    || declaration.declarationList.declarations.length !== 1
    || guard === undefined || !isIfStatement(guard)) return false;
  const item = declaration.declarationList.declarations[0];
  if (item === undefined || !isIdentifier(item.name) || item.name.text !== "location"
    || item.initializer === undefined || !isNewExpression(item.initializer)
    || !isIdentifier(item.initializer.expression) || item.initializer.expression.text !== "URL"
    || item.initializer.arguments?.length !== 1
    || !pathEndsWith(
      expressionPath(item.initializer.arguments[0] as Expression, new Map()),
      urlPath,
    )) {
    return false;
  }
  return compactSource(guard.expression) === [
    "location.protocol!==\"https:\"",
    "location.hostname!==\"miseojeu.espacejeux.com\"",
    "location.pathname!==\"/\"",
    "location.username!==\"\"",
    "location.password!==\"\"",
    "location.search!==\"\"",
    "location.hash!==\"\"",
  ].join("||") && compactSource(guard.thenStatement).includes("thrownewError(");
};

const callbackHasExactStatement = (
  expression: Expression,
  index: number,
  expected: string,
): boolean => {
  if ((!isArrowFunction(expression) && !isFunctionExpression(expression))
    || !isBlock(expression.body)) return false;
  const statement = expression.body.statements[index];
  return statement !== undefined && compactSource(statement) === expected;
};

const callbackStatementCount = (expression: Expression): number =>
  (isArrowFunction(expression) || isFunctionExpression(expression)) && isBlock(expression.body)
    ? expression.body.statements.length
    : -1;

const hasExactStringSet = (
  sourceFile: SourceFile,
  name: string,
  expected: readonly string[],
): boolean => {
  let observed: string[] | undefined;
  let declarations = 0;
  const inspect = (node: Node): void => {
    if (isVariableDeclaration(node)
      && isIdentifier(node.name)
      && node.name.text === name) {
      declarations += 1;
      if (node.parent?.parent?.parent === sourceFile
        && node.initializer !== undefined
        && isNewExpression(node.initializer)
        && isIdentifier(node.initializer.expression)
        && node.initializer.expression.text === "Set"
        && node.initializer.arguments?.length === 1
        && node.initializer.arguments[0] !== undefined
        && isArrayLiteralExpression(node.initializer.arguments[0])) {
        const values = node.initializer.arguments[0].elements.map((element) =>
          isStringLiteral(element) ? element.text : undefined);
        if (values.every((value): value is string => value !== undefined)) observed = values;
      }
    }
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return declarations === 1 && equalJson(observed, expected);
};

const isAuthenticatedLoopbackOwner = (node: Node, path: string): boolean => ownerMatches(
  node,
  path,
  "extension/src/security/loopback.ts#AuthenticatedLoopback",
);

const exactAuthenticatedMessageCallback = (expression: Expression | undefined): boolean => {
  if (expression === undefined
    || (!isArrowFunction(expression) && !isFunctionExpression(expression))
    || !isBlock(expression.body)
    || !equalJson(callbackParameters(expression), ["event"])
    || expression.body.statements.length !== 1) return false;
  const first = expression.body.statements[0];
  return first !== undefined
    && compactSource(first) === "decodeAuthenticatedFact(event.data,pairingSecret,sessionId,"
      + "\"BACKEND_TO_CLIENT\",nextInboundCounter);";
};

const hasEnclosingParameter = (node: Node, name: string): boolean => {
  let current = node.parent;
  while (current !== undefined) {
    if (isFunctionDeclaration(current)
      || isFunctionExpression(current)
      || isArrowFunction(current)
      || isMethodDeclaration(current)) {
      return current.parameters.some(
        (parameter) => isIdentifier(parameter.name) && parameter.name.text === name,
      );
    }
    current = current.parent;
  }
  return false;
};

const hasEnclosingAuthorization = (node: Node, path: string): boolean => {
  let current = node.parent;
  while (current !== undefined) {
    if (isFunctionDeclaration(current)
      || isFunctionExpression(current)
      || isArrowFunction(current)
      || isMethodDeclaration(current)) {
      const parameter = current.parameters.find(
        (candidate) => isIdentifier(candidate.name) && candidate.name.text === "authorization",
      );
      if (parameter === undefined) return false;
      return path.endsWith(".js")
        || parameter.type?.getText() === "DiscoveryRunAuthorization";
    }
    current = current.parent;
  }
  return false;
};

const hasAuthorizationTabBinding = (
  node: Node,
  path: string,
  aliases: ReadonlyMap<string, readonly string[]>,
): boolean => hasEnclosingAuthorization(node, path)
  && pathEndsWith(aliases.get("selectedTabId"), ["authorization", "browser_binding", "tab_id"]);

const exactSelectedTarget = (
  call: Node,
  path: string,
  expression: Expression | undefined,
  constants: ReadonlyMap<string, string>,
  aliases: ReadonlyMap<string, readonly string[]>,
): boolean => {
  if (!hasEnclosingAuthorization(call, path)) return false;
  if (expression === undefined || !isObjectLiteralExpression(expression)) return false;
  if (expression.properties.length !== 1) return false;
  const property = expression.properties[0];
  return property !== undefined
    && isPropertyAssignment(property)
    && propertyName(property.name, constants) === "tabId"
    && pathEndsWith(
      resolveAlias(expressionPath(property.initializer, constants), aliases),
      ["authorization", "browser_binding", "tab_id"],
    );
};

const expressionIsEmptyArray = (expression: Expression | undefined): boolean =>
  expression !== undefined && isArrayLiteralExpression(expression) && expression.elements.length === 0;

const exactExecuteScriptDetails = (
  call: Node,
  path: string,
  expression: Expression | undefined,
  constants: ReadonlyMap<string, string>,
  aliases: ReadonlyMap<string, readonly string[]>,
): boolean => {
  if (!hasEnclosingAuthorization(call, path)) return false;
  if (expression === undefined || !isObjectLiteralExpression(expression)) return false;
  const properties = new Map<string, Expression>();
  for (const property of expression.properties) {
    if (!isPropertyAssignment(property)) return false;
    const name = propertyName(property.name, constants);
    if (name === undefined) return false;
    properties.set(name, property.initializer);
  }
  if (!equalJson([...properties.keys()].sort(), ["args", "func", "target", "world"])) return false;
  const target = properties.get("target");
  if (target === undefined || !isObjectLiteralExpression(target)) return false;
  const targetProperties = new Map<string, Expression>();
  for (const property of target.properties) {
    if (!isPropertyAssignment(property)) return false;
    const name = propertyName(property.name, constants);
    if (name === undefined) return false;
    targetProperties.set(name, property.initializer);
  }
  const tabId = targetProperties.get("tabId");
  const frameIds = targetProperties.get("frameIds");
  const func = properties.get("func");
  return equalJson([...targetProperties.keys()].sort(), ["frameIds", "tabId"])
    && tabId !== undefined
    && pathEndsWith(
      resolveAlias(expressionPath(tabId, constants), aliases),
      ["authorization", "browser_binding", "tab_id"],
    )
    && frameIds !== undefined
    && isArrayLiteralExpression(frameIds)
    && frameIds.elements.length === 1
    && frameIds.elements[0] !== undefined
    && isIdentifier(frameIds.elements[0])
    && ["ownedFrameId", "frameId"].includes(frameIds.elements[0].text)
    && hasEnclosingParameter(call, frameIds.elements[0].text)
    && constantString(properties.get("world") as Expression, constants) === "ISOLATED"
    && func !== undefined
    && isIdentifier(func)
    && ["APP_LOCATION_CONTEXT_V1", "DOM_DOCUMENT_LIFECYCLE_V1"].includes(func.text)
    && expressionIsEmptyArray(properties.get("args"));
};

const hasCanonicalProjectionImport = (sourceFile: SourceFile, path: string): boolean => {
  if (!/(?:^|[/\\])spool\.(?:ts|js)$/u.test(path)) return false;
  const expectedSpecifier = "./security/redaction.js";
  let imports = 0;
  let shadowed = false;
  const inspect = (node: Node): void => {
    if (isImportDeclaration(node)
      && node.moduleSpecifier !== undefined
      && isStringLiteral(node.moduleSpecifier)
      && node.moduleSpecifier.text === expectedSpecifier
      && node.importClause?.namedBindings !== undefined
      && compactSource(node).includes("{projectBeforePersistence}")) {
      imports += 1;
    }
    if ((isFunctionDeclaration(node) && node.name?.text === "projectBeforePersistence")
      || (isVariableDeclaration(node)
        && isIdentifier(node.name)
        && node.name.text === "projectBeforePersistence")
      || (isParameter(node)
        && isIdentifier(node.name)
        && node.name.text === "projectBeforePersistence")) {
      shadowed = true;
    }
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return imports === 1 && !shadowed;
};

const storageTypeFromExpression = (
  expression: Expression,
  storageTypes: ReadonlyMap<string, string>,
  constants: ReadonlyMap<string, string>,
): string | undefined => {
  if (isAsExpression(expression)) {
    const asserted = expression.type.getText().split("<", 1)[0];
    return asserted?.startsWith("IDB") === true
      ? asserted
      : storageTypeFromExpression(expression.expression, storageTypes, constants);
  }
  if (isParenthesizedExpression(expression)
    || isSatisfiesExpression(expression)
    || isNonNullExpression(expression)) {
    return storageTypeFromExpression(expression.expression, storageTypes, constants);
  }
  if (isIdentifier(expression)) return storageTypes.get(expression.text);
  if (isCallExpression(expression)) {
    const member = finalPathPart(expressionPath(expression.expression, constants));
    return new Map<string, string>([
      ["open", "IDBOpenDBRequest"],
      ["createObjectStore", "IDBObjectStore"],
      ["transaction", "IDBTransaction"],
      ["objectStore", "IDBObjectStore"],
      ["openCursor", "IDBRequest"],
      ["bound", "IDBKeyRange"],
    ]).get(member);
  }
  if (isPropertyAccessExpression(expression) && expression.name.text === "result") {
    const receiverType = storageTypeFromExpression(expression.expression, storageTypes, constants);
    if (receiverType === "IDBOpenDBRequest") return "IDBDatabase";
    if (receiverType === "IDBRequest") return "IDBCursor";
  }
  return undefined;
};

const isRawEvidenceIdentifier = (name: string): boolean =>
  /^(?:cdpEvent\w*|event\w*|raw(?:Bytes|CdpBytes|CdpEvent|Event|Observation|Payload)\w*)$/u.test(name);

const containsTaintedIdentifier = (node: Node, tainted: ReadonlySet<string>): boolean => {
  if (isIdentifier(node)
    && (tainted.has(node.text) || isRawEvidenceIdentifier(node.text))) {
    return true;
  }
  let found = false;
  node.forEachChild((child) => {
    if (!found && containsTaintedIdentifier(child, tainted)) found = true;
  });
  return found;
};

const isAssignment = (node: Node): node is BinaryExpression => isBinaryExpression(node)
  && ["=", "+=", "-=", "*=", "/=", "%=", "&&=", "||=", "??="].includes(
    node.operatorToken.getText(),
  );

const containsForbiddenFactShape = (
  node: Node,
  constants: ReadonlyMap<string, string>,
): boolean => {
  if (isObjectLiteralExpression(node)) {
    for (const property of node.properties) {
      if (!isPropertyAssignment(property)) return true;
      const name = propertyName(property.name, constants);
      if (name === undefined || ["action", "cdp_method", "command"].includes(name)) return true;
      if (containsForbiddenFactShape(property.initializer, constants)) return true;
    }
  }
  let forbidden = false;
  node.forEachChild((child) => {
    if (!forbidden && containsForbiddenFactShape(child, constants)) forbidden = true;
  });
  return forbidden;
};

const hasExactFixedProbeDefinition = (sourceFile: SourceFile, name: string): boolean => {
  const expected = new Map([
    [
      "APP_LOCATION_CONTEXT_V1",
      "()=>({origin_id:\"MOJ_ESPACEJEUX\",path_template_id:\"ROOT\"})",
    ],
    [
      "DOM_DOCUMENT_LIFECYCLE_V1",
      "()=>({ready_state:document.readyState,visibility_state:document.visibilityState,"
        + "has_focus:document.hasFocus(),document_context:\"CURRENT_OWNED_DOCUMENT\"})",
    ],
  ]).get(name);
  if (expected === undefined) return false;
  let declarations = 0;
  let exactFound = false;
  const inspect = (node: Node): void => {
    if (isVariableDeclaration(node)
      && isIdentifier(node.name)
      && node.name.text === name) {
      declarations += 1;
      if (node.parent?.parent?.parent === sourceFile
        && node.initializer !== undefined
        && compactSource(node.initializer) === expected) exactFound = true;
    }
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return declarations === 1 && exactFound;
};

const hasExactProbeResultValidator = (sourceFile: SourceFile): boolean => {
  const expected = "(results,ownedFrameId,ownedDocumentId,probeId)=>{"
    + "if(results.length!==1||results[0].frameId!==ownedFrameId"
    + "||results[0].documentId!==ownedDocumentId){thrownewError(\"SAFETY_STOP\");}"
    + "constresult=results[0].result;"
    + "constexactApp=probeId===\"APP_LOCATION_CONTEXT_V1\""
    + "&&result?.origin_id===\"MOJ_ESPACEJEUX\"&&result?.path_template_id===\"ROOT\""
    + "&&Object.keys(result).sort().join(\",\")===\"origin_id,path_template_id\";"
    + "constexactDom=probeId===\"DOM_DOCUMENT_LIFECYCLE_V1\""
    + "&&result?.ready_state!==undefined"
    + "&&[\"loading\",\"interactive\",\"complete\"].includes(result.ready_state)"
    + "&&result?.visibility_state!==undefined"
    + "&&[\"hidden\",\"visible\"].includes(result.visibility_state)"
    + "&&typeofresult?.has_focus===\"boolean\""
    + "&&result?.document_context===\"CURRENT_OWNED_DOCUMENT\""
    + "&&Object.keys(result).sort().join(\",\")"
    + "===\"document_context,has_focus,ready_state,visibility_state\";"
    + "if(!(exactApp||exactDom)){thrownewError(\"SAFETY_STOP\");}}";
  let declarations = 0;
  let exactFound = false;
  const inspect = (node: Node): void => {
    if (isVariableDeclaration(node)
      && isIdentifier(node.name)
      && node.name.text === "validateFixedProbeResult") {
      declarations += 1;
      if (node.parent?.parent?.parent === sourceFile
        && node.initializer !== undefined
        && compactSource(node.initializer) === expected) exactFound = true;
    }
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return declarations === 1 && exactFound;
};

const exactExecuteScriptResultBinding = (
  call: Node,
  sourceFile: SourceFile,
  functionName: string,
): boolean => {
  let initializer = call;
  if (initializer.parent?.kind === SyntaxKind.AwaitExpression) initializer = initializer.parent;
  const declaration = initializer.parent;
  if (declaration === undefined
    || !isVariableDeclaration(declaration)
    || declaration.initializer !== initializer
    || !isIdentifier(declaration.name)) return false;
  const statement = declaration.parent?.parent;
  const block = statement?.parent;
  if (statement === undefined || !isVariableStatement(statement) || block === undefined || !isBlock(block)) {
    return false;
  }
  const index = block.statements.findIndex((candidate) => candidate === statement);
  const next = index >= 0 ? block.statements[index + 1] : undefined;
  return next !== undefined
    && compactSource(next) === `validateFixedProbeResult(${declaration.name.text},ownedFrameId,ownedDocumentId,"${functionName}");`
    && hasExactProbeResultValidator(sourceFile);
};

const isWithinStorageHandler = (
  node: Node,
  handler: string,
  constants: ReadonlyMap<string, string>,
): boolean => {
  let current = node.parent;
  while (current !== undefined) {
    if ((isArrowFunction(current) || isFunctionExpression(current))
      && current.parent !== undefined
      && isBinaryExpression(current.parent)
      && current.parent.operatorToken.kind === SyntaxKind.EqualsToken
      && finalPathPart(expressionPath(current.parent.left, constants)) === handler) return true;
    current = current.parent;
  }
  return false;
};

const isWithinSpoolAppendFlow = (node: Node): boolean => {
  let current = node.parent;
  while (current !== undefined) {
    if (isMethodDeclaration(current)) {
      return propertyName(current.name, new Map()) === "append";
    }
    if (isFunctionDeclaration(current)) return false;
    if (isArrowFunction(current) || isFunctionExpression(current)) {
      const assignment = current.parent;
      if (assignment === undefined
        || !isBinaryExpression(assignment)
        || !STORAGE_HANDLER_NAMES.has(
          finalPathPart(expressionPath(assignment.left, new Map())),
        )) return false;
    }
    if (isIfStatement(current)
      && current.expression.kind === SyntaxKind.FalseKeyword) return false;
    current = current.parent;
  }
  return false;
};

const hasExactDatabaseBinding = (sourceFile: SourceFile): boolean => {
  let databaseBinding = false;
  let uuidGuard = false;
  const inspect = (node: Node): void => {
    if (isVariableDeclaration(node)
      && isIdentifier(node.name)
      && node.name.text === "databaseName"
      && node.initializer !== undefined
      && isWithinSpoolAppendFlow(node)
      && isBinaryExpression(node.initializer)
      && node.initializer.operatorToken.kind === SyntaxKind.PlusToken
      && constantString(node.initializer.left, new Map()) === "hybrid-discovery-v6.2-working-"
      && pathEndsWith(
        expressionPath(node.initializer.right, new Map()),
        ["authorization", "browser_binding", "browser_run_id"],
      )) databaseBinding = true;
    if (isIfStatement(node)
      && isWithinSpoolAppendFlow(node)
      && compactSource(node.expression)
        === "!LOWERCASE_UUID_V4.test(authorization.browser_binding.browser_run_id)"
      && compactSource(node.thenStatement).includes("thrownewError(")) uuidGuard = true;
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return databaseBinding && uuidGuard;
};

const hasExactSpoolAppendContract = (sourceFile: SourceFile, path: string): boolean => {
  let methods = 0;
  let valid = false;
  const inspect = (node: Node): void => {
    if (isMethodDeclaration(node) && propertyName(node.name, new Map()) === "append") {
      methods += 1;
      const parameter = node.parameters[0];
      const sourceSignature = path.endsWith(".ts")
        ? parameter?.type?.getText() === "PersistableSanitizedObservationV1"
          && node.type?.getText() === "Promise<SpoolRecord>"
        : true;
      const statements = node.body?.statements ?? [];
      const pending = statements.some((statement) =>
        isVariableStatement(statement)
        && statement.declarationList.declarations.some((declaration) =>
          isIdentifier(declaration.name)
          && declaration.name.text === "durableCompletion"
          && declaration.initializer !== undefined
          && compactSource(declaration.initializer) === "createPendingDurabilityPromise()"));
      const returnStatements: Node[] = [];
      const findReturns = (candidate: Node): void => {
        if (candidate !== node
          && (isArrowFunction(candidate)
            || isFunctionExpression(candidate)
            || isFunctionDeclaration(candidate))) return;
        if (isReturnStatement(candidate)) returnStatements.push(candidate);
        candidate.forEachChild(findReturns);
      };
      findReturns(node);
      valid = node.parameters.length === 1
        && parameter !== undefined
        && isIdentifier(parameter.name)
        && parameter.name.text === "value"
        && sourceSignature
        && pending
        && returnStatements.length === 1
        && compactSource(returnStatements[0] as Node) === "returndurableCompletion.promise;";
    }
    node.forEachChild(inspect);
  };
  inspect(sourceFile);
  return methods === 1 && valid;
};

const scanSourceFile = (
  sourceFile: SourceFile,
  path: string,
  root: string,
  policy: CapabilityPolicy,
): string[] => {
  const errors: string[] = [];
  const constants = new Map<string, string>();
  const aliases = new Map<string, readonly string[]>();
  const callbacks = new Map<string, Expression>();
  const objects = new Map<string, unknown>();
  const storageTypes = new Map<string, string>();
  const domTypes = new Set<string>();
  const tainted = new Set<string>();
  const childTargets = new Set<string>();
  const storageCallOrder: string[] = [];
  let storageUsed = false;
  const add = (error: string): void => { errors.push(error); };

  const visit = (node: Node): void => {
    const ownerName = /(?:^|[/\\])(cdp-broker|loopback|run-controller|target-policy)\.(?:ts|js)$/u
      .exec(path)?.[1];
    const localName = (isFunctionDeclaration(node) || isVariableDeclaration(node))
      && node.name !== undefined && isIdentifier(node.name)
      ? node.name.text
      : undefined;
    if (ownerName !== undefined && localName !== undefined
      && OWNER_IMPORTED_HELPERS.get(ownerName)?.has(localName) === true) {
      add("E_PRIVILEGED_HELPER_PROVENANCE");
    }
    if (isParameter(node) && isIdentifier(node.name) && node.type !== undefined) {
      const declaredType = node.type.getText().split("<", 1)[0];
      if (declaredType?.startsWith("IDB") === true) {
        storageTypes.set(node.name.text, declaredType);
      }
      if (/^(?:Document|Element|HTMLElement|HTML\w+Element|Node|Range|Selection)$/u
        .test(declaredType ?? "")) domTypes.add(node.name.text);
    }
    if (isPropertyAccessExpression(node) || isElementAccessExpression(node)) {
      const reference = normalizeChromeRoot(
        resolveAlias(expressionPath(node, constants), aliases),
      );
      const isIntermediate = node.parent !== undefined
        && (isPropertyAccessExpression(node.parent) || isElementAccessExpression(node.parent))
        && node.parent.expression === node;
      if (reference?.[0] === "chrome" && reference.length >= 2 && !isIntermediate) {
        const member = reference.join(".");
        const allowedOwner = policy.chromeOwners.get(member);
        const directCall = node.parent !== undefined
          && isCallExpression(node.parent)
          && node.parent.expression === node;
        if (reference.length === 2) {
          add(reference[1] === "debugger" ? "E_PRIVILEGED_API_ALIAS" : "E_CHROME_API_NOT_ALLOWLISTED");
        } else if (allowedOwner === undefined) {
          const sealedDebuggerMembers = new Set([
            "chrome.debugger.attach",
            "chrome.debugger.detach",
            "chrome.debugger.onDetach.addListener",
            "chrome.debugger.onEvent.addListener",
            "chrome.debugger.sendCommand",
          ]);
          add(
            reference[1] === "debugger" && sealedDebuggerMembers.has(member)
              ? "E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"
              : "E_CHROME_API_NOT_ALLOWLISTED",
          );
        } else if (!directCall || !ownerMatches(node, path, allowedOwner)) {
          add(
            reference[1] === "debugger"
              ? "E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"
              : member === "chrome.runtime.onMessage.addListener"
                ? "E_UNTRUSTED_COMMAND_CHANNEL"
                : "E_CHROME_API_NOT_ALLOWLISTED",
          );
        }
      }
      if (reference === undefined && hasChromeRoot(node.expression, constants)) {
        add("E_CHROME_API_NOT_ALLOWLISTED");
      }
      if (isElementAccessExpression(node)
        && constantString(node.argumentExpression, constants) === undefined
        && hasGlobalRoot(node.expression)) add("E_CHROME_API_NOT_ALLOWLISTED");
      if (
        isPropertyAccessExpression(node)
        && ["createWritable", "getFileHandle"].includes(node.name.text)
      ) {
        add("E_PERSISTENCE_BEFORE_PROJECTION");
      }
      const referencedMember = isPropertyAccessExpression(node)
        ? node.name.text
        : constantString(node.argumentExpression, constants);
      const referencedReceiver = expressionPath(node.expression, constants)?.at(-1) ?? "";
      const directInvocation = node.parent !== undefined
        && isCallExpression(node.parent)
        && node.parent.expression === node;
      if (!directInvocation
        && referencedMember !== undefined
        && DOM_MUTATION_NAMES.has(referencedMember)
        && storageTypes.get(referencedReceiver) === undefined) add("E_FIXED_PROBE_SHAPE");
      if (isElementAccessExpression(node)
        && referencedMember === undefined
        && (/^(?:document|element|node|range|selection|style)$/iu.test(referencedReceiver)
          || domTypes.has(referencedReceiver))) add("E_FIXED_PROBE_SHAPE");
    }

    if (isImportDeclaration(node) || isExportDeclaration(node)) {
      const specifierNode = node.moduleSpecifier;
      if (specifierNode !== undefined) {
        if (!isStringLiteral(specifierNode) || moduleTarget(path, specifierNode.text, root) === undefined) {
          add("E_REMOTE_OR_SPLIT_CODE");
        }
      }
    }

    if (isVariableDeclaration(node)) {
      if (isIdentifier(node.name) && node.initializer !== undefined) {
        if (isArrowFunction(node.initializer) || isFunctionExpression(node.initializer)) {
          callbacks.set(node.name.text, node.initializer);
        }
        const declaredType = (node as typeof node & { type?: Node }).type?.getText().split("<", 1)[0]
          ?? storageTypeFromExpression(node.initializer, storageTypes, constants);
        if (declaredType?.startsWith("IDB") === true) {
          storageTypes.set(node.name.text, declaredType);
        } else if (isIdentifier(node.initializer)) {
          const aliasedType = storageTypes.get(node.initializer.text);
          if (aliasedType !== undefined) storageTypes.set(node.name.text, aliasedType);
        }
        if (/^(?:Document|Element|HTMLElement|HTML\w+Element|Node|Range|Selection)$/u
          .test(declaredType ?? "")) domTypes.add(node.name.text);
        if (isIdentifier(node.initializer) && domTypes.has(node.initializer.text)) {
          domTypes.add(node.name.text);
        }
        if (isCallExpression(node.initializer)
          && pathEndsWith(expressionPath(node.initializer.expression, constants), ["document", "createElement"])) {
          domTypes.add(node.name.text);
        }
        if (isNewExpression(node.initializer)
          && pathEndsWith(expressionPath(node.initializer.expression, constants), ["Image"])) {
          domTypes.add(node.name.text);
        }
        const isCanonicalProjection = isCallExpression(node.initializer)
          && pathEndsWith(
            expressionPath(node.initializer.expression, constants),
            ["projectBeforePersistence"],
          )
          && hasCanonicalProjectionImport(sourceFile, path);
        if (!isCanonicalProjection && containsTaintedIdentifier(node.initializer, tainted)) {
          tainted.add(node.name.text);
        }
        const value = constantString(node.initializer, constants);
        if (value !== undefined) constants.set(node.name.text, value);
        const structuredValue = objectValue(node.initializer, constants, objects);
        if (structuredValue !== undefined) objects.set(node.name.text, structuredValue);
        const alias = resolveAlias(expressionPath(node.initializer, constants), aliases);
        if (alias !== undefined) {
          aliases.set(node.name.text, alias);
          if (pathEndsWith(alias, ["chrome", "debugger", "sendCommand"])) {
            add("E_PRIVILEGED_API_ALIAS");
          }
        }
        if (
          isObjectLiteralExpression(node.initializer)
          && node.initializer.properties.some(
            (property) => (isPropertyAssignment(property) || isShorthandPropertyAssignment(property))
              && ["sessionId", "targetId"].includes(propertyName(property.name, constants) ?? ""),
          )
        ) {
          childTargets.add(node.name.text);
        }
      } else if (isObjectBindingPattern(node.name) && node.initializer !== undefined) {
        const owner = resolveAlias(expressionPath(node.initializer, constants), aliases);
        for (const element of node.name.elements) {
          const name = element.propertyName === undefined
            ? element.name === undefined ? undefined : propertyName(element.name, constants)
            : propertyName(element.propertyName, constants);
          if (name === "sendCommand" && pathEndsWith(owner, ["chrome", "debugger"])) {
            add("E_PRIVILEGED_API_ALIAS");
          }
          if (
            element.name !== undefined
            && isIdentifier(element.name)
            && name !== undefined
            && owner !== undefined
          ) {
            aliases.set(element.name.text, [...owner, name]);
          }
        }
      }
      const functionValue = node.initializer;
      if (
        isIdentifier(node.name)
        && functionValue !== undefined
        && (isArrowFunction(functionValue) || isFunctionExpression(functionValue))
        && /(?:send|dispatch).*(?:cdp|command)|cdp.*(?:send|dispatch)/iu.test(node.name.text)
        && functionValue.parameters.some(
          (parameter) => isIdentifier(parameter.name) && /^(?:method|command|params)$/u.test(parameter.name.text),
        )
      ) {
        add("E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER");
      }
    }

    if (
      isFunctionDeclaration(node)
      && node.name !== undefined
      && /(?:send|dispatch).*(?:cdp|command)|cdp.*(?:send|dispatch)/iu.test(node.name.text)
      && node.parameters.some(
        (parameter) => isIdentifier(parameter.name) && /^(?:method|command|params)$/u.test(parameter.name.text),
      )
    ) {
      add("E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER");
    }

    if (isCallExpression(node)) {
      if (node.expression.kind === SyntaxKind.ImportKeyword) {
        add("E_DYNAMIC_MODULE_LOADING");
      } else {
        const directPath = expressionPath(node.expression, constants);
        let callPath = normalizeChromeRoot(resolveAlias(directPath, aliases));
        const indirect = pathEndsWith(callPath, ["call"])
          || pathEndsWith(callPath, ["apply"])
          || pathEndsWith(callPath, ["bind"]);
        if (indirect) callPath = callPath?.slice(0, -1);
        const callMember = callPath?.join(".");
        const allowedChromeOwner = callMember === undefined
          ? undefined
          : policy.chromeOwners.get(callMember);
        const inAllowedChromeOwner = allowedChromeOwner !== undefined
          && ownerMatches(node, path, allowedChromeOwner);

        if (inAllowedChromeOwner) {
          if (callMember === "chrome.debugger.attach") {
            if (!exactSelectedTarget(node, path, node.arguments[0], constants, aliases)) {
              add("E_SELECTED_TARGET_BINDING");
            }
            if (node.arguments.length !== 2
              || node.arguments[1] === undefined
              || constantString(node.arguments[1], constants) !== "1.3") {
              add("E_DEBUGGER_PROTOCOL_VERSION");
            }
          } else if (callMember === "chrome.debugger.detach") {
            if (node.arguments.length !== 1
              || !exactSelectedTarget(node, path, node.arguments[0], constants, aliases)) {
              add("E_SELECTED_TARGET_BINDING");
            }
          } else if (callMember === "chrome.webNavigation.getAllFrames") {
            if (node.arguments.length !== 1
              || !exactSelectedTarget(node, path, node.arguments[0], constants, aliases)) {
              add("E_CHROME_API_PARAMETER_MISMATCH");
            }
          } else if (callMember === "chrome.scripting.executeScript") {
            if (node.arguments.length !== 1
              || !exactExecuteScriptDetails(node, path, node.arguments[0], constants, aliases)) {
              add("E_FIXED_PROBE_SHAPE");
            } else {
              const details = node.arguments[0];
              const funcProperty = details !== undefined && isObjectLiteralExpression(details)
                ? details.properties.find((property) =>
                  isPropertyAssignment(property)
                  && propertyName(property.name, constants) === "func")
                : undefined;
              const functionName = funcProperty !== undefined
                && isPropertyAssignment(funcProperty)
                && isIdentifier(funcProperty.initializer)
                ? funcProperty.initializer.text
                : undefined;
              if (functionName === undefined
                || !hasExactFixedProbeDefinition(sourceFile, functionName)
                || !exactExecuteScriptResultBinding(node, sourceFile, functionName)) {
                add("E_FIXED_PROBE_SHAPE");
              }
            }
          } else if (callMember?.endsWith(".addListener") === true) {
            const callbackArgument = node.arguments[0];
            const callback = callbackArgument !== undefined && isIdentifier(callbackArgument)
              ? callbacks.get(callbackArgument.text)
              : callbackArgument;
            const parameters = callback === undefined ? undefined : callbackParameters(callback);
            if (!hasAuthorizationTabBinding(node, path, aliases)) add("E_SELECTED_TARGET_BINDING");
            if (callMember === "chrome.action.onClicked.addListener") {
              if (node.arguments.length !== 1
                || !equalJson(parameters, ["tab"])
                || callbackReturnsValue(callback as Expression)) {
                add("E_CHROME_API_SIGNATURE_MISMATCH");
              }
              if (callback === undefined || !callbackStartsWithGuard(
                callback,
                "tab.id!==selectedTabId||tab.url===undefined",
              )) add("E_SELECTED_TARGET_BINDING");
              if (callback === undefined
                || callbackStatementCount(callback) !== 3
                || !callbackHasExactLocationGuard(callback, ["tab", "url"], 1)) {
                add("E_CHROME_API_PARAMETER_MISMATCH");
              }
            } else if (callMember === "chrome.runtime.onMessage.addListener") {
              if (node.arguments.length !== 1
                || !equalJson(parameters, ["message", "sender", "sendResponse"])
                || callbackReturnsValue(callback as Expression)) {
                add("E_CHROME_API_SIGNATURE_MISMATCH");
              }
              if (callback === undefined || !callbackStartsWithGuard(
                callback,
                "sender.id!==\"anfddcancelbmpogbmckmjckjlnpmpjk\""
                + "||sender.origin!==\"chrome-extension://anfddcancelbmpogbmckmjckjlnpmpjk\""
                + "||sender.tab!==undefined",
              )) {
                add("E_UNTRUSTED_COMMAND_CHANNEL");
              }
              if (callback === undefined
                || !hasExactStringSet(sourceFile, "PUBLIC_MESSAGE_TYPES", PUBLIC_MESSAGE_TYPES)
                || callbackStatementCount(callback) !== 3
                || !callbackHasExactStatement(
                  callback,
                  1,
                  "if(typeofmessage!==\"object\"||message===null"
                    + "||!PUBLIC_MESSAGE_TYPES.has(message.message_type)"
                    + "||Object.keys(message).length!==1){return;}",
                )
                || !callbackHasExactStatement(
                  callback,
                  2,
                  "sendResponse(handlePublicMessage(message));",
                )) {
                add("E_UNTRUSTED_COMMAND_CHANNEL");
              }
            } else if (callMember === "chrome.debugger.onEvent.addListener") {
              if (node.arguments.length !== 1
                || !equalJson(parameters, ["source", "method", "params"])
                || callbackReturnsValue(callback as Expression)) {
                add("E_CHROME_API_SIGNATURE_MISMATCH");
              }
              if (callback === undefined || !callbackStartsWithGuard(
                callback,
                "source.tabId!==selectedTabId||source.sessionId!==undefined"
                + "||source.targetId!==undefined||source.extensionId!==undefined"
                + "||Object.keys(source).length!==1",
              )) add("E_CHILD_SESSION_DENIED");
              if (callback === undefined
                || !hasExactStringSet(sourceFile, "ALLOWED_NETWORK_EVENTS", ALLOWED_NETWORK_EVENTS)
                || callbackStatementCount(callback) !== 3
                || !callbackHasExactStatement(
                  callback,
                  1,
                  "if(!ALLOWED_NETWORK_EVENTS.has(method)){thrownewError(\"SAFETY_STOP\");}",
                )
                || !callbackHasExactStatement(
                  callback,
                  2,
                  "projectCdpEvent(method,params);",
                )) add("E_CHROME_API_PARAMETER_MISMATCH");
            } else if (callMember === "chrome.debugger.onDetach.addListener") {
              if (node.arguments.length !== 1
                || !equalJson(parameters, ["source", "reason"])
                || callbackReturnsValue(callback as Expression)) {
                add("E_CHROME_API_SIGNATURE_MISMATCH");
              }
              if (callback === undefined || !callbackStartsWithGuard(
                callback,
                "source.tabId!==selectedTabId||source.sessionId!==undefined"
                + "||source.targetId!==undefined||source.extensionId!==undefined"
                + "||Object.keys(source).length!==1"
                + "||(reason!==\"target_closed\"&&reason!==\"canceled_by_user\")",
              )) add("E_SELECTED_TARGET_BINDING");
              if (callback === undefined
                || callbackStatementCount(callback) !== 2
                || !callbackHasExactStatement(callback, 1, "safetyStopAndSealRun();")) {
                add("E_CHROME_API_PARAMETER_MISMATCH");
              }
            } else {
              if (!equalJson(parameters, ["details"]) || callbackReturnsValue(callback as Expression)) {
                add("E_CHROME_API_SIGNATURE_MISMATCH");
              }
              const isTabReplaced = callMember
                === "chrome.webNavigation.onTabReplaced.addListener";
              if (isTabReplaced) {
                if (node.arguments.length !== 1
                  || callback === undefined
                  || callbackStatementCount(callback) !== 2
                  || !callbackStartsWithGuard(callback, "details.replacedTabId!==selectedTabId")
                  || !callbackHasExactStatement(callback, 1, "safetyStopAndSealRun();")) {
                  add("E_CHROME_API_PARAMETER_MISMATCH");
                }
              } else {
                const expectedFilter = {
                  url: [{ hostEquals: "miseojeu.espacejeux.com", pathEquals: "/" }],
                };
                if (node.arguments.length !== 2
                  || node.arguments[1] === undefined
                  || !equalJson(objectValue(node.arguments[1], constants, objects), expectedFilter)
                  || callback === undefined
                  || callbackStatementCount(callback) !== 4
                  || !callbackStartsWithGuard(
                    callback,
                    "details.tabId!==selectedTabId||details.frameId!==ownedFrameId",
                  )
                  || !callbackHasExactLocationGuard(callback, ["details", "url"], 1)
                  || !callbackHasExactStatement(
                    callback,
                    3,
                    "projectNavigationEvent(details);",
                  )) {
                  add("E_CHROME_API_PARAMETER_MISMATCH");
                }
              }
            }
          }
        }
        if (!inAllowedChromeOwner && callMember === "chrome.debugger.attach") {
          if (!exactSelectedTarget(node, path, node.arguments[0], constants, aliases)) {
            add("E_SELECTED_TARGET_BINDING");
          }
          if (node.arguments.length !== 2
            || node.arguments[1] === undefined
            || constantString(node.arguments[1], constants) !== "1.3") {
            add("E_DEBUGGER_PROTOCOL_VERSION");
          }
        }
        if (!inAllowedChromeOwner && callMember === "chrome.debugger.detach"
          && (node.arguments.length !== 1
            || !exactSelectedTarget(node, path, node.arguments[0], constants, aliases))) {
          add("E_SELECTED_TARGET_BINDING");
        }

        const callFinal = finalPathPart(callPath)
          || (isPropertyAccessExpression(node.expression) ? node.expression.name.text : "");
        const storageOwner = ownerMatches(node, path, policy.storageOwner)
          && isWithinSpoolAppendFlow(node);
        const storageReceiver = directPath?.at(-2) ?? callPath?.at(-2) ?? "";
        const storageReceiverType = storageTypes.get(storageReceiver);
        const storageLikeReceiver = /(?:cursor|database|db|indexedDB|keyRange|request|store|transaction|tx)/iu
          .test(storageReceiver);
        const canonicalStorageMember = storageReceiver === "IDBKeyRange"
          && policy.storageMethods.has(`IDBKeyRange.${callFinal}`)
          ? `IDBKeyRange.${callFinal}`
          : storageReceiverType !== undefined
            && policy.storageMethods.has(`${storageReceiverType}.${callFinal}`)
            ? `${storageReceiverType}.${callFinal}`
            : undefined;
        if (callMember === "indexedDB.open" || storageReceiverType?.startsWith("IDB") === true) {
          storageUsed = true;
          if (storageOwner && canonicalStorageMember !== undefined) {
            storageCallOrder.push(canonicalStorageMember);
          }
        }
        if (DESTRUCTIVE_STORAGE_NAMES.has(callFinal)) {
          add("E_CUSTODY_PATH_DENIED");
        } else if (UNLISTED_STORAGE_METHOD_NAMES.has(callFinal)
          || (callPath?.[0] === "indexedDB" && callFinal !== "open")) {
          add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
        } else if (storageReceiverType?.startsWith("IDB") === true
          && canonicalStorageMember === undefined) {
          add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
        } else if (callMember === "indexedDB.open") {
          if (!storageOwner) {
            add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
          } else if (
            node.arguments.length !== 2
            || node.arguments[0] === undefined
            || !isIdentifier(node.arguments[0])
            || node.arguments[0].text !== "databaseName"
            || node.arguments[1]?.getText() !== "1"
          ) {
            add("E_PERSISTENCE_CONTRACT_MISMATCH");
          }
        } else if (STORAGE_METHOD_NAMES.has(callFinal)
          && (storageOwner || storageLikeReceiver || storageReceiverType !== undefined)) {
          if (!storageOwner || canonicalStorageMember === undefined) {
            add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
          } else {
            const first = node.arguments[0];
            const second = node.arguments[1];
            const third = node.arguments[2];
            let validStorageShape = true;
            if (callFinal === "createObjectStore") {
              validStorageShape = node.arguments.length === 2
                && isWithinStorageHandler(node, "onupgradeneeded", constants)
                && first !== undefined
                && ["stream_state_v1", "spool_entries_v1"]
                  .includes(constantString(first, constants) ?? "")
                && second !== undefined
                && equalJson(objectValue(second, constants, objects), { autoIncrement: false });
            } else if (callFinal === "createIndex") {
              const index = first === undefined ? undefined : constantString(first, constants);
              validStorageShape = node.arguments.length === 3
                && isWithinStorageHandler(node, "onupgradeneeded", constants)
                && ["by_spool_record_id", "by_raw_observation_id"].includes(index ?? "")
                && second !== undefined
                && constantString(second, constants)
                  === (index === "by_spool_record_id"
                    ? "spool_record.spool_record_id"
                    : "spool_record.raw_observation_id")
                && third !== undefined
                && equalJson(objectValue(third, constants, objects), { multiEntry: false, unique: true });
            } else if (callFinal === "transaction") {
              const argumentsValue = node.arguments.map(
                (argument) => objectValue(argument, constants, objects),
              );
              validStorageShape = equalJson(argumentsValue, [
                ["stream_state_v1", "spool_entries_v1"],
                "readwrite",
                { durability: "strict" },
              ]) || equalJson(argumentsValue, [
                ["stream_state_v1", "spool_entries_v1"],
                "readonly",
              ]);
            } else if (callFinal === "objectStore") {
              validStorageShape = node.arguments.length === 1
                && first !== undefined
                && ["stream_state_v1", "spool_entries_v1"]
                  .includes(constantString(first, constants) ?? "");
            } else if (callFinal === "add") {
              validStorageShape = node.arguments.length === 2
                && first?.getText() === "entry"
                && second?.getText() === "positionKey";
            } else if (callFinal === "put") {
              validStorageShape = node.arguments.length === 2
                && first?.getText() === "state"
                && second?.getText() === "streamKey";
            } else if (callFinal === "get") {
              validStorageShape = node.arguments.length === 1;
            } else if (callFinal === "openCursor") {
              validStorageShape = node.arguments.length === 2
                && second !== undefined
                && constantString(second, constants) === "next";
            } else if (callFinal === "bound") {
              validStorageShape = node.arguments.length === 4
                && objectValue(node.arguments[2] as Expression, constants, objects) === false
                && objectValue(node.arguments[3] as Expression, constants, objects) === false;
            } else if (["continue", "abort", "close"].includes(callFinal)) {
              validStorageShape = node.arguments.length === 0;
            }
            if (!validStorageShape) {
              add("E_PERSISTENCE_CONTRACT_MISMATCH");
            }
          }
        }
        if ((callMember === "indexedDB.open" || storageReceiverType?.startsWith("IDB") === true)
          && node.arguments.some((argument) => containsTaintedIdentifier(argument, tainted))) {
          add("E_PERSISTENCE_BEFORE_PROJECTION");
        }
        if (callFinal === "append") {
          const value = node.arguments[0];
          const projected = value !== undefined
            && isCallExpression(value)
            && pathEndsWith(expressionPath(value.expression, constants), ["projectBeforePersistence"])
            && value.arguments.length === 1
            && hasCanonicalProjectionImport(sourceFile, path);
          if (node.arguments.length !== 1 || !projected) {
            add("E_PERSISTENCE_BEFORE_PROJECTION");
          }
        }

        if (pathEndsWith(directPath, ["Reflect", "apply"])) {
          const sink = node.arguments[0] === undefined
            ? undefined
            : resolveAlias(expressionPath(node.arguments[0], constants), aliases);
          if (pathEndsWith(sink, ["chrome", "debugger", "sendCommand"])) {
            add("E_INDIRECT_PRIVILEGED_CALL");
          }
          const sinkFinal = finalPathPart(sink);
          if (DOM_MUTATION_NAMES.has(sinkFinal)) add("E_FIXED_PROBE_SHAPE");
          if (sinkFinal === "postMessage") add("E_PAGE_COMMAND_CHANNEL");
          if (sinkFinal === "send") add("E_LOOPBACK_FACT_UNION");
        }
        if (pathEndsWith(directPath, ["Reflect", "get"])) {
          const owner = node.arguments[0] === undefined
            ? undefined
            : resolveAlias(expressionPath(node.arguments[0], constants), aliases);
          const member = node.arguments[1] === undefined
            ? undefined
            : constantString(node.arguments[1], constants);
          if (pathEndsWith(owner, ["chrome", "debugger"]) && member === "sendCommand") {
            add("E_PRIVILEGED_API_ALIAS");
          }
          if (["chrome", "eval", "Function", "require", "fetch", "WebSocket"].includes(member ?? "")
            && (pathEndsWith(owner, ["globalThis"]) || pathEndsWith(owner, ["self"]))) {
            add(member === "chrome" ? "E_CHROME_API_NOT_ALLOWLISTED" : "E_DYNAMIC_CODE");
          }
          if (member === undefined
            && (pathEndsWith(owner, ["globalThis"])
              || pathEndsWith(owner, ["self"])
              || pathEndsWith(owner, ["window"]))) add("E_CHROME_API_NOT_ALLOWLISTED");
        }
        if (pathEndsWith(directPath, ["Object", "getOwnPropertyDescriptor"])
          && node.arguments[0] !== undefined
          && hasGlobalRoot(node.arguments[0])
          && (node.arguments[1] === undefined
            || constantString(node.arguments[1], constants) === undefined
            || ["chrome", "eval", "Function", "require", "fetch", "WebSocket"]
              .includes(constantString(node.arguments[1], constants) ?? ""))) {
          add("E_CHROME_API_NOT_ALLOWLISTED");
        }
        if (pathEndsWith(directPath, ["Object", "values"])
          && node.arguments[0] !== undefined
          && hasGlobalRoot(node.arguments[0])) {
          add("E_CHROME_API_NOT_ALLOWLISTED");
        }
        if ((pathEndsWith(directPath, ["Object", "defineProperty"])
            || pathEndsWith(directPath, ["Reflect", "defineProperty"]))
          && node.arguments.length >= 2) {
          add("E_FIXED_PROBE_SHAPE");
        }
        if (pathEndsWith(directPath, ["Reflect", "set"])) {
          const member = node.arguments[1] === undefined
            ? undefined
            : constantString(node.arguments[1], constants);
          if (member === undefined || /^(?:onmessage|onMessage|innerHTML|outerHTML|textContent|className|id|value|checked|src|href|cssText)$/u.test(member)) {
            add(member?.toLowerCase().includes("message") === true
              ? "E_UNTRUSTED_COMMAND_CHANNEL"
              : "E_FIXED_PROBE_SHAPE");
          }
        }
        if (pathEndsWith(directPath, ["Object", "assign"])) {
          add("E_FIXED_PROBE_SHAPE");
        }

        if (pathEndsWith(callPath, ["require"]) || pathEndsWith(callPath, ["importScripts"])) {
          add("E_DYNAMIC_MODULE_LOADING");
        }
        if (pathEndsWith(callPath, ["eval"]) || pathEndsWith(callPath, ["Function"])) {
          add("E_DYNAMIC_CODE");
        }
        if ((pathEndsWith(callPath, ["setTimeout"]) || pathEndsWith(callPath, ["setInterval"]))
          && (node.arguments[0] === undefined
            || (!isArrowFunction(node.arguments[0]) && !isFunctionExpression(node.arguments[0])))) {
          add("E_DYNAMIC_CODE");
        }
        const projectedAppend = callFinal === "append"
          && node.arguments.length === 1
          && node.arguments[0] !== undefined
          && isCallExpression(node.arguments[0])
          && pathEndsWith(
            expressionPath(node.arguments[0].expression, constants),
            ["projectBeforePersistence"],
          )
          && hasCanonicalProjectionImport(sourceFile, path);
        if (DOM_MUTATION_NAMES.has(callFinal)
          && canonicalStorageMember === undefined
          && !projectedAppend) {
          add("E_FIXED_PROBE_SHAPE");
        }
        if (["insertNode", "insertRule", "replaceSync"].includes(callFinal)) {
          add("E_FIXED_PROBE_SHAPE");
        }
        if (NAVIGATION_MUTATION_NAMES.has(callFinal)
          && callPath?.some((part) => /^(?:history|location|navigation)$/u.test(part)) === true) {
          add("E_LOCATION_SAFETY_STOP");
        }
        if (pathEndsWith(callPath, ["window", "open"])
          || pathEndsWith(callPath, ["navigation", "navigate"])) {
          add("E_LOCATION_SAFETY_STOP");
        }
        if (pathEndsWith(callPath, ["fetch"])) add("E_OUTBOUND_NETWORK_PATH");
        if (
          pathEndsWith(callPath, ["sendBeacon"])
          || pathEndsWith(callPath, ["submit"])
          || pathEndsWith(callPath, ["requestSubmit"])
          || (pathEndsWith(callPath, ["open"])
            && /(?:request|xhr|xmlHttpRequest)/iu.test(storageReceiver))
        ) {
          add("E_OUTBOUND_NETWORK_PATH");
        }
        if (pathEndsWith(callPath, ["postMessage"])) add("E_PAGE_COMMAND_CHANNEL");
        if (callFinal === "send") {
          const payload = node.arguments[0];
          const authenticated = isAuthenticatedLoopbackOwner(node, path)
            && node.arguments.length === 1
            && payload !== undefined
            && isCallExpression(payload)
            && pathEndsWith(expressionPath(payload.expression, constants), ["encodeAuthenticatedFact"])
            && payload.arguments.length === 5
            && payload.arguments[0] !== undefined
            && isIdentifier(payload.arguments[0])
            && payload.arguments[0].text === "fact"
            && payload.arguments[1]?.getText() === "pairingSecret"
            && payload.arguments[2]?.getText() === "sessionId"
            && constantString(payload.arguments[3] as Expression, constants) === "CLIENT_TO_BACKEND"
            && payload.arguments[4]?.getText() === "nextOutboundCounter"
            && !containsForbiddenFactShape(payload.arguments[0], constants);
          if (!authenticated) add("E_LOOPBACK_FACT_UNION");
        }
        if ((pathEndsWith(callPath, ["console", "log"])
          || pathEndsWith(callPath, ["crypto", "subtle", "digest"]))
          && node.arguments.some((argument) => containsTaintedIdentifier(argument, tainted))) {
          add("E_PERSISTENCE_BEFORE_PROJECTION");
        }
        if (
          pathEndsWith(callPath, ["onMessageExternal", "addListener"])
          || pathEndsWith(callPath, ["sendMessage"])
        ) {
          add("E_UNTRUSTED_COMMAND_CHANNEL");
        }
        if (
          pathEndsWith(callPath, ["localStorage", "setItem"])
          || pathEndsWith(callPath, ["sessionStorage", "setItem"])
          || pathEndsWith(callPath, ["caches", "open"])
          || pathEndsWith(callPath, ["chrome", "storage", "local", "set"])
          || (
            callPath?.includes("chrome") === true
            && callPath.includes("storage")
            && finalPathPart(callPath) === "set"
          )
          || pathEndsWith(callPath, ["writeFile"])
          || pathEndsWith(callPath, ["appendFile"])
          || pathEndsWith(callPath, ["writeFileSync"])
          || pathEndsWith(callPath, ["appendFileSync"])
          || pathEndsWith(callPath, ["createWriteStream"])
          || pathEndsWith(callPath, ["getFileHandle"])
          || pathEndsWith(callPath, ["createWritable"])
          || pathEndsWith(callPath, ["navigator", "storage", "getDirectory"])
        ) {
          add("E_PERSISTENCE_BEFORE_PROJECTION");
          add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
        }
        if (
          pathEndsWith(callPath, ["window", "addEventListener"])
          && node.arguments[0] !== undefined
          && constantString(node.arguments[0], constants) === "message"
        ) {
          add("E_PAGE_COMMAND_CHANNEL");
        }
        if (
          (pathEndsWith(callPath, ["chrome", "runtime", "onMessage", "addListener"])
            && !inAllowedChromeOwner)
          || pathEndsWith(callPath, ["chrome", "runtime", "onConnect", "addListener"])
          || pathEndsWith(callPath, ["chrome", "runtime", "onConnectExternal", "addListener"])
          || callPath?.includes("commands") === true
          || pathEndsWith(callPath, ["onmessage"])
          || (pathEndsWith(callPath, ["onMessage", "addListener"])
            && !inAllowedChromeOwner)
        ) {
          add("E_UNTRUSTED_COMMAND_CHANNEL");
        }
        if (
          pathEndsWith(callPath, ["addEventListener"])
          && node.arguments[0] !== undefined
          && constantString(node.arguments[0], constants) === "message"
        ) {
          const authenticated = isAuthenticatedLoopbackOwner(node, path)
            && node.arguments.length === 2
            && exactAuthenticatedMessageCallback(node.arguments[1]);
          if (!authenticated) add("E_UNTRUSTED_COMMAND_CHANNEL");
        }
        if (pathEndsWith(callPath, ["chrome", "debugger", "sendCommand"])) {
          if (indirect) add("E_INDIRECT_PRIVILEGED_CALL");
          if (!inAllowedChromeOwner) add("E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER");
          const method = node.arguments[1] === undefined || !isStringLiteral(node.arguments[1])
            ? undefined
            : constantString(node.arguments[1], constants);
          if (method === undefined) {
            add("E_CDP_METHOD_NOT_LITERAL");
          } else {
            const methodError = classifyCdpMethod(method);
            if (methodError !== undefined) add(methodError);
            if (ALLOWED_CDP.has(method)) {
              const target = node.arguments[0];
              const parameters = node.arguments[2];
              const expected = method === "Network.enable" ? EXPECTED_ENABLE_ARGUMENTS : {};
              if (
                node.arguments.length !== 3
                || target === undefined
                || !(
                  exactSelectedTarget(node, path, target, constants, aliases)
                )
                || parameters === undefined
                || !equalJson(objectValue(parameters, constants, objects), expected)
              ) {
                add("E_CDP_PARAMETER_MISMATCH");
              }
            }
          }
          const target = node.arguments[0];
          if (
            target !== undefined
            && (
              (isIdentifier(target) && childTargets.has(target.text))
              || (
                isObjectLiteralExpression(target)
                && target.properties.some(
                  (property) => (isPropertyAssignment(property) || isShorthandPropertyAssignment(property))
                    && ["sessionId", "targetId"].includes(propertyName(property.name, constants) ?? ""),
                )
              )
            )
          ) {
            add("E_CHILD_SESSION_DENIED");
          }
        }
        if (pathEndsWith(callPath, ["sendLiteralCommand"])) {
          const method = node.arguments[0] === undefined
            ? undefined
            : constantString(node.arguments[0], constants);
          if (method === undefined) add("E_CDP_METHOD_NOT_LITERAL");
          else {
            const methodError = classifyCdpMethod(method);
            if (methodError !== undefined) add(methodError);
          }
        }
        if (pathEndsWith(callPath, ["runFixedProbe"])) {
          const probeId = node.arguments[0] === undefined
            ? undefined
            : constantString(node.arguments[0], constants);
          if (!new Set(["APP_LOCATION_CONTEXT_V1", "DOM_DOCUMENT_LIFECYCLE_V1"]).has(probeId ?? "")) {
            add("E_FIXED_PROBE_ID");
          } else if (node.arguments.length !== 1) {
            add("E_FIXED_PROBE_SHAPE");
          }
        }
        if (
          /frame/iu.test(finalPathPart(callPath))
          && finalPathPart(callPath) !== "getAllFrames"
          && node.arguments.length > 0
        ) {
          add("E_FRAME_OWNERSHIP");
        }
        if (/(?:archive|backup|compact|purge|cleanup|restore|delete)/iu.test(finalPathPart(callPath))) {
          add("E_CUSTODY_PATH_DENIED");
        }
        if (/(?:wager|betslip|cashout|providerperformance|productionoperator)/iu.test(finalPathPart(callPath))) {
          add("E_PRODUCTION_CAPABILITY_REACHABLE");
        }
      }
    }

    if (
      isAssignment(node)
      && (
        expressionPath(node.left, constants)?.some((part) => part === "location") === true
        || pathEndsWith(expressionPath(node.left, constants), ["window", "location"])
        || pathEndsWith(expressionPath(node.left, constants), ["document", "location"])
        || pathEndsWith(expressionPath(node.left, constants), ["top", "location"])
      )
    ) {
      add("E_LOCATION_SAFETY_STOP");
    }
    if (
      isAssignment(node)
      && ["onmessage", "onMessage"].includes(finalPathPart(expressionPath(node.left, constants)))
    ) {
      if (!isAuthenticatedLoopbackOwner(node, path)
        || !exactAuthenticatedMessageCallback(node.right)) {
        add("E_UNTRUSTED_COMMAND_CHANNEL");
      }
    }
    if (
      isAssignment(node)
    ) {
      if (isIdentifier(node.left)) {
        if (hasEnclosingParameter(node, node.left.text)) {
          add("E_PARAMETER_MUTATION");
        }
        if (containsTaintedIdentifier(node.right, tainted)) tainted.add(node.left.text);
        const alias = resolveAlias(expressionPath(node.right, constants), aliases);
        if (alias !== undefined) {
          aliases.set(node.left.text, alias);
          if (pathEndsWith(alias, ["chrome", "debugger"])) {
            add("E_PRIVILEGED_API_ALIAS");
          }
        }
      }
      const assignmentPath = expressionPath(node.left, constants);
      const assignmentFinal = finalPathPart(assignmentPath);
      const propertyWrite = isPropertyAccessExpression(node.left)
        || isElementAccessExpression(node.left);
      const canonicalParserWrite = /(?:^|[/\\])canonical\.(?:ts|js)$/u.test(path);
      const canonicalStorageHandler = STORAGE_HANDLER_NAMES.has(assignmentFinal)
        && ownerMatches(node, path, policy.storageOwner);
      const canonicalSpoolAuthorization = ownerMatches(node, path, policy.storageOwner)
        && compactSource(node.left) === "this.authorization";
      if (propertyWrite && !canonicalParserWrite && !canonicalStorageHandler
        && !canonicalSpoolAuthorization) {
        add("E_FIXED_PROBE_SHAPE");
      }
      if (["className", "cssText", "dataset", "innerHTML", "outerHTML", "textContent"]
        .includes(assignmentFinal)
        || (["checked", "href", "id", "src", "value"].includes(assignmentFinal)
          && (assignmentPath?.some((part) => /^(?:document|element|location|window)$/u.test(part))
            || domTypes.has(assignmentPath?.at(-2) ?? "")))) {
        add("E_FIXED_PROBE_SHAPE");
      }
      if (STORAGE_HANDLER_NAMES.has(assignmentFinal)) {
        const storageOwner = ownerMatches(node, path, policy.storageOwner)
          && isWithinSpoolAppendFlow(node);
        const receiver = assignmentPath?.at(-2) ?? "";
        const receiverType = storageTypes.get(receiver);
        const canonicalHandler = receiverType !== undefined
          && policy.storageHandlers.has(`${receiverType}.${assignmentFinal}`);
        storageUsed = true;
        if (!storageOwner || !canonicalHandler) {
          add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
        } else {
          const parameters = callbackParameters(node.right);
          if (!equalJson(parameters, ["event"]) || callbackReturnsValue(node.right)) {
            add("E_PERSISTENCE_CONTRACT_MISMATCH");
          }
          const exactEffect = new Map<string, readonly string[]>([
            ["onupgradeneeded", [
              "if(event.oldVersion!==0||event.newVersion!==1){thrownewError(\"SAFETY_STOP\");}",
            ]],
            ["onsuccess", ["validateRequestSuccess(event);"],
            ],
            ["onerror", ["abortAndFailClosed(event);"],
            ],
            ["onblocked", ["failClosedNoAppend(event);"],
            ],
            ["oncomplete", ["resolveDurablySpooled(durableCompletion,committedRecord);"],
            ],
            ["onabort", ["failClosedNoDurabilityClaim(event,durableCompletion);"],
            ],
            ["onversionchange", ["closeAndFailClosed(event);"],
            ],
          ]).get(assignmentFinal);
          if (exactEffect === undefined || node.right === undefined
            || !isArrowFunction(node.right) && !isFunctionExpression(node.right)
            || !isBlock(node.right.body)
            || !exactEffect.every((effect, index) =>
              callbackHasExactStatement(node.right, index, effect))) {
            add("E_PERSISTENCE_CONTRACT_MISMATCH");
          }
        }
      }
      if (
        pathEndsWith(assignmentPath, ["localStorage"])
        || pathEndsWith(assignmentPath, ["sessionStorage"])
        || assignmentPath?.includes("localStorage")
        || assignmentPath?.includes("sessionStorage")
      ) {
        add("E_PERSISTENCE_BEFORE_PROJECTION");
        add("E_PERSISTENCE_API_NOT_ALLOWLISTED");
      }
    }

    if (isNewExpression(node)) {
      const constructorPath = resolveAlias(expressionPath(node.expression, constants), aliases);
      if (pathEndsWith(constructorPath, ["Function"])) add("E_DYNAMIC_CODE");
      if (pathEndsWith(constructorPath, ["XMLHttpRequest"])
        || pathEndsWith(constructorPath, ["EventSource"])
        || pathEndsWith(constructorPath, ["Worker"])
        || pathEndsWith(constructorPath, ["Image"])) add("E_OUTBOUND_NETWORK_PATH");
      if (pathEndsWith(constructorPath, ["WebSocket"])) {
        const url = node.arguments?.[0] === undefined
          ? undefined
          : constantString(node.arguments[0], constants);
        if (!isAuthenticatedLoopbackOwner(node, path) || url !== "ws://127.0.0.1:8765") {
          add("E_LOOPBACK_URL_NOT_LITERAL");
        }
      }
      if (pathEndsWith(constructorPath, ["BroadcastChannel"])) {
        add("E_UNTRUSTED_COMMAND_CHANNEL");
      }
    }

    if (isCallExpression(node)) {
      const called = expressionPath(node.expression, constants);
      if (called?.includes("constructor") === true
        || (pathEndsWith(called, ["Reflect", "construct"])
          && node.arguments[0] !== undefined
          && expressionPath(node.arguments[0], constants)?.includes("constructor") === true)) {
        add("E_DYNAMIC_CODE");
      }
    }

    if (isIdentifier(node)) {
      if (["fetch", "XMLHttpRequest", "EventSource", "Worker", "Image", "importScripts"]
        .includes(node.text)) {
        add("E_OUTBOUND_NETWORK_PATH");
      }
      if (node.text === "WebSocket") {
        const directLoopback = node.parent !== undefined
          && isNewExpression(node.parent)
          && node.parent.expression === node
          && isAuthenticatedLoopbackOwner(node, path)
          && node.parent.arguments?.[0] !== undefined
          && constantString(node.parent.arguments[0], constants) === "ws://127.0.0.1:8765";
        if (!directLoopback) add("E_LOOPBACK_URL_NOT_LITERAL");
      }
      if (node.text === "chrome") {
        const parent = node.parent;
        const chainContinues = parent !== undefined
          && (isPropertyAccessExpression(parent) || isElementAccessExpression(parent))
          && parent.expression === node;
        if (!chainContinues && (parent === undefined || !isQualifiedName(parent))) {
          add("E_CHROME_API_NOT_ALLOWLISTED");
        }
      }
      if (["require", "eval", "Function", "importScripts"].includes(node.text)) {
        add(node.text === "require" ? "E_DYNAMIC_MODULE_LOADING" : "E_DYNAMIC_CODE");
      }
    }

    if (isObjectLiteralExpression(node)) {
      const properties = new Map<string, unknown>();
      for (const property of node.properties) {
        if (isPropertyAssignment(property)) {
          const name = propertyName(property.name, constants);
          if (name !== undefined) {
            properties.set(name, objectValue(property.initializer, constants, objects));
          }
        }
      }
      if (
        properties.has("cdp_method")
        || properties.get("message_type") === "COMMAND"
        || properties.has("command")
        || properties.has("action")
      ) {
        add("E_LOOPBACK_FACT_UNION");
      }
      const forbiddenEventFields = new Set([
        "authorization",
        "cookie",
        "errorText",
        "fragment",
        "header",
        "headers",
        "password",
        "payloadData",
        "postData",
        "query",
        "sseData",
        "userinfo",
        "username",
      ]);
      if ([...properties.keys()].some((name) => forbiddenEventFields.has(name))) {
        add("E_EVENT_FIELD_DENIED");
      }
    }

    node.forEachChild((child) => { visit(child); });
  };

  visit(sourceFile);
  if (storageUsed && pathMatchesOwnerFile(path, policy.storageOwner)) {
    const requiredOrderedCalls = [
      "IDBDatabase.transaction",
      "IDBTransaction.objectStore",
      "IDBTransaction.objectStore",
      "IDBObjectStore.get",
      "IDBObjectStore.add",
      "IDBObjectStore.put",
    ];
    let cursor = 0;
    for (const operation of storageCallOrder) {
      if (operation === requiredOrderedCalls[cursor]) cursor += 1;
    }
    if (!hasExactDatabaseBinding(sourceFile)
      || !hasExactSpoolAppendContract(sourceFile, path)
      || cursor !== requiredOrderedCalls.length) {
      add("E_PERSISTENCE_CONTRACT_MISMATCH");
    }
  }
  return unique(errors);
};

const verifyAst = (
  root: string,
  files: readonly string[],
  policy: CapabilityPolicy,
): string[] => {
  if (files.length === 0) return [];
  return unique(files.flatMap((path) => {
    const sourceFile = createSourceFile(
      path,
      readFileSync(path, "utf8"),
      ScriptTarget.Latest,
      true,
      extname(path) === ".js" ? ScriptKind.JS : ScriptKind.TS,
    );
    return scanSourceFile(sourceFile, path, root, policy);
  }));
};

export const verifyCapabilityGraph = (root: string): string[] => {
  const absoluteRoot = resolve(root);
  const policy = loadCapabilityPolicy();
  if (policy === undefined) return ["E_CAPABILITY_POLICY_DRIFT"];
  const errors = verifyAst(absoluteRoot, filesBelow(absoluteRoot), policy);
  if (absoluteRoot.endsWith(`${sep}extension${sep}src`)) {
    const manifest = resolve(absoluteRoot, "../manifest.json");
    const canonical = resolve(
      process.cwd(),
      "vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json",
    );
    if (!existsSync(manifest) || !existsSync(canonical)) errors.push("E_MANIFEST_CAPABILITY_MISMATCH");
    else errors.push(...verifyCapabilityManifest(manifest, canonical));
    const compiledRoot = resolve(absoluteRoot, "../dist");
    if (!existsSync(compiledRoot)) errors.push("E_COMPILED_CHUNK_MISSING");
    else {
      const expectedCompiled = new Set(
        filesBelow(absoluteRoot)
          .filter((path) => path.endsWith(".ts") && !path.endsWith(".d.ts"))
          .map((path) => `${relative(absoluteRoot, path).slice(0, -3)}.js`),
      );
      const actualCompiled = new Set(
        allFilesBelow(compiledRoot).map((path) => relative(compiledRoot, path)),
      );
      if (!equalJson([...actualCompiled].sort(), [...expectedCompiled].sort())) {
        errors.push("E_COMPILED_CHUNK_SET");
      }
      errors.push(...verifyAst(compiledRoot, filesBelow(compiledRoot), policy));
    }
  }
  return unique(errors);
};

export const main = (argv: readonly string[] = process.argv.slice(2)): number => {
  const errors = verifyCapabilityGraph(resolve(argv[0] ?? "src"));
  if (errors.length) process.stderr.write(`${errors.join("\n")}\n`);
  return errors.length ? 1 : 0;
};

const invokedPath = process.argv[1];
if (invokedPath !== undefined && import.meta.url === `file://${invokedPath}`) process.exitCode = main();
