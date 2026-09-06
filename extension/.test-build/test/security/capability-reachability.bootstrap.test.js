import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import { verifyCapabilityGraph, verifyCapabilityManifest, } from "../../tools/verify-capability-graph.js";
void test("bootstrap privilege graph is closed", () => {
    assert.deepEqual(verifyCapabilityGraph(resolve("extension/src")), []);
});
void test("security-sensitive stubs expose no arbitrary map or index signature", () => {
    const sensitive = [
        resolve("extension/src/security/redaction.ts"),
        resolve("extension/src/spool.ts"),
    ].map((path) => readFileSync(path, "utf8")).join("\n");
    assert.doesNotMatch(sensitive, /Record<string,\s*unknown>|\[key:\s*string\]/u);
});
void test("compiler scanner rejects closed-world escape classes", () => {
    const fixtures = [
        "fetch('https://example.invalid')",
        "await import(name)",
        "eval(source)",
        "new WebSocket(url)",
        "sendLiteralCommand('Network.' + operation)",
        "chrome.debugger.sendCommand(target, 'Runtime.evaluate')",
        "const send = chrome.debugger.sendCommand",
        "chrome.runtime.onMessageExternal.addListener(handler)",
        "localStorage.setItem('raw', payload)",
    ];
    for (const [index, source] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], source);
    }
});
void test("AST and module reachability reject computed aliases and indirect sinks", () => {
    const fixtures = [
        [
            "computed debugger alias",
            "const send = chrome['debug' + 'ger']['send' + 'Command']; send(target, 'Network.enable', {});",
        ],
        ["computed fetch", "globalThis['fe' + 'tch']('https://example.invalid')"],
        ["remote static import", "import 'https://example.invalid/module.js'"],
        ["bare re-export", "export * from 'unapproved-package'"],
        [
            "aliased persistence with projection decoy",
            "const save = localStorage.setItem.bind(localStorage); projectBeforePersistence(payload); save('raw', raw);",
        ],
        [
            "generic exported dispatch",
            "export function sendCdpCommand(method: string, params: object) { return chrome.debugger.sendCommand({}, method, params); }",
        ],
        ["page command channel", "window.postMessage({command: 'ATTACH'}, '*')"],
        ["target attachment escape", "chrome.debugger.attach({targetId}, '1.3')"],
        [
            "child session escape",
            "chrome.debugger.sendCommand({sessionId}, 'Network.enable', {});",
        ],
    ];
    for (const [index, [name, source]] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-ast-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
});
void test("AST provenance rejects recursive aliases, indirect calls, handlers, and storage sinks", () => {
    const exactArguments = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
    const fixtures = [
        ["recursive privileged alias", `const d=chrome.debugger; const send=d.sendCommand; send(target,'Network.enable',${exactArguments})`],
        ["Reflect.apply privilege", `Reflect.apply(chrome.debugger.sendCommand,chrome.debugger,[target,'Network.enable',${exactArguments}])`],
        ["comma-call privilege", `(0,chrome.debugger.sendCommand)(target,'Network.enable',${exactArguments})`],
        ["cast computed privilege", `chrome.debugger['sendCommand' as string](target,'Network.enable',${exactArguments})`],
        ["destructured fetch", "const {fetch: outbound}=globalThis; outbound(url)"],
        ["arbitrary executeScript", "chrome.scripting.executeScript({target, func: userFunction})"],
        ["page message listener", "window.addEventListener('message', handler)"],
        ["runtime message listener", "chrome.runtime.onMessage.addListener(handler)"],
        ["debugger target enumeration", "chrome.debugger.getTargets(callback)"],
        ["tabs mutation", "chrome.tabs.update(tabId, {url})"],
        ["sync file persistence", "writeFileSync(path, raw); createWriteStream(path)"],
    ];
    for (const [index, [name, source]] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-provenance-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
});
void test("AST privilege references fail closed across carriers and assignment forms", () => {
    const exactArguments = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
    const fixtures = [
        `const holder={run:chrome.debugger.sendCommand}; holder.run(target,'Network.enable',${exactArguments})`,
        `[chrome.debugger.sendCommand][0](target,'Network.enable',${exactArguments})`,
        `function invoke(fn: unknown){}; invoke(chrome.debugger.sendCommand)`,
        `let send; send=chrome.debugger.sendCommand; send(target,'Network.enable',${exactArguments})`,
        `class Holder { run=chrome.debugger.sendCommand }`,
        `Reflect.get(chrome.debugger,'sendCommand')(target,'Network.enable',${exactArguments})`,
        "socket.onmessage=handler",
        "window.onmessage=handler",
        "chrome.runtime.onConnect.addListener(handler)",
        "navigator.storage.getDirectory().then(root => root.getFileHandle(name).then(file => file.createWritable().then(writer => writer.write(raw))))",
    ];
    for (const [index, source] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-carrier-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], source);
    }
});
void test("strict-linked structural bypass corpus compiles and is rejected", () => {
    const prelude = `
declare const secret: unknown;
declare const html: string;
declare const value: string;
declare const url: string;
declare const body: BodyInit;
declare const sourceText: string;
declare const attackerTabId: number;
declare const attackerDomain: string;
declare const rule: string;
declare const css: string;
declare const fragment: Node;
declare const element: HTMLElement;
declare const range: Range;
declare const sheet: CSSStyleSheet;
declare function getAnchor(): HTMLAnchorElement;
declare function getNode(): unknown;
declare function leakRaw(value: unknown): void;
declare function executePrivileged(value: unknown): void;
declare function invokePrivileged(value: unknown): void;
type DiscoveryRunAuthorization={browser_binding:{tab_id:number,browser_run_id:string}};
`;
    const fixtures = [
        ["cdp-disable-params-mutated", "security/cdp-broker.ts", "export function sendLiteralCommand(authorization:DiscoveryRunAuthorization){const params={};(params as Record<string,unknown>).evil=secret;chrome.debugger.sendCommand({tabId:authorization.browser_binding.tab_id},'Network.disable',params)}"],
        ["cdp-enable-params-mutated", "security/cdp-broker.ts", "export function sendLiteralCommand(authorization:DiscoveryRunAuthorization){const params={maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0};params.maxPostDataSize=999;chrome.debugger.sendCommand({tabId:authorization.browser_binding.tab_id},'Network.enable',params)}"],
        ["authorization-tab-mutated", "security/cdp-broker.ts", "export function sendLiteralCommand(authorization:DiscoveryRunAuthorization){authorization.browser_binding.tab_id=attackerTabId;chrome.debugger.sendCommand({tabId:authorization.browser_binding.tab_id},'Network.disable',{})}"],
        ["chrome-via-global-values", "fixture.ts", "const c=Object.values(globalThis).find((v:any)=>v?.debugger?.sendCommand) as any;c.debugger.sendCommand({tabId:1},'Runtime.evaluate',{})"],
        ["fetch-via-global-values", "fixture.ts", "const f=Object.values(globalThis).find((v:any)=>typeof v==='function'&&v.name==='fetch') as any;f(url,{method:'POST',body})"],
        ["eval-via-global-values", "fixture.ts", "const e=Object.values(globalThis).find((v:any)=>typeof v==='function'&&v.name==='eval') as any;e(sourceText)"],
        ["function-constructor-chain", "fixture.ts", "([] as any).constructor.constructor(sourceText)()"],
        ["function-reflect-construct-chain", "fixture.ts", "Reflect.construct((()=>{}).constructor as any,[sourceText])"],
        ["dom-returned-anchor", "fixture.ts", "const link=getAnchor();link.href=url"],
        ["dom-untyped-anchor", "fixture.ts", "const link=getNode() as HTMLAnchorElement;link.href=url"],
        ["dom-location-alias", "fixture.ts", "const loc=location;loc.href=url"],
        ["dom-cookie", "fixture.ts", "document.cookie=String(secret)"],
        ["dom-domain", "fixture.ts", "document.domain=attackerDomain"],
        ["dom-title", "fixture.ts", "document.title=String(secret)"],
        ["dom-style", "fixture.ts", "element.style.color=value"],
        ["dom-dataset", "fixture.ts", "element.dataset.command=value"],
        ["dom-object-define-property", "fixture.ts", "Object.defineProperty(element,'innerHTML',{value:html})"],
        ["dom-reflect-define-property", "fixture.ts", "Reflect.defineProperty(element,'innerHTML',{value:html})"],
        ["dom-range-insert-node", "fixture.ts", "range.insertNode(fragment)"],
        ["dom-stylesheet-insert-rule", "fixture.ts", "sheet.insertRule(rule,0)"],
        ["dom-stylesheet-replace-sync", "fixture.ts", "sheet.replaceSync(css)"],
        ["dom-script-text", "fixture.ts", "const script=document.createElement('script');script.text=sourceText"],
        ["dom-timer-mutation", "fixture.ts", "setTimeout(()=>{const link=document.querySelector<HTMLAnchorElement>('a')!;link.href=url},1)"],
        ["malicious-cdp-projector", "security/cdp-broker.ts", "const projectCdpEvent=(_method:string,params:unknown):void=>leakRaw(params);export const closed=projectCdpEvent"],
        ["noop-safety-stop", "security/cdp-broker.ts", "const safetyStopAndSealRun=():void=>{};export const closed=safetyStopAndSealRun"],
        ["malicious-public-handler", "security/run-controller.ts", "const handlePublicMessage=(message:unknown):unknown=>{executePrivileged(message);return {message_type:'OK'}};export const closed=handlePublicMessage"],
        ["malicious-navigation-projector", "security/target-policy.ts", "const projectNavigationEvent=(details:unknown):void=>leakRaw(details);export const closed=projectNavigationEvent"],
        ["malicious-loopback-encoder", "security/loopback.ts", "type SanitizedFact={fact_type:string};const encodeAuthenticatedFact=(_fact:SanitizedFact,_secret:string,_sessionId:string,_direction:'CLIENT_TO_BACKEND',_counter:number):Uint8Array=>new TextEncoder().encode('{\"message_type\":\"COMMAND\"}');export const closed=encodeAuthenticatedFact"],
        ["malicious-loopback-decoder", "security/loopback.ts", "const decodeAuthenticatedFact=(data:unknown):void=>invokePrivileged(data);export const closed=decodeAuthenticatedFact"],
    ];
    for (const [index, [name, relativePath, body]] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-strict-${String(index)}-`));
        const sourceRoot = resolve(root, "extension/src");
        const path = resolve(sourceRoot, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, `${prelude}\n${body}\n`);
        const configPath = resolve(root, "extension/tsconfig.json");
        writeFileSync(configPath, JSON.stringify({
            compilerOptions: {
                lib: ["ES2024", "DOM"],
                module: "NodeNext",
                moduleResolution: "NodeNext",
                noEmit: true,
                skipLibCheck: true,
                strict: true,
                target: "ES2024",
                typeRoots: [resolve("extension/node_modules/@types")],
                types: ["chrome"],
            },
            include: ["src/**/*.ts"],
        }));
        const compile = spawnSync(process.execPath, [resolve("extension/node_modules/typescript/bin/tsc"), "-p", configPath], { encoding: "utf8" });
        assert.equal(compile.status, 0, `${name}: ${compile.stdout}${compile.stderr}`);
        assert.notDeepEqual(verifyCapabilityGraph(sourceRoot), [], name);
    }
});
void test("closed allowlists reject unknown CDP, command listeners, and storage variants", () => {
    const exactArguments = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
    const fixtures = [
        `chrome.debugger.sendCommand(target,'Browser.close',{})`,
        `const member='send'+'Command'; chrome.debugger[member](target,method,${exactArguments})`,
        `const child={sessionId}; chrome.debugger.sendCommand(child,'Network.disable',{})`,
        `chrome.scripting.executeScript({target,func:userFunction})`,
        `const enumerate=chrome.debugger.getTargets; enumerate(callback)`,
        `const attach=chrome.debugger.attach; attach(target,'1.3')`,
        `const network=fetch; network(url)`,
        `const Request=XMLHttpRequest; new Request()`,
        `const Socket=WebSocket; new Socket(userUrl)`,
        `chrome.runtime.onConnectExternal.addListener(handler)`,
        `chrome.commands.onCommand.addListener(handler)`,
        `new BroadcastChannel('commands')`,
        `socket.addEventListener('message',handler)`,
        `sessionStorage.token=raw`,
        `localStorage['raw']=payload`,
        `chrome.storage.sync.set({raw})`,
    ];
    for (const [index, source] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-closed-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], source);
    }
});
void test("assignment aliases inherit privileged and network provenance", () => {
    const exactArguments = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
    const fixtures = [
        `let d:any; d=chrome.debugger; d.sendCommand(target,'Network.enable',${exactArguments})`,
        "let d:any; d=chrome.debugger; d.getTargets(callback)",
        "let d:any; d=chrome.debugger; d.attach(target,'1.3')",
        "let f:any; f=fetch; f(url)",
        "let W:any; W=WebSocket; new W(url)",
    ];
    for (const [index, source] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-assignment-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], source);
    }
});
void test("privileged roots cannot escape through closures or object carriers", () => {
    const exactArguments = "{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0}";
    const fixtures = [
        `const d=(()=>chrome.debugger)(); d.sendCommand(target,'Network.enable',${exactArguments})`,
        `const holder={d:chrome.debugger}; holder.d.sendCommand(target,'Network.enable',${exactArguments})`,
        "const f=(()=>fetch)(); f(url)",
        "const W=(()=>WebSocket)(); new W(url)",
    ];
    for (const [index, source] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-carried-root-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], source);
    }
    const root = mkdtempSync(resolve(tmpdir(), "capability-broker-alias-"));
    const brokerDirectory = resolve(root, "src/security");
    mkdirSync(brokerDirectory, { recursive: true });
    writeFileSync(resolve(brokerDirectory, "cdp-broker.ts"), "export const escape = chrome.debugger.sendCommand;");
    assert.ok(verifyCapabilityGraph(root).includes("E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"));
    writeFileSync(resolve(brokerDirectory, "cdp-broker.ts"), "export const escape = (target: chrome.debugger.Debuggee) => chrome.debugger.sendCommand(target, 'Network.disable', {});");
    assert.ok(verifyCapabilityGraph(root).includes("E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"));
});
void test("compiled module set is exact and cannot hide omitted or extra chunks", () => {
    const root = mkdtempSync(resolve(tmpdir(), "capability-compiled-"));
    const sourceRoot = resolve(root, "extension/src");
    const distRoot = resolve(root, "extension/dist");
    mkdirSync(sourceRoot, { recursive: true });
    mkdirSync(distRoot, { recursive: true });
    writeFileSync(resolve(sourceRoot, "bootstrap.ts"), "export const held = true;");
    writeFileSync(resolve(root, "extension/manifest.json"), readFileSync(resolve("extension/manifest.json")));
    assert.ok(verifyCapabilityGraph(sourceRoot).includes("E_COMPILED_CHUNK_SET"));
    writeFileSync(resolve(distRoot, "bootstrap.js"), "export const held = true;");
    writeFileSync(resolve(distRoot, "evil.mjs"), "fetch('https://example.invalid')");
    assert.ok(verifyCapabilityGraph(sourceRoot).includes("E_COMPILED_CHUNK_SET"));
});
void test("local module graph resolves only files inside the scanned root", () => {
    const root = mkdtempSync(resolve(tmpdir(), "capability-module-"));
    writeFileSync(resolve(root, "entry.ts"), "export {value} from './local.js';");
    writeFileSync(resolve(root, "local.ts"), "export const value = 'closed';");
    assert.deepEqual(verifyCapabilityGraph(root), []);
    writeFileSync(resolve(root, "entry.ts"), "export {value} from './missing.js';");
    assert.ok(verifyCapabilityGraph(root).includes("E_REMOTE_OR_SPLIT_CODE"));
});
void test("closed broker permits only literal Network methods with exact arguments", () => {
    const root = mkdtempSync(resolve(tmpdir(), "capability-broker-"));
    const brokerDirectory = resolve(root, "src/security");
    mkdirSync(brokerDirectory, { recursive: true });
    const broker = resolve(brokerDirectory, "cdp-broker.ts");
    writeFileSync(broker, `export const sendLiteralCommand = (authorization: DiscoveryRunAuthorization) => {
      const selectedTabId = authorization.browser_binding.tab_id;
      chrome.debugger.sendCommand({tabId:selectedTabId}, "Network.enable", {
        maxTotalBufferSize: 33554432,
        maxResourceBufferSize: 2097152,
        maxPostDataSize: 0,
      });
      chrome.debugger.sendCommand({tabId:selectedTabId}, "Network.disable", {});
    };`);
    assert.deepEqual(verifyCapabilityGraph(root), []);
    writeFileSync(broker, `export const sendLiteralCommand = (authorization: DiscoveryRunAuthorization) => {
      const selectedTabId = authorization.browser_binding.tab_id;
      chrome.debugger.sendCommand({tabId:selectedTabId}, "Network.enable", {maxPostDataSize: 1});
    }`);
    assert.ok(verifyCapabilityGraph(root).includes("E_CDP_PARAMETER_MISMATCH"));
});
void test("actual extension manifest exactly matches canonical capability surfaces", () => {
    assert.deepEqual(verifyCapabilityManifest(resolve("extension/manifest.json"), resolve("vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json")), []);
});
void test("all canonical manifest escape vectors mutate exact executable surfaces", () => {
    const canonicalPath = resolve("vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json");
    const actual = JSON.parse(readFileSync(resolve("extension/manifest.json"), "utf8"));
    const mutations = [
        ["CAP-NEG-031", (manifest) => { manifest.host_permissions = ["https://example.invalid/*"]; }],
        ["CAP-NEG-032", (manifest) => { manifest.optional_permissions = ["tabs"]; }],
        ["CAP-NEG-033", (manifest) => { manifest.externally_connectable = { matches: ["https://example.invalid/*"] }; }],
        ["CAP-NEG-034", (manifest) => { manifest.content_scripts = [{ matches: ["<all_urls>"] }]; }],
        ["CAP-NEG-035", (manifest) => { manifest.web_accessible_resources = [{ resources: ["*"] }]; }],
        [
            "CAP-NEG-036",
            (manifest) => {
                manifest.content_security_policy = {
                    extension_pages: "script-src 'self' 'unsafe-eval'; object-src 'self'",
                };
            },
        ],
        ["CAP-NEG-044", (manifest) => { manifest.action = { default_title: "Hybrid Discovery held pending review", default_popup: "popup.html" }; }],
        ["CAP-NEG-045", (manifest) => { manifest.background = { service_worker: "remote.js", type: "classic" }; }],
        ["CAP-NEG-046", (manifest) => { manifest.commands = { run: {} }; }],
        ["CAP-NEG-047", (manifest) => { manifest.side_panel = { default_path: "panel.html" }; }],
        ["CAP-NEG-048", (manifest) => { manifest.devtools_page = "devtools.html"; }],
        ["CAP-NEG-049", (manifest) => { manifest.omnibox = { keyword: "discover" }; }],
        ["CAP-NEG-050", (manifest) => { manifest.sandbox = { pages: ["sandbox.html"] }; }],
        ["CAP-NEG-051", (manifest) => { manifest.optional_host_permissions = ["https://example.invalid/*"]; }],
        ["CAP-NEG-052", (manifest) => { manifest.permissions = ["nativeMessaging"]; }],
        ["CAP-NEG-053", (manifest) => { manifest.key = "mutated"; }],
        ["CAP-NEG-054", (manifest) => { manifest.unknown_executable_surface = {}; }],
        ["CAP-NEG-055", (manifest) => { manifest.action = { default_title: "Mutated" }; }],
        ["CAP-NEG-078", (manifest) => { manifest.name = "Mutated"; }],
    ];
    for (const [index, [vectorId, mutate]] of mutations.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-manifest-${String(index)}-`));
        const mutated = structuredClone(actual);
        mutate(mutated);
        const path = resolve(root, "manifest.json");
        writeFileSync(path, JSON.stringify(mutated));
        assert.deepEqual(verifyCapabilityManifest(path, canonicalPath), ["E_MANIFEST_CAPABILITY_MISMATCH"], vectorId);
    }
});
void test("all canonical source escape vectors execute against the AST verifier", () => {
    const fixtures = [
        ["CAP-NEG-001", "export function sendCdpCommand(method: string, params: object) {}", "E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"],
        ["CAP-NEG-002", "sendLiteralCommand('Network.' + operation)", "E_CDP_METHOD_NOT_LITERAL"],
        ["CAP-NEG-003", "const send = chrome.debugger.sendCommand", "E_PRIVILEGED_API_ALIAS"],
        ["CAP-NEG-004", "const {sendCommand} = chrome.debugger", "E_PRIVILEGED_API_ALIAS"],
        ["CAP-NEG-005", "chrome.debugger.sendCommand.call(adapter, target, 'Network.disable', {})", "E_INDIRECT_PRIVILEGED_CALL"],
        ["CAP-NEG-006", "await import(moduleName)", "E_DYNAMIC_MODULE_LOADING"],
        ["CAP-NEG-007", "require(moduleName)", "E_DYNAMIC_MODULE_LOADING"],
        ["CAP-NEG-008", "eval(source); new Function(source)", "E_DYNAMIC_CODE"],
        ["CAP-NEG-009", "import 'https://example.invalid/chunk.js'", "E_REMOTE_OR_SPLIT_CODE"],
        ["CAP-NEG-010", "chrome.debugger.sendCommand(target, 'Runtime.evaluate', {})", "E_CDP_METHOD_DENIED"],
        ["CAP-NEG-011", "chrome.debugger.sendCommand(target, 'Runtime.callFunctionOn', {})", "E_CDP_METHOD_DENIED"],
        ["CAP-NEG-012", "chrome.debugger.sendCommand(target, 'Fetch.enable', {})", "E_CDP_DOMAIN_DENIED"],
        ["CAP-NEG-013", "chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {})", "E_CDP_DOMAIN_DENIED"],
        ["CAP-NEG-014", "chrome.debugger.sendCommand(target, 'Page.navigate', {})", "E_CDP_METHOD_DENIED"],
        ["CAP-NEG-015", "chrome.debugger.sendCommand(target, 'Network.replayXHR', {})", "E_CDP_METHOD_DENIED"],
        ["CAP-NEG-016", "chrome.debugger.sendCommand(target, 'DOM.setAttributeValue', {})", "E_CDP_DOMAIN_DENIED"],
        ["CAP-NEG-017", "chrome.debugger.sendCommand(target, 'CSS.setStyleTexts', {})", "E_CDP_DOMAIN_DENIED"],
        ["CAP-NEG-018", "chrome.debugger.sendCommand(target, 'Network.getResponseBody', {})", "E_CDP_METHOD_DENIED"],
        ["CAP-NEG-019", "chrome.debugger.sendCommand(target, 'Target.getTargets', {})", "E_TARGET_DOMAIN_DENIED"],
        ["CAP-NEG-020", "fetch(url, {method: 'POST', body})", "E_OUTBOUND_NETWORK_PATH"],
        ["CAP-NEG-021", "new XMLHttpRequest(); form.submit(); navigator.sendBeacon(url, body)", "E_OUTBOUND_NETWORK_PATH"],
        ["CAP-NEG-022", "new WebSocket(userUrl)", "E_LOOPBACK_URL_NOT_LITERAL"],
        ["CAP-NEG-023", "window.postMessage({command: 'ATTACH'}, '*')", "E_PAGE_COMMAND_CHANNEL"],
        ["CAP-NEG-024", "chrome.runtime.onMessageExternal.addListener(handler)", "E_UNTRUSTED_COMMAND_CHANNEL"],
        ["CAP-NEG-025", "consume({message_type: 'COMMAND', action: 'attach'})", "E_LOOPBACK_FACT_UNION"],
        ["CAP-NEG-026", "consume({message_type: 'ACK_CURSOR_FACT_V1', cdp_method: 'Runtime.evaluate'})", "E_LOOPBACK_FACT_UNION"],
        ["CAP-NEG-027", "chrome.debugger.attach({targetId}, '1.3')", "E_SELECTED_TARGET_BINDING"],
        ["CAP-NEG-028", "chrome.debugger.sendCommand({sessionId}, 'Network.disable', {})", "E_CHILD_SESSION_DENIED"],
        ["CAP-NEG-029", "observeFrame(unownedFrameId)", "E_FRAME_OWNERSHIP"],
        ["CAP-NEG-030", "location.href = 'https://example.invalid/away'", "E_LOCATION_SAFETY_STOP"],
        ["CAP-NEG-038", "runFixedProbe('APP_LOCATION_CONTEXT_V1', '#selector')", "E_FIXED_PROBE_SHAPE"],
        ["CAP-NEG-039", "runFixedProbe('UNKNOWN_PROBE')", "E_FIXED_PROBE_ID"],
        ["CAP-NEG-040", "const save = localStorage.setItem.bind(localStorage); save('raw', event)", "E_PERSISTENCE_BEFORE_PROJECTION"],
        ["CAP-NEG-041", "persist({url: event.url, query: event.query, cookie: event.cookie})", "E_EVENT_FIELD_DENIED"],
        ["CAP-NEG-042", "automaticBackup(); deleteAckedRecord(record)", "E_CUSTODY_PATH_DENIED"],
        ["CAP-NEG-043", "placeWager(); mutateBetslip(); requestCashout(); providerPerformanceProbe()", "E_PRODUCTION_CAPABILITY_REACHABLE"],
    ];
    for (const [index, [vectorId, source, expected]] of fixtures.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-vector-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.ok(verifyCapabilityGraph(root).includes(expected), vectorId);
    }
});
void test("CAP-NEG-037 executes body-class denial against canonical policy", () => {
    const root = mkdtempSync(resolve(tmpdir(), "capability-body-class-"));
    const canonical = JSON.parse(readFileSync(resolve("vendor/hybrid-discovery-v6.3.6/security/discovery-capability-manifest.v1.json"), "utf8"));
    canonical.body_classes = ["RESPONSE_BODY"];
    const canonicalPath = resolve(root, "canonical.json");
    writeFileSync(canonicalPath, JSON.stringify(canonical));
    assert.deepEqual(verifyCapabilityManifest(resolve("extension/manifest.json"), canonicalPath), ["E_BODY_CLASS_NOT_PERMITTED"]);
});
void test("CAP-NEG-056 through CAP-NEG-077 execute exact Chrome and storage denials", () => {
    const cases = [
        ["CAP-NEG-056", "src/security/cdp-broker.ts", "export class ClosedCdpBroker { run(){ chrome.debugger.attach({targetId}, '1.3'); } }", "E_SELECTED_TARGET_BINDING"],
        ["CAP-NEG-057", "src/security/cdp-broker.ts", "export class ClosedCdpBroker { run(selectedTabId:number, version:string){ chrome.debugger.attach({tabId:selectedTabId}, version); } }", "E_DEBUGGER_PROTOCOL_VERSION"],
        ["CAP-NEG-058", "src/security/cdp-broker.ts", "export class ClosedCdpBroker { run(){ chrome.debugger.detach({sessionId}); } }", "E_SELECTED_TARGET_BINDING"],
        ["CAP-NEG-059", "src/security/cdp-broker.ts", "export class ClosedCdpBroker { run(){ chrome.debugger.onEvent.addListener((source,method,params)=>{}); } }", "E_CHILD_SESSION_DENIED"],
        ["CAP-NEG-060", "src/security/cdp-broker.ts", "export class ClosedCdpBroker { run(){ chrome.debugger.onDetach.addListener((source,reason)=>{}); } }", "E_SELECTED_TARGET_BINDING"],
        ["CAP-NEG-061", "fixture.ts", "chrome.debugger.getTargets()", "E_CHROME_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-062", "src/security/fixed-probes.ts", "export function runFixedProbe(){ chrome.scripting.executeScript({target:{allFrames:true},files:['evil.js'],world:'MAIN'}); }", "E_FIXED_PROBE_SHAPE"],
        ["CAP-NEG-063", "src/security/target-policy.ts", "export function assertOwnedTarget(){ chrome.webNavigation.getFrame({tabId:1,frameId:0}); }", "E_CHROME_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-064", "src/security/run-controller.ts", "export class DiscoveryRunController { run(){ chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{}); } }", "E_UNTRUSTED_COMMAND_CHANNEL"],
        ["CAP-NEG-065", "src/security/run-controller.ts", "export class DiscoveryRunController { run(){ chrome.action.openPopup(); } }", "E_CHROME_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-066", "src/security/target-policy.ts", "export function assertOwnedTarget(){ chrome.tabs.query({}); }", "E_CHROME_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-067", "src/security/cdp-broker.ts", "export function escape(target:chrome.debugger.Debuggee){ chrome.debugger.sendCommand(target,'Network.disable',{}); }", "E_PRIVILEGED_SINK_OUTSIDE_CLOSED_BROKER"],
        ["CAP-NEG-068", "src/security/cdp-broker.ts", "export function sendLiteralCommand(target:chrome.debugger.Debuggee){ chrome.debugger.sendCommand(target,'Network.enable',{maxPostDataSize:1}); }", "E_CDP_PARAMETER_MISMATCH"],
        ["CAP-NEG-069", "src/security/target-policy.ts", "export function assertOwnedTarget(){ chrome.webNavigation.onCommitted.addListener((details)=>{}); }", "E_CHROME_API_PARAMETER_MISMATCH"],
        ["CAP-NEG-070", "src/security/run-controller.ts", "export class DiscoveryRunController { run(){ chrome.runtime.connectNative('host'); } }", "E_CHROME_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-071", "fixture.ts", "indexedDB.databases()", "E_PERSISTENCE_API_NOT_ALLOWLISTED"],
        ["CAP-NEG-072", "fixture.ts", "spool.append(rawEvent)", "E_PERSISTENCE_BEFORE_PROJECTION"],
        ["CAP-NEG-073", "src/spool.ts", "export class Spool { run(databaseName:string){ indexedDB.open(databaseName,2); } }", "E_PERSISTENCE_CONTRACT_MISMATCH"],
        ["CAP-NEG-074", "src/spool.ts", "export class Spool { run(){ indexedDB.deleteDatabase('old'); } }", "E_CUSTODY_PATH_DENIED"],
        ["CAP-NEG-075", "src/spool.ts", "export class Spool { run(store:IDBObjectStore,key:IDBValidKey,rawEvent:unknown){ store.add(rawEvent,key); } }", "E_PERSISTENCE_BEFORE_PROJECTION"],
        ["CAP-NEG-076", "src/security/run-controller.ts", "export class DiscoveryRunController { run(){ chrome.action.onClicked.addListener((tab,info)=>{}, extra); } }", "E_CHROME_API_SIGNATURE_MISMATCH"],
        ["CAP-NEG-077", "src/security/run-controller.ts", `export class DiscoveryRunController { run(){ chrome.runtime.onMessage.addListener(async (message,sender,sendResponse)=>{ if(sender.id!=="anfddcancelbmpogbmckmjckjlnpmpjk"||sender.origin!=="chrome-extension://anfddcancelbmpogbmckmjckjlnpmpjk"||sender.tab!==undefined){return;} }); } }`, "E_CHROME_API_SIGNATURE_MISMATCH"],
    ];
    for (const [index, [vectorId, relativePath, source, expected]] of cases.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-final-vector-${String(index)}-`));
        const path = resolve(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, source);
        assert.ok(verifyCapabilityGraph(root).includes(expected), vectorId);
    }
});
void test("computed Chrome roots, IDB types, DOM mutation, and dynamic carriers fail closed", () => {
    const cases = [
        ["computed root", "const member=unknown; chrome[member]()"],
        ["computed debugger", "const member=unknown; chrome.debugger[member]()"],
        ["global computed root", "const member=unknown; globalThis['chrome'][member]()"],
        ["bare Chrome carrier", "const c=chrome; consume(c)"],
        ["Reflect Chrome carrier", "Reflect.get(chrome,'debugger')"],
        ["typed IDBIndex", "const index=null as unknown as IDBIndex; index.get('key')"],
        ["unlisted IDB method", "const x=null as unknown as IDBObjectStore; x.getAll()"],
        ["DOM mutation", "document.body.replaceChildren(node)"],
        ["location mutation", "location.replace(url); history.pushState({},'',url)"],
        ["string timer", "setTimeout('fetch(url)', 1)"],
        ["require carrier", "const r=(()=>require)(); r(name)"],
        ["eval carrier", "const e=(()=>eval)(); e(source)"],
        ["Function carrier", "const F=(()=>Function)(); new F(source)"],
    ];
    for (const [index, [name, source]] of cases.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-adversarial-final-${String(index)}-`));
        writeFileSync(resolve(root, "fixture.ts"), source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
});
void test("deny-first analyzer rejects the independent adversarial escape corpus", () => {
    const cases = [
        ["descriptor Chrome carrier", "fixture.ts", "Object.getOwnPropertyDescriptor(globalThis,'chrome').value.debugger.sendCommand({tabId:1},'Runtime.evaluate',{})"],
        ["style mutation", "fixture.ts", "element.style.setProperty(name,value)"],
        ["property mutation", "fixture.ts", "element.className=value"],
        ["EventSource", "fixture.ts", "new EventSource(url)"],
        ["Worker source", "fixture.ts", "new Worker(URL.createObjectURL(new Blob([source])))"],
        ["Reflect message handler", "fixture.ts", "Reflect.set(window,'onmessage',handler)"],
        ["computed CDP method", "src/security/cdp-broker.ts", "export const sendLiteralCommand=(authorization)=>chrome.debugger.sendCommand({tabId:authorization.browser_binding.tab_id},'Network.'+'disable',{})"],
        ["shadowed fixed probe", "src/security/fixed-probes.ts", "const APP_LOCATION_CONTEXT_V1=()=>userControlled; export function runFixedProbe(authorization,ownedFrameId){chrome.scripting.executeScript({target:{tabId:authorization.browser_binding.tab_id,frameIds:[ownedFrameId]},world:'ISOLATED',func:APP_LOCATION_CONTEXT_V1,args:[]})}"],
        ["CacheStorage", "src/spool.ts", "export class Spool{append(){caches.open('archive')}}"],
        ["session storage", "src/spool.ts", "export class Spool{append(){sessionStorage.setItem('raw',value)}}"],
        ["indexedDB cmp", "src/spool.ts", "export class Spool{append(){indexedDB.cmp(left,right)}}"],
        ["upgrade call outside handler", "src/spool.ts", "export class Spool{append(db:IDBDatabase){db.createObjectStore('stream_state_v1',{autoIncrement:false})}}"],
        ["empty upgrade handler", "src/spool.ts", "export class Spool{append(request:IDBOpenDBRequest){request.onupgradeneeded=(event)=>{}}}"],
        ["constructed raw append", "fixture.ts", "new Spool().append(raw)"],
        ["factory raw append", "fixture.ts", "makeSpool().append(raw)"],
        ["raw logging", "fixture.ts", "console.log(rawCdpEvent)"],
        ["raw hashing", "fixture.ts", "crypto.subtle.digest('SHA-256',rawBytes)"],
        ["loopback command shorthand", "src/security/loopback.ts", "export class AuthenticatedLoopback{open(command){const socket=new WebSocket('ws://127.0.0.1:8765');socket.send(encodeAuthenticatedFact({command}))}}"],
        ["loopback spread", "src/security/loopback.ts", "export class AuthenticatedLoopback{open(payload){const socket=new WebSocket('ws://127.0.0.1:8765');socket.send(encodeAuthenticatedFact({...payload}))}}"],
        ["importScripts", "fixture.ts", "importScripts(url)"],
    ];
    for (const [index, [name, relativePath, source]] of cases.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-review-corpus-${String(index)}-`));
        const path = resolve(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
});
void test("DOM provenance, typed authorization, canonical projection, and raw aliases fail closed", () => {
    const cases = [
        ["created anchor navigation", "fixture.ts", "const x=document.createElement('a');x.href=url"],
        ["compound DOM assignment", "fixture.ts", "document.body.innerHTML+=html"],
        ["Object.assign DOM mutation", "fixture.ts", "Object.assign(element,{innerHTML:html})"],
        ["image beacon", "fixture.ts", "const image=new Image();image.src=url"],
        [
            "untyped authorization",
            "src/security/cdp-broker.ts",
            "export const sendLiteralCommand=(authorization:any)=>chrome.debugger.sendCommand({tabId:authorization.browser_binding.tab_id},'Network.disable',{})",
        ],
        [
            "local projection decoy",
            "src/spool.ts",
            "const projectBeforePersistence=(input:any)=>input;new Spool().append(projectBeforePersistence(raw))",
        ],
        ["raw alias logging", "fixture.ts", "const bytes=rawCdpEvent;console.log(bytes)"],
        ["raw CDP bytes hashing", "fixture.ts", "crypto.subtle.digest('SHA-256',rawCdpBytes)"],
        [
            "raw alias hashing",
            "fixture.ts",
            "const bytes=rawCdpBytes;crypto.subtle.digest('SHA-256',bytes)",
        ],
    ];
    for (const [index, [name, relativePath, source]] of cases.entries()) {
        const root = mkdtempSync(resolve(tmpdir(), `capability-final-corpus-${String(index)}-`));
        const path = resolve(root, relativePath);
        mkdirSync(resolve(path, ".."), { recursive: true });
        writeFileSync(path, source);
        assert.notDeepEqual(verifyCapabilityGraph(root), [], name);
    }
});
void test("all seven canonical allowed controls pass source and compiled graph ownership", () => {
    const root = mkdtempSync(resolve(tmpdir(), "capability-positive-full-"));
    const sourceRoot = resolve(root, "extension/src");
    const distRoot = resolve(root, "extension/dist");
    mkdirSync(resolve(sourceRoot, "security"), { recursive: true });
    mkdirSync(resolve(distRoot, "security"), { recursive: true });
    const sourceFiles = {
        "security/contracts": `
      export type DiscoveryRunAuthorization=Readonly<{browser_binding:Readonly<{tab_id:number,browser_run_id:string}>}>;
      export type PublicMessage=Readonly<{message_type:string}>;
      export type SanitizedFact=Readonly<{fact_type:string}>;
    `,
        "security/helpers": `
      import type {PublicMessage,SanitizedFact} from "./contracts.js";
      export const projectCdpEvent=(_method:string,_params:unknown):SanitizedFact=>({fact_type:"CDP_EVENT_V1"});
      export const projectNavigationEvent=(_details:unknown):SanitizedFact=>({fact_type:"NAVIGATION_EVENT_V1"});
      export const safetyStopAndSealRun=():never=>{throw new Error("SAFETY_STOP");};
      export const handlePublicMessage=(_message:PublicMessage):Readonly<{message_type:"DISCOVERY_STATUS_V1"}>=>({message_type:"DISCOVERY_STATUS_V1"});
      export const encodeAuthenticatedFact=(_fact:SanitizedFact,_secret:string,_sessionId:string,_direction:"CLIENT_TO_BACKEND",_counter:number):ArrayBuffer=>new ArrayBuffer(0);
      export const decodeAuthenticatedFact=(_data:unknown,_secret:string,_sessionId:string,_direction:"BACKEND_TO_CLIENT",_counter:number):SanitizedFact=>({fact_type:"AUTHENTICATED_FACT_V1"});
      export const validateRequestSuccess=(event:Event):void=>{if(event.target===null){throw new Error("SAFETY_STOP");}};
      export const abortAndFailClosed=(_event:Event):never=>{throw new Error("SAFETY_STOP");};
      export const failClosedNoAppend=(_event:Event):never=>{throw new Error("SAFETY_STOP");};
      export const closeAndFailClosed=(_event:Event):never=>{throw new Error("SAFETY_STOP");};
      export type DurableCompletion<T>=Readonly<{promise:Promise<T>,resolve:(value:T)=>void,reject:(error:Error)=>void}>;
      export const createPendingDurabilityPromise=<T>():DurableCompletion<T>=>{
        let resolveValue:(value:T)=>void=()=>{};
        let rejectValue:(error:Error)=>void=()=>{};
        const promise=new Promise<T>((resolve,reject)=>{resolveValue=resolve;rejectValue=reject;});
        return {promise,resolve:resolveValue,reject:rejectValue};
      };
      export const resolveDurablySpooled=<T>(completion:DurableCompletion<T>,value:T):void=>{completion.resolve(value);};
      export const failClosedNoDurabilityClaim=<T>(_event:Event,completion:DurableCompletion<T>):void=>{completion.reject(new Error("SAFETY_STOP"));};
    `,
        "security/cdp-broker": `
      import type {DiscoveryRunAuthorization} from "./contracts.js";
      import {projectCdpEvent,safetyStopAndSealRun} from "./helpers.js";
      const ALLOWED_NETWORK_EVENTS=new Set([
        "Network.requestWillBeSent","Network.responseReceived","Network.dataReceived",
        "Network.loadingFinished","Network.loadingFailed","Network.webSocketCreated",
        "Network.webSocketWillSendHandshakeRequest","Network.webSocketHandshakeResponseReceived",
        "Network.webSocketFrameReceived","Network.webSocketFrameSent","Network.webSocketFrameError",
        "Network.webSocketClosed","Network.eventSourceMessageReceived"
      ]);
      export const sendLiteralCommand = (authorization:DiscoveryRunAuthorization) => {
        const selectedTabId=authorization.browser_binding.tab_id;
        chrome.debugger.sendCommand({tabId:selectedTabId},"Network.enable",{maxTotalBufferSize:33554432,maxResourceBufferSize:2097152,maxPostDataSize:0});
        chrome.debugger.sendCommand({tabId:selectedTabId},"Network.disable",{});
      };
      export class ClosedCdpBroker { open(authorization:DiscoveryRunAuthorization) {
        const selectedTabId=authorization.browser_binding.tab_id;
        chrome.debugger.attach({tabId:selectedTabId},"1.3");
        chrome.debugger.onEvent.addListener((source,method,params)=>{
          if(source.tabId!==selectedTabId||source.sessionId!==undefined||source.targetId!==undefined||source.extensionId!==undefined||Object.keys(source).length!==1){throw new Error("SAFETY_STOP");}
          if(!ALLOWED_NETWORK_EVENTS.has(method)){throw new Error("SAFETY_STOP");}
          projectCdpEvent(method,params);
        });
        chrome.debugger.onDetach.addListener((source,reason)=>{
          // @ts-expect-error pinned Chrome types omit DebuggerSession.sessionId on this event source
          if(source.tabId!==selectedTabId||source.sessionId!==undefined||source.targetId!==undefined||source.extensionId!==undefined||Object.keys(source).length!==1||(reason!=="target_closed"&&reason!=="canceled_by_user")){throw new Error("SAFETY_STOP");}
          safetyStopAndSealRun();
        });
        chrome.debugger.detach({tabId:selectedTabId});
      }}
    `,
        "security/fixed-probes": `
      import type {DiscoveryRunAuthorization} from "./contracts.js";
      type ProbeOutput=Readonly<{origin_id?:string,path_template_id?:string,ready_state?:string,visibility_state?:string,has_focus?:boolean,document_context?:string}>;
      const APP_LOCATION_CONTEXT_V1=()=>({origin_id:"MOJ_ESPACEJEUX",path_template_id:"ROOT"});
      const DOM_DOCUMENT_LIFECYCLE_V1=()=>({ready_state:document.readyState,visibility_state:document.visibilityState,has_focus:document.hasFocus(),document_context:"CURRENT_OWNED_DOCUMENT"});
      const validateFixedProbeResult:(results:chrome.scripting.InjectionResult<ProbeOutput>[],ownedFrameId:number,ownedDocumentId:string,probeId:string)=>void=(results,ownedFrameId,ownedDocumentId,probeId)=>{
        if(results.length!==1||results[0].frameId!==ownedFrameId||results[0].documentId!==ownedDocumentId){throw new Error("SAFETY_STOP");}
        const result=results[0].result;
        const exactApp=probeId==="APP_LOCATION_CONTEXT_V1"&&result?.origin_id==="MOJ_ESPACEJEUX"&&result?.path_template_id==="ROOT"&&Object.keys(result).sort().join(",")==="origin_id,path_template_id";
        const exactDom=probeId==="DOM_DOCUMENT_LIFECYCLE_V1"&&result?.ready_state!==undefined&&["loading","interactive","complete"].includes(result.ready_state)&&result?.visibility_state!==undefined&&["hidden","visible"].includes(result.visibility_state)&&typeof result?.has_focus==="boolean"&&result?.document_context==="CURRENT_OWNED_DOCUMENT"&&Object.keys(result).sort().join(",")==="document_context,has_focus,ready_state,visibility_state";
        if(!(exactApp||exactDom)){throw new Error("SAFETY_STOP");}
      };
      export async function runFixedProbe(authorization:DiscoveryRunAuthorization,ownedFrameId:number,ownedDocumentId:string){
        const selectedTabId=authorization.browser_binding.tab_id;
        const appResult=await chrome.scripting.executeScript({target:{tabId:selectedTabId,frameIds:[ownedFrameId]},world:"ISOLATED",func:APP_LOCATION_CONTEXT_V1,args:[]});
        validateFixedProbeResult(appResult,ownedFrameId,ownedDocumentId,"APP_LOCATION_CONTEXT_V1");
        const domResult=await chrome.scripting.executeScript({target:{tabId:selectedTabId,frameIds:[ownedFrameId]},world:"ISOLATED",func:DOM_DOCUMENT_LIFECYCLE_V1,args:[]});
        validateFixedProbeResult(domResult,ownedFrameId,ownedDocumentId,"DOM_DOCUMENT_LIFECYCLE_V1");
      }
    `,
        "security/target-policy": `
      import type {DiscoveryRunAuthorization} from "./contracts.js";
      import {projectNavigationEvent,safetyStopAndSealRun} from "./helpers.js";
      export function assertOwnedTarget(authorization:DiscoveryRunAuthorization,ownedFrameId:number){
        const selectedTabId=authorization.browser_binding.tab_id;
        chrome.webNavigation.getAllFrames({tabId:selectedTabId});
        const filter={url:[{hostEquals:"miseojeu.espacejeux.com",pathEquals:"/"}]};
        const listener=(details:chrome.webNavigation.WebNavigationBaseCallbackDetails)=>{
          if(details.tabId!==selectedTabId||details.frameId!==ownedFrameId){throw new Error("SAFETY_STOP");}
          const location=new URL(details.url);
          if(location.protocol!=="https:"||location.hostname!=="miseojeu.espacejeux.com"||location.pathname!=="/"||location.username!==""||location.password!==""||location.search!==""||location.hash!==""){throw new Error("SAFETY_STOP");}
          projectNavigationEvent(details);
        };
        chrome.webNavigation.onBeforeNavigate.addListener(listener,filter);
        chrome.webNavigation.onCommitted.addListener(listener,filter);
        chrome.webNavigation.onHistoryStateUpdated.addListener(listener,filter);
        chrome.webNavigation.onReferenceFragmentUpdated.addListener(listener,filter);
        chrome.webNavigation.onErrorOccurred.addListener(listener,filter);
        chrome.webNavigation.onTabReplaced.addListener((details)=>{
          if(details.replacedTabId!==selectedTabId){throw new Error("SAFETY_STOP");}
          safetyStopAndSealRun();
        });
      }
    `,
        "security/run-controller": `
      import type {DiscoveryRunAuthorization,PublicMessage} from "./contracts.js";
      import {handlePublicMessage} from "./helpers.js";
      const PUBLIC_MESSAGE_TYPES=new Set([
        "DISCOVERY_BEGIN_V1","DISCOVERY_STOP_V1","DISCOVERY_STATUS_GET_V1",
        "DISCOVERY_EXPORT_SANITIZED_V1","DESTROY_WHOLE_RUN_WORKING_STORAGE_V1"
      ]);
      export class DiscoveryRunController { open(authorization:DiscoveryRunAuthorization){
        const selectedTabId=authorization.browser_binding.tab_id;
        chrome.action.onClicked.addListener((tab)=>{
          if(tab.id!==selectedTabId||tab.url===undefined){throw new Error("SAFETY_STOP");}
          const location=new URL(tab.url);
          if(location.protocol!=="https:"||location.hostname!=="miseojeu.espacejeux.com"||location.pathname!=="/"||location.username!==""||location.password!==""||location.search!==""||location.hash!==""){throw new Error("SAFETY_STOP");}
        });
        chrome.runtime.onMessage.addListener((message:PublicMessage,sender,sendResponse)=>{
          if(sender.id!=="anfddcancelbmpogbmckmjckjlnpmpjk"||sender.origin!=="chrome-extension://anfddcancelbmpogbmckmjckjlnpmpjk"||sender.tab!==undefined){return;}
          if(typeof message!=="object"||message===null||!PUBLIC_MESSAGE_TYPES.has(message.message_type)||Object.keys(message).length!==1){return;}
          sendResponse(handlePublicMessage(message));
        });
      }}
    `,
        "security/loopback": `
      import type {SanitizedFact} from "./contracts.js";
      import {decodeAuthenticatedFact,encodeAuthenticatedFact} from "./helpers.js";
      export class AuthenticatedLoopback { open(fact:SanitizedFact,pairingSecret:string,sessionId:string,nextOutboundCounter:number,nextInboundCounter:number){
        const socket=new WebSocket("ws://127.0.0.1:8765");
        socket.send(encodeAuthenticatedFact(fact,pairingSecret,sessionId,"CLIENT_TO_BACKEND",nextOutboundCounter));
        socket.addEventListener("message",(event)=>{decodeAuthenticatedFact(event.data,pairingSecret,sessionId,"BACKEND_TO_CLIENT",nextInboundCounter);});
      }}
    `,
        "security/redaction": `
      declare const sanitizedBrand:unique symbol;
      export type PersistableSanitizedObservationV1=Readonly<{readonly [sanitizedBrand]:never,readonly canonicalSanitizedBytes:Uint8Array}>;
      export function projectBeforePersistence(input:unknown):PersistableSanitizedObservationV1{void input;throw new Error("NOT_IMPLEMENTED");}
    `,
        "spool": `
      import type {DiscoveryRunAuthorization} from "./security/contracts.js";
      import {projectBeforePersistence} from "./security/redaction.js";
      import type {PersistableSanitizedObservationV1} from "./security/redaction.js";
      import {abortAndFailClosed,closeAndFailClosed,createPendingDurabilityPromise,failClosedNoAppend,failClosedNoDurabilityClaim,resolveDurablySpooled,validateRequestSuccess} from "./security/helpers.js";
      import type {DurableCompletion} from "./security/helpers.js";
      type SpoolRecord=Readonly<{record_type:"SpoolRecord"}>;
      const LOWERCASE_UUID_V4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
      export class Spool { readonly authorization:DiscoveryRunAuthorization;constructor(authorization:DiscoveryRunAuthorization){this.authorization=authorization;} append(value:PersistableSanitizedObservationV1):Promise<SpoolRecord>{
        const authorization=this.authorization;
        const durableCompletion:DurableCompletion<SpoolRecord>=createPendingDurabilityPromise();
        const committedRecord:SpoolRecord={record_type:"SpoolRecord"};
        if(!LOWERCASE_UUID_V4.test(authorization.browser_binding.browser_run_id)){throw new Error("SAFETY_STOP");}
        const databaseName="hybrid-discovery-v6.2-working-"+authorization.browser_binding.browser_run_id;
        const request=indexedDB.open(databaseName,1);
        request.onupgradeneeded=(event)=>{
          if(event.oldVersion!==0||event.newVersion!==1){throw new Error("SAFETY_STOP");}
          const db=request.result;
          db.createObjectStore("stream_state_v1",{autoIncrement:false});
          const spoolStore=db.createObjectStore("spool_entries_v1",{autoIncrement:false});
          spoolStore.createIndex("by_spool_record_id","spool_record.spool_record_id",{unique:true,multiEntry:false});
          spoolStore.createIndex("by_raw_observation_id","spool_record.raw_observation_id",{unique:true,multiEntry:false});
        };
        request.onsuccess=(event)=>{
          validateRequestSuccess(event);
          const db=request.result;
          const tx=db.transaction(["stream_state_v1","spool_entries_v1"],"readwrite",{durability:"strict"});
          const stateStore=tx.objectStore("stream_state_v1");
          const entryStore=tx.objectStore("spool_entries_v1");
          const streamKey="stream";
          const positionKey="position";
          const entry={record_type:"SpoolRecord"} as const;
          const state={next_position:"1"};
          const lowerKey="0";
          const upperKey="z";
          stateStore.get(streamKey);
          entryStore.add(entry,positionKey);
          stateStore.put(state,streamKey);
          const range=IDBKeyRange.bound(lowerKey,upperKey,false,false);
          const cursorRequest=entryStore.openCursor(range,"next");
          cursorRequest.onsuccess=(event)=>{validateRequestSuccess(event);const cursor=cursorRequest.result;if(cursor!==null){cursor.continue();}};
          cursorRequest.onerror=(event)=>{abortAndFailClosed(event);};
          tx.oncomplete=(event)=>{resolveDurablySpooled(durableCompletion,committedRecord);};
          tx.onabort=(event)=>{failClosedNoDurabilityClaim(event,durableCompletion);};
          tx.onerror=(event)=>{abortAndFailClosed(event);};
          db.onversionchange=(event)=>{closeAndFailClosed(event);};
        };
        request.onerror=(event)=>{abortAndFailClosed(event);};
        request.onblocked=(event)=>{failClosedNoAppend(event);};
        return durableCompletion.promise;
      }}
      export const enqueue=(spool:Spool,input:unknown):Promise<SpoolRecord>=>spool.append(projectBeforePersistence(input));
    `,
    };
    for (const [relativePath, source] of Object.entries(sourceFiles)) {
        const sourcePath = resolve(sourceRoot, `${relativePath}.ts`);
        mkdirSync(resolve(sourcePath, ".."), { recursive: true });
        writeFileSync(sourcePath, source);
    }
    const configPath = resolve(root, "extension/tsconfig.json");
    writeFileSync(resolve(root, "extension/package.json"), '{"type":"module"}\n');
    writeFileSync(configPath, `${JSON.stringify({
        compilerOptions: {
            lib: ["ES2024", "DOM"],
            module: "NodeNext",
            moduleResolution: "NodeNext",
            noEmitOnError: true,
            outDir: distRoot,
            rootDir: sourceRoot,
            skipLibCheck: true,
            strict: true,
            target: "ES2024",
            typeRoots: [resolve("extension/node_modules/@types")],
            types: ["chrome"],
        },
        include: ["src/**/*.ts"],
    }, undefined, 2)}\n`);
    const compile = spawnSync(process.execPath, [resolve("extension/node_modules/typescript/bin/tsc"), "-p", configPath], { encoding: "utf8" });
    assert.equal(compile.status, 0, `positive capability graph must typecheck and link:\n${compile.stdout}${compile.stderr}`);
    writeFileSync(resolve(root, "extension/manifest.json"), readFileSync(resolve("extension/manifest.json")));
    assert.deepEqual(verifyCapabilityGraph(sourceRoot), []);
});
